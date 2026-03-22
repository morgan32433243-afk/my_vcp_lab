import os
import ssl

# 解決 macOS 上 Python 3.x 抓取網頁時的 SSL 憑證驗證失敗問題
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['PYTHONHTTPSVERIFY'] = '0'

from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np
import re
import requests
import time
import math
from collections import defaultdict
from VCP技術分析核心 import analyze_vcp, format_vcp_amount
import json

# Session-based cache to avoid API limits during manual queries
fundamental_cache = {
    "revenue": {}, # ticker -> (yoy, accel, msg)
    "eps":     {}  # ticker -> (yoy, margins, msg)
}


# ============================================================
# 大盤環境判定
# ============================================================
def get_market_status():
    """
    判斷加權指數 (TAIEX) 是否處於多頭環境：
    - 收盤 > 200MA
    - 20MA > 60MA
    """
    try:
        import yfinance as yf
        end = datetime.now()
        start = end - timedelta(days=400)
        df = yf.download("^TWII", start=start, end=end, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty or len(df) < 60:
            return True, "無法取得大盤資料，預設放行"
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        df['MA200'] = df['Close'].rolling(200).mean()
        latest = df.iloc[-1]
        close = latest['Close'].item() if hasattr(latest['Close'], 'item') else float(latest['Close'])
        ma20  = latest['MA20'].item() if hasattr(latest['MA20'], 'item') else float(latest['MA20'])
        ma60  = latest['MA60'].item() if hasattr(latest['MA60'], 'item') else float(latest['MA60'])
        ma200 = latest['MA200'].item() if hasattr(latest['MA200'], 'item') else float(latest['MA200'])
        above_200 = close > ma200
        ma_rising = ma20 > ma60
        status_ok = above_200 and ma_rising
        msg = f"TAIEX {close:.0f} | 200MA: {ma200:.0f} | 20MA{'>' if ma_rising else '<'}60MA → {'✅ 多頭環境' if status_ok else '⚠️  大盤偏弱，謹慎操作'}"
        return status_ok, msg
    except Exception as e:
        return True, f"大盤判定失敗 ({e})，預設放行"


# ============================================================
# RS Rating 計算 (全市場相對強度 Percentile Rank) - 加權版
# ============================================================
RS_CACHE_FILE = f"rs_weighted_cache_{datetime.now().strftime('%Y-%m-%d')}.json"

def calculate_rs_ratings(tickers):
    """
    批次下載全市場 1 年期數據，並計算加權 RS (0~100 Percentile)。
    公式：(C0/C63 * 0.4) + (C0/C126 * 0.2) + (C0/C189 * 0.2) + (C0/C250 * 0.2)
    結果快取至當日的 rs_weighted_cache_YYYY-MM-DD.json。
    回傳 dict: { ticker: rs_score }
    """
    import json, glob

    # 讀取當日快取（存在就直接用）
    if os.path.exists(RS_CACHE_FILE):
        try:
            with open(RS_CACHE_FILE, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            print(f"✅ 已讀取今日 RS Rating 快取 (共 {len(cached)} 檔)，跳過重新計算。")
            return cached
        except Exception:
            pass  # 快取損壞就重算

    print("\n📊 正在計算全市場 RS Rating (1 年期績效 Percentile Rank)...")
    print("   (計算完畢後會存入今日快取，今天內重複執行無需等待)")
    end = datetime.now()
    start = end - timedelta(days=380)

    import yfinance as yf
    batch = {}
    chunk_size = 200
    ticker_chunks = [tickers[i:i+chunk_size] for i in range(0, len(tickers), chunk_size)]

    for chunk in ticker_chunks:
        try:
            import io, contextlib
            _buf = io.StringIO()
            with contextlib.redirect_stderr(_buf):
                df = yf.download(chunk, start=start, end=end, progress=False, group_by='ticker')
            if isinstance(df.columns, pd.MultiIndex):
                for t in chunk:
                    try:
                        closes = df[t]['Close'].dropna()
                        if len(closes) > 50:
                            c0 = closes.iloc[-1]
                            c63 = closes.iloc[-64] if len(closes) > 63 else closes.iloc[0]
                            c126 = closes.iloc[-127] if len(closes) > 126 else closes.iloc[0]
                            c189 = closes.iloc[-190] if len(closes) > 189 else closes.iloc[0]
                            c250 = closes.iloc[-251] if len(closes) > 250 else closes.iloc[0]
                            
                            raw_rs = (c0 / c63 * 0.4) + (c0 / c126 * 0.2) + (c0 / c189 * 0.2) + (c0 / c250 * 0.2)
                            batch[t] = float(raw_rs)
                    except Exception:
                        pass
            else:
                closes = df['Close'].dropna()
                if len(closes) > 50 and len(chunk) == 1:
                    c0 = closes.iloc[-1]
                    c63 = closes.iloc[-64] if len(closes) > 63 else closes.iloc[0]
                    c126 = closes.iloc[-127] if len(closes) > 126 else closes.iloc[0]
                    c189 = closes.iloc[-190] if len(closes) > 189 else closes.iloc[0]
                    c250 = closes.iloc[-251] if len(closes) > 250 else closes.iloc[0]
                    
                    raw_rs = (c0 / c63 * 0.4) + (c0 / c126 * 0.2) + (c0 / c189 * 0.2) + (c0 / c250 * 0.2)
                    batch[chunk[0]] = float(raw_rs)
        except Exception:
            pass
        time.sleep(0.5)

    if not batch:
        print("RS Rating 計算失敗，將跳過此濾網。")
        return {}

    returns_series = pd.Series(batch)
    rs_scores = returns_series.rank(pct=True) * 100
    result = {t: round(float(rs_scores[t]), 1) for t in rs_scores.index}
    print(f"✅ RS Rating 計算完成，共 {len(result)} 檔。")

    # 儲存今日快取，並清除 7 天前的舊快取
    try:
        with open(RS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)
        for old in glob.glob("rs_cache_*.json"):
            if old != RS_CACHE_FILE:
                os.remove(old)
    except Exception:
        pass

    return result



# ============================================================
# 台股名冊快取 (7 天更新一次)
# ============================================================
def get_stock_list():
    import json
    
    cache_file = "tw_stock_cache.json"
    
    if os.path.exists(cache_file):
        mtime = os.path.getmtime(cache_file)
        if (datetime.now().timestamp() - mtime) < 7 * 86400:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print("✅ 發現近期的台股名冊快取，為您省下網路下載等待時間！")
                return data['final_tickers'], data['ticker_industry_map'], data['ticker_name_map']
            except Exception:
                pass

    print("開始從證交所下載台灣最新股票清單... (每 7 天自動更新一次)")
    try:
        twse_url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=2'
        tpex_url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=4'
        
        twse = pd.read_html(twse_url, encoding='cp950')[0]
        tpex = pd.read_html(tpex_url, encoding='cp950')[0]
        full_df = pd.concat([twse, tpex])
        
        ticker_list = []
        ticker_industry_map = {}
        ticker_name_map = {}
        for idx in range(len(full_df)):
            s_val = str(full_df.iloc[idx, 0])
            industry = str(full_df.iloc[idx, 4]) if full_df.shape[1] > 4 else "未知產業"
            if str(industry).lower() == 'nan':
                industry = "未知產業"
                
            # 接受所有股票與 ETF：4 位數字一般股票，以及所有 00 開頭的 ETF (含加構、反向、債券型)
            # Yahoo Finance 上不存在的特殊商品會在後續分析時安靜跳過，不影響掃描
            if re.match(r'^\d{4}\s', s_val) or re.match(r'^00[a-zA-Z0-9]{2,4}\s', s_val):
                parts = s_val.split('\u3000')
                ticker = parts[0].strip()
                name = parts[1].strip() if len(parts) > 1 else ""
                suffix = ".TW" if s_val in twse.iloc[:, 0].values else ".TWO"
                full_ticker = f"{ticker}{suffix}"
                ticker_list.append(full_ticker)
                ticker_industry_map[full_ticker] = industry
                ticker_name_map[full_ticker] = name
        
        final_tickers = sorted(list(set(ticker_list)))
        print(f"成功篩選出 {len(final_tickers)} 檔真實股票代號")
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "final_tickers": final_tickers,
                    "ticker_industry_map": ticker_industry_map,
                    "ticker_name_map": ticker_name_map
                }, f, ensure_ascii=False)
        except Exception:
            pass
            
        return final_tickers, ticker_industry_map, ticker_name_map
    except Exception as e:
        print(f"下載失敗: {e}")
        return [], {}, {}


# ============================================================
# 本地營收快取載入 (附「每月 10 日後自動清除舊資料」機制)
# ============================================================
def load_revenue_cache():
    cache = {}
    csv_file = "taiwan_revenue.csv"

    if os.path.exists(csv_file):
        # ── 自動過期判斷 ──────────────────────────────────────
        # 每月 10 日後（營收公布日），若快取是上個月的，自動刪除讓程式重新下載
        from datetime import datetime as _dt
        mtime = _dt.fromtimestamp(os.path.getmtime(csv_file))
        now   = _dt.now()
        is_new_revenue_day = now.day >= 10                     # 已過當月公布日
        is_old_cache       = (mtime.year, mtime.month) < (now.year, now.month)
        if is_new_revenue_day and is_old_cache:
            print(f"\n[🗑️] 偵測到舊月份營收快取 ({mtime.strftime('%Y-%m')})，已自動清除以取得最新資料...")
            os.remove(csv_file)
            return cache  # 回傳空 cache → 觸發上層自動下載
        # ──────────────────────────────────────────────────────

        try:
            df = pd.read_csv(csv_file)
            for _, r in df.iterrows():
                cache[str(r['ticker'])] = float(r['revenue_yoy'])
            print(f"\n✅ 成功載入本地營收快取 (共 {len(cache)} 筆，更新於 {mtime.strftime('%Y-%m-%d')})。")
        except Exception as e:
            print("\n❌ 讀取 taiwan_revenue.csv 失敗:", e)
    return cache



# ============================================================
# FinMind API 與本地快取雙軌並行 (先 API，再本地)
# ============================================================
local_revenue_cache = None
FINMIND_LIMIT_REACHED = False

def get_revenue_yoy(ticker_symbol):
    """最新單月營收 YoY 判斷"""
    global local_revenue_cache, FINMIND_LIMIT_REACHED
    if ticker_symbol in fundamental_cache["revenue"]:
        return fundamental_cache["revenue"][ticker_symbol]

    stock_id = ticker_symbol.split('.')[0]
    
    if FINMIND_LIMIT_REACHED:
        result = (None, None, "LIMIT_EXCEEDED")
    else:
        result = _fetch_revenue_api(stock_id)
        if result[2] == "LIMIT_EXCEEDED":
            FINMIND_LIMIT_REACHED = True
    
    if result[2] == "LIMIT_EXCEEDED":
        # 讀取本地快取作為備案
        if local_revenue_cache is None:
            local_revenue_cache = load_revenue_cache()
            
        if stock_id in local_revenue_cache:
            yoy = local_revenue_cache[stock_id]
            return yoy, False, f"近月 YoY:{yoy:.1f}% (本地資料)"
            
    if result[2] != "LIMIT_EXCEEDED" and result[2] != "API 異常":
        fundamental_cache["revenue"][ticker_symbol] = result
        
    return result

def _fetch_revenue_api(stock_id):
    start_date = (date.today() - timedelta(days=450)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockMonthRevenue", "data_id": stock_id, "start_date": start_date}
    try:
        resp = requests.get(url, params=params, timeout=10)
        res_json = resp.json()
        if 'limit' in str(res_json.get('msg', '')).lower():
            return None, None, "LIMIT_EXCEEDED"
        data = res_json.get('data', [])
        if len(data) < 14:
            return None, None, "數據不足"
        latest = data[-1]
        prev = data[-2]
        t_month, t_year = latest['revenue_month'], latest['revenue_year'] - 1
        p_month, p_year = prev['revenue_month'], prev['revenue_year'] - 1
        ly_latest = next((x for x in reversed(data[:-1]) if x['revenue_month'] == t_month and x['revenue_year'] == t_year), None)
        ly_prev   = next((x for x in reversed(data[:-2]) if x['revenue_month'] == p_month and x['revenue_year'] == p_year), None)
        if ly_latest and ly_latest['revenue'] > 0:
            yoy_now = ((latest['revenue'] - ly_latest['revenue']) / ly_latest['revenue']) * 100
        else:
            return None, None, "去年同期數據缺失"
        yoy_prev = None
        if ly_prev and ly_prev['revenue'] > 0:
            yoy_prev = ((prev['revenue'] - ly_prev['revenue']) / ly_prev['revenue']) * 100
        is_accelerating = (yoy_prev is not None and yoy_now > yoy_prev)
        return yoy_now, is_accelerating, f"{latest['revenue_year']}/{latest['revenue_month']} YoY:{yoy_now:.1f}%"
    except Exception:
        return None, None, "API 異常"


def get_eps_and_margins(ticker_symbol):
    """從 FinMind 取得最近一季 EPS YoY 與三率成長"""
    global FINMIND_LIMIT_REACHED
    if ticker_symbol in fundamental_cache["eps"]:
        return fundamental_cache["eps"][ticker_symbol]

    stock_id = ticker_symbol.split('.')[0]
    
    if FINMIND_LIMIT_REACHED:
        return None, None, "LIMIT_EXCEEDED"
        
    result = _fetch_eps_api(stock_id)
    if result[2] == "LIMIT_EXCEEDED":
        FINMIND_LIMIT_REACHED = True
        
    if result[2] != "LIMIT_EXCEEDED":
        fundamental_cache["eps"][ticker_symbol] = result
    return result

def _fetch_eps_api(stock_id):
    start_date = (date.today() - timedelta(days=600)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockFinancialStatements", "data_id": stock_id, "start_date": start_date}
    try:
        resp = requests.get(url, params=params, timeout=10)
        res_json = resp.json()
        if 'limit' in str(res_json.get('msg', '')).lower():
            return None, None, "LIMIT_EXCEEDED"
        data = res_json.get('data', [])
        if not data:
            return None, None, "財報數據不足"
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        eps_data = df[df['type'] == 'EPS'].tail(8)
        gp_data  = df[df['type'] == 'GrossProfit']     
        op_data  = df[df['type'] == 'OperatingIncome']
        ni_data  = df[df['type'] == 'NetIncome']
        if len(eps_data) < 2:
            return None, None, "EPS 數據不足"
        latest_eps = float(eps_data.iloc[-1]['value'])
        prev_eps   = float(eps_data.iloc[-2]['value'])
        eps_yoy = ((latest_eps - prev_eps) / abs(prev_eps) * 100) if prev_eps != 0 else None
        
        def is_improving(sdf):
            if len(sdf) < 2: return True 
            return float(sdf.iloc[-1]['value']) > float(sdf.iloc[-2]['value'])
            
        margins_improving = is_improving(gp_data) and is_improving(op_data) and is_improving(ni_data)
        
        # 格式化季度顯示
        d = eps_data.iloc[-1]['date']
        quarter = (d.month - 1) // 3 + 1
        msg = f"{d.year}Q{quarter} EPS:{latest_eps:.2f} YoY:{eps_yoy:.1f}% | 三率{'✅成長' if margins_improving else '❌退步'}"
        return eps_yoy, margins_improving, msg
    except Exception:
        return None, None, "API 異常"


def get_institutional_net(ticker_symbol, days=20):
    """
    從 FinMind 取得近 N 日外資 + 投信累計買賣超。
    回傳 (net_buy, msg)，net_buy > 0 表示法人為淨增加。
    """
    global FINMIND_LIMIT_REACHED
    if FINMIND_LIMIT_REACHED:
        return None, "LIMIT_EXCEEDED"
        
    stock_id = ticker_symbol.split('.')[0]
    start_date = (date.today() - timedelta(days=days + 10)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockInstitutionalInvestorsBuySell", "data_id": stock_id, "start_date": start_date}
    try:
        resp = requests.get(url, params=params, timeout=10)
        res_json = resp.json()
        if 'limit' in str(res_json.get('msg', '')).lower():
            FINMIND_LIMIT_REACHED = True
            return None, "LIMIT_EXCEEDED"
        data = res_json.get('data', [])
        if not data:
            return None, "無法人數據"
        df = pd.DataFrame(data)
        # 只看外資 + 投信
        df = df[df['name'].isin(['外陸資買賣超股數(不含外資自營商)', '外資買賣超股數', '投信買賣超股數'])]
        net = df['buy'].astype(float).sum() - df['sell'].astype(float).sum()
        return net, f"近{days}日法人淨{'買' if net > 0 else '賣'}超: {net:,.0f}股"
    except Exception:
        return None, "API 異常"


# ============================================================
# 主批次掃描函數
# ============================================================
def batch_scan_vcp(
    tickers_to_scan,
    enable_revenue_filter=True,
    interactive=True,
    ask_callback=None,
    ticker_industry_map=None,
    ticker_name_map=None,
    rs_ratings=None,
):
    print("開始批次掃描 VCP 型態...")
    
    revenue_cache = {}
    if enable_revenue_filter:
        revenue_cache = load_revenue_cache()
        if not revenue_cache:
            print("\n[📥] 未偵測到本地營收快取，自動從政府公開資料下載 (約 1~2 秒)...")
            try:
                import importlib, sys
                # 動態載入同資料夾下的 update_revenue.py
                spec = importlib.util.spec_from_file_location(
                    "營收資料同步",
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "營收資料同步.py")
                )
                ur = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(ur)
                ur.build_fast_revenue_csv()
                revenue_cache = load_revenue_cache()
                if revenue_cache:
                    print("[✅] 營收快取下載完成，繼續掃描...\n")
                else:
                    print("[⚠️] 下載後仍無資料，將跳過基本面-營收篩選。\n")
            except Exception as e:
                print(f"[⚠️] 自動下載失敗 ({e})，將跳過基本面-營收篩選。\n")
    
    ultimate_picks = []
    total_scanned = len(tickers_to_scan)
    
    ma_passed_tickers        = []
    liquidity_passed_tickers = []
    rs_passed_tickers        = []
    ud_passed_tickers        = []
    vcp_passed_tickers       = []

    for i, ticker in enumerate(tickers_to_scan):
        if (i+1) % 30 == 0:
            time.sleep(2)
            print(f"\n--- 進度報告: 已完成 {i+1}/{total_scanned} ---")
            
        print(f"\n--- 篩選股票: {ticker} ({i+1}/{total_scanned}) ---")
        
        try:
            result = analyze_vcp(ticker, silent=True)
        except Exception as e:
            print(f"股票 {ticker} 分析過程中發生未預期錯誤 ({e})，安全跳過。")
            continue
        
        if result is None:
            print(f"股票 {ticker} 數據抓取失敗或數據不足，快速跳過。")
            continue

        # --- 第一層：趨勢模板 ---
        close    = result["current_price"]
        ma50     = result.get("ma50")
        ma200    = result.get("ma200")
        year_high = result["highest_250_day_price"]
        year_low  = result.get("lowest_250_day_price")
        is_uptrend = result.get("is_uptrend", False)

        if None in [ma50, ma200, year_low]:
            print(f"股票 {ticker} 缺乏均線數據，快速跳過。")
            continue

        within_high_range = close >= (year_high * 0.75)
        above_low_range   = close >= (year_low  * 1.30)

        if not (is_uptrend and within_high_range and above_low_range):
            print(f"股票 {ticker} 未通過趨勢濾網，快速跳過。")
            continue
        ma_passed_tickers.append(ticker)

        # --- 第二層：流動性動態過濾 ---
        t5  = result.get("turnover_5_ma", 0)
        t50 = result.get("turnover_50_ma", 0)
        
        # 優化邏輯：只要求長期(50日)具備基本流動性(>3000萬)。
        # 移除 5日均成交>5000萬 的限制，以保留 VCP 突破前的「量縮窒息 (VDU)」特徵。
        is_liquid = (t50 > 30_000_000)
        
        if not is_liquid:
            print(f"股票 {ticker} 未通過流動性濾網 (50日均成交<3000萬)，快速跳過。")
            continue
        liquidity_passed_tickers.append(ticker)

        # --- 第三層：RS Rating > 90 ---
        rs_score = rs_ratings.get(ticker, 0) if rs_ratings else 0
        if rs_ratings and rs_score < 90:
            print(f"股票 {ticker} 未通過 RS 濾網 (RS Rating: {rs_score:.0f} < 90)，快速跳過。")
            continue
        rs_passed_tickers.append(ticker)

        # --- 第四層：U/D Volume Ratio > 1.0 ---
        ud = result.get("ud_ratio", 0)
        if ud < 1.0:
            print(f"股票 {ticker} 未通過 U/D 量比濾網 (U/D Ratio: {ud:.2f} < 1.0)，快速跳過。")
            continue
        ud_passed_tickers.append(ticker)

        # --- 第五層：VCP 核心波動收縮 < 4% ---
        vcp_pct = result["current_volatility_percentage"]
        t_count = result["t_count"]
        if not (t_count > 0 and vcp_pct < 7.0):
            print(f"股票 {ticker} 未通過 VCP 濾網 (波動 {vcp_pct:.2f}% >= 7% 或無收縮)，快速跳過。")
            continue

        # --- 第六層：VDU 窒息量 (已在 vcp_analyzer 中計算，門檻 40%) ---
        if not result.get("is_vdu", False):
            vdr = result.get("vdu_vol_ratio")
            vdr_str = f"{vdr:.2f}" if vdr is not None else "無資料"
            print(f"股票 {ticker} 未通過 VDU 濾網 (量比 {vdr_str} >= 0.40)，快速跳過。")
            continue

        # --- 第七層：回檔遞減 ---
        pullbacks = result.get("recent_pullbacks", [])
        is_decreasing = result.get("pullbacks_decreasing", False)
        if not is_decreasing:
            formatted_pb = " -> ".join([f"{p:.1f}%" for p in pullbacks]) if pullbacks else "無"
            print(f"股票 {ticker} 未通過回檔遞減濾網 ({formatted_pb})，快速跳過。")
            continue

        vcp_passed_tickers.append(ticker)

        # ============================================================
        # 延遲 Lazy Load：只對技術面全通過的股票呼叫 FinMind
        # ============================================================
        yoy_val       = 0.0
        eps_yoy_val   = None
        is_accel      = None
        margins_ok    = None
        inst_net      = None

        if enable_revenue_filter:
            is_etf = ticker.startswith("00")
            if not is_etf:
                # 營收
                if ticker in revenue_cache:
                    yoy_val = revenue_cache[ticker]
                    is_accel = None  # 快取無法判斷加速性，標示為未知
                    if math.isnan(yoy_val) or yoy_val < 20.0:
                        y_fmt = f"{yoy_val:.1f}%" if not math.isnan(yoy_val) else "無資料"
                        print(f"股票 {ticker} 未通過基本面-營收濾網 ({y_fmt} < 20%)，跳過。")
                        continue
                else:
                    rv_yoy, rv_accel, rv_msg = get_revenue_yoy(ticker)
                    
                    if rv_msg == "LIMIT_EXCEEDED":
                        if not getattr(batch_scan_vcp, "warned_limit", False):
                            print("\n[⚠️ API 上限] FinMind API 達 300次/小時上限！停止睡眠等待，受限的股票將強行通過基本面濾網 (計 0 分) 以保留技術面型態。")
                            batch_scan_vcp.warned_limit = True
                    
                    if rv_yoy is not None and rv_yoy < 20.0 and rv_msg != "LIMIT_EXCEEDED":
                        print(f"股票 {ticker} 未通過基本面-營收濾網 ({rv_msg})，跳過。")
                        continue
                        
                    yoy_val  = rv_yoy if rv_msg != "LIMIT_EXCEEDED" and rv_yoy is not None else 0.0
                    is_accel = rv_accel
                    
                    if rv_msg == "LIMIT_EXCEEDED":
                        print(f"股票 {ticker} 營收無資料 (受限 API 上限，強制放行)")
                    else:
                        print(f"股票 {ticker} 通過營收濾網 ({rv_msg}{'，具加速性🚀' if rv_accel else ''})")

                # EPS + 三率
                eps_yoy_val, margins_ok, eps_msg = get_eps_and_margins(ticker)
                
                if eps_yoy_val is not None and eps_yoy_val < 20.0 and eps_msg != "LIMIT_EXCEEDED":
                    print(f"股票 {ticker} 未通過基本面-EPS 濾網 ({eps_msg})，跳過。")
                    continue
                if margins_ok is False and eps_msg != "LIMIT_EXCEEDED":
                    print(f"股票 {ticker} 未通過三率成長濾網 ({eps_msg})，跳過。")
                    continue
                    
                if eps_msg == "LIMIT_EXCEEDED":
                    print(f"股票 {ticker} EPS 無資料 (受限 API 上限，強制放行)")
                elif eps_yoy_val is not None:
                    print(f"股票 {ticker} 通過 EPS 濾網 ({eps_msg})")

                # 法人籌碼
                inst_net, inst_msg = get_institutional_net(ticker, days=20)
                
                if inst_net is not None and inst_net <= 0 and inst_msg != "LIMIT_EXCEEDED":
                    print(f"股票 {ticker} 未通過法人籌碼濾網 ({inst_msg})，跳過。")
                    continue
                    
                if inst_msg == "LIMIT_EXCEEDED":
                    print(f"股票 {ticker} 法人籌碼無資料 (受限 API 上限，強制放行)")
                elif inst_net is not None:
                    print(f"股票 {ticker} 通過法人濾網 ({inst_msg})")

        # === 計算得分 (40% RS + 30% EPS YoY + 30% VCP 緊縮度) ===
        rs_norm  = min(rs_score / 100, 1.0) * 40
        eps_norm = min((eps_yoy_val or 0) / 100, 1.0) * 30
        vcp_norm = max(0, (7.0 - vcp_pct) / 7.0) * 30  # 越小越好
        total_score = round(rs_norm + eps_norm + vcp_norm, 1)

        # VCP 分級
        if vcp_pct < 2.5:
            vcp_label = "🔥 VCP 臨界點"
        elif vcp_pct < 7.0:
            vcp_label = "✨ 高度關注"
        else:
            vcp_label = "⭐ 潛力標的"

        ultimate_picks.append({
            "ticker":          result["ticker"],
            "current_price":   close,
            "vcp_pct":         vcp_pct,
            "rs_score":        rs_score,
            "revenue_yoy":     yoy_val,
            "eps_yoy":         eps_yoy_val,
            "is_accel":        is_accel,
            "margins_ok":      margins_ok,
            "inst_net":        inst_net,
            "ud_ratio":        ud,
            "status":          vcp_label,
            "total_score":     total_score,
            # 突破訊號
            "cheat_pivot":     result.get("cheat_pivot"),
            "base_high":       result.get("base_high"),
            "is_traditional_breakout": result.get("is_traditional_breakout", False),
            "is_cheat_breakout":       result.get("is_cheat_breakout", False),
            "is_false_breakout":       result.get("is_false_breakout", False),
            "today_vol":               result.get("today_vol", 0),
            "today_amount":            result.get("today_amount", 0),
            "avg_amount_20":           result.get("avg_amount_20", 0),
            "vol_20_ma":               result.get("vol_20_ma", 0),
            "breakout_vol_ratio":      result.get("breakout_vol_ratio", 0),
        })
        print(f"🏆 股票 {ticker} 通過全部濾網！得分: {total_score:.1f} / 100，標註為 '{vcp_label}'")

    print("\n所有批次掃描已完成。")

    # ==================== 輸出最終戰報 ====================
    if ultimate_picks:
        industry_groups = defaultdict(list)
        for pick in ultimate_picks:
            ind = ticker_industry_map.get(pick['ticker'], "未知產業") if ticker_industry_map else "未知產業"
            industry_groups[ind].append(pick)
            
        # 🚀 族群性過濾器 (Sector Clustering)
        for industry, picks in industry_groups.items():
            if len(picks) >= 3:
                for pick in picks:
                    pick['total_score'] = round(pick['total_score'] * 1.2, 1)
                    pick['status'] = f"{pick['status']} [族群🔥]"

        print("\n" + "="*80)
        print("🏆 今日全市場最優選 (依產業分類，得分由高到低):")
        print("="*80)
        
        tv_watchlist = []
        # 將產業依照最高得分的股票進行排序
        sorted_industries = sorted(industry_groups.items(), key=lambda item: max(p["total_score"] for p in item[1]), reverse=True)

        for industry, picks in sorted_industries:
            picks.sort(key=lambda x: x["total_score"], reverse=True)
            cluster_tag = " 🔥聚落形成 (綜合評分+20%)" if len(picks) >= 3 else ""
            print(f"\n📂 【{industry}】 (共 {len(picks)} 檔){cluster_tag}")
            print("-" * 60)
            for pick in picks:
                t = pick['ticker']
                name = ticker_name_map.get(t, "") if ticker_name_map else ""
                yoy_str = f"{pick['revenue_yoy']:.1f}%" if not math.isnan(pick['revenue_yoy'] or 0) else "N/A"
                eps_str = f"{pick['eps_yoy']:.1f}%" if pick.get('eps_yoy') is not None else "N/A"
                accel_str = "🚀" if pick.get('is_accel') else ""
                # 突破狀態標註
                if pick.get('is_traditional_breakout'):
                    pivot_str = f"🚀 強勢突破大底! 成交量{format_vcp_amount(pick['today_amount'])} / {pick['today_vol']:,.0f}張 ({pick['breakout_vol_ratio']*100:.0f}%) BaseHigh:{pick['base_high']:.2f}"
                elif pick.get('is_cheat_breakout'):
                    pivot_str = f"🎯 中繼作弊點 (Cheat) 觸發! 成交量{format_vcp_amount(pick['today_amount'])} / {pick['today_vol']:,.0f}張 ({pick['breakout_vol_ratio']*100:.0f}%) CheatPivot:{pick['cheat_pivot']:.2f}"
                elif pick.get('is_false_breakout'):
                    pivot_str = f"⚠️  假突破 CP:{pick['cheat_pivot']:.2f}"
                else:
                    cv = pick.get('cheat_pivot') or 0
                    bh = pick.get('base_high') or 0
                    pivot_str = f"⏳ 尚未突破 CP:{cv:.2f} BH:{bh:.2f} (量:{format_vcp_amount(pick['today_amount'])} / {pick['today_vol']:,.0f}張)"
                print(
                    f"🔹 {t:<10} {name:<6} | 股價:{pick['current_price']:<7.2f} | "
                    f"VCP:{pick['vcp_pct']:.2f}% | RS:{pick['rs_score']:.0f} | "
                    f"營收:{yoy_str}{accel_str} | EPS:{eps_str} | "
                    f"U/D:{pick['ud_ratio']:.2f} | 得分:{pick['total_score']:.1f} | {pick['status']}"
                )
                print(f"         └─ {pivot_str}")
                if t.endswith('.TW'):
                    tv_watchlist.append(f"TWSE:{t.replace('.TW','')}")
                elif t.endswith('.TWO'):
                    tv_watchlist.append(f"TPEX:{t.replace('.TWO','')}")

        print("\n" + "="*80)
        
        tv_filename = "TradingView_VCP_Watchlist.txt"
        with open(tv_filename, "w") as f:
            f.write(",".join(tv_watchlist))
        print(f"\n✅ TradingView 匯入清單已輸出至：{tv_filename}")
        
    else:
        print("\n今日沒有偵測到全市場最優選股票。")
    
    print("\n" + "="*60)
    print("今日全市場掃描統計:")
    print("="*60)
    print(f"今日總計掃描:           {total_scanned:>5} 檔")
    print(f"通過趨勢模板:           {len(ma_passed_tickers):>5} 檔")
    print(f"通過流動性濾網:         {len(liquidity_passed_tickers):>5} 檔")
    print(f"通過 RS Rating > 90:    {len(rs_passed_tickers):>5} 檔")
    print(f"通過 U/D 量比 > 1.0:    {len(ud_passed_tickers):>5} 檔")
    print(f"通過 VCP < 4%:          {len(vcp_passed_tickers):>5} 檔")
    print(f"通過全部濾網 (最優選):  {len(ultimate_picks):>5} 檔")
    print("="*60)
    
    # === 互動式查詢 ===
    def ask_to_show_list(prompt_text, tickers_list):
        if not tickers_list: return
        if interactive:
            if ask_callback:
                ans = 'Y' if ask_callback(prompt_text, len(tickers_list)) else 'N'
            else:
                try:
                    ans = input(f"是否想查看 {prompt_text}: {len(tickers_list)} 檔清單？(Y/N): ").upper()
                except EOFError:
                    ans = 'N'
        else:
            ans = 'N'

        if ans == 'Y':
            print(f"\n[ {prompt_text} - 清單共 {len(tickers_list)} 檔 ]")
            print("=" * 60)
            ind_groups = defaultdict(list)
            for t in tickers_list:
                ind = ticker_industry_map.get(t, "未知產業") if ticker_industry_map else "未知產業"
                ind_groups[ind].append(t)
            for ind, t_list in ind_groups.items():
                print(f"\n📁 【{ind}】 ({len(t_list)} 檔)")
                print("-" * 40)
                cols, rows = 4, (len(t_list) + 3) // 4
                for r in range(rows):
                    line = ""
                    for c in range(cols):
                        idx = c * rows + r
                        if idx < len(t_list):
                            line += f"{t_list[idx]:<11}"
                    print(line)
            print("\n" + "=" * 60 + "\n")

    print("\n")
    ask_to_show_list("通過趨勢模板", ma_passed_tickers)
    ask_to_show_list("通過流動性濾網", liquidity_passed_tickers)
    ask_to_show_list("通過 RS Rating > 90", rs_passed_tickers)
    ask_to_show_list("通過 U/D 量比 > 1.0", ud_passed_tickers)
    ask_to_show_list("通過 VCP 緊縮濾網", vcp_passed_tickers)


# ============================================================
# 主程式入口
# ============================================================
if __name__ == "__main__":
    try:
        user_choice = input("是否掃描全台股市場？(Y/N): ").upper()
    except EOFError:
        user_choice = 'Y'

    if user_choice == 'Y':
        # 第一步：大盤環境檢查
        market_ok, market_msg = get_market_status()
        print(f"\n📈 大盤環境：{market_msg}")
        if not market_ok:
            try:
                proceed = input("⚠️  大盤偏弱，是否仍要繼續掃描？(Y/N): ").upper()
            except EOFError:
                proceed = 'Y'
            if proceed != 'Y':
                print("使用者中止掃描。")
                exit()

        # 第二步：載入股票名冊
        tickers, ticker_industry_map, ticker_name_map = get_stock_list()
        print(f"成功下載 {len(tickers)} 檔股票。")

        # 第三步：計算全市場 RS Rating
        rs_ratings = calculate_rs_ratings(tickers)

        # 第四步：批次掃描
        batch_scan_vcp(
            tickers,
            enable_revenue_filter=True,
            ticker_industry_map=ticker_industry_map,
            ticker_name_map=ticker_name_map,
            rs_ratings=rs_ratings,
        )

    elif user_choice == 'N':
        print("\n正在載入台股名冊供查詢對照...")
        tickers, ticker_industry_map, ticker_name_map = get_stock_list()
        print("\n進入手動輸入模式。")
        # 建立名稱 → ticker 反查字典（小寫，支援模糊比對）
        name_to_tickers = {}
        for t, n in ticker_name_map.items():
            key = n.strip().lower()
            name_to_tickers.setdefault(key, []).append(t)

        while True:
            raw = input("請輸入股票代碼或公司名稱（輸入 q 結束）：").strip()
            if raw.upper() == 'Q':
                break

            search_ticker = None

            # 1) 純數字 → 自動加後綴
            if raw.isdigit():
                if f"{raw}.TW" in ticker_industry_map:
                    search_ticker = f"{raw}.TW"
                elif f"{raw}.TWO" in ticker_industry_map:
                    search_ticker = f"{raw}.TWO"
                else:
                    search_ticker = raw  # 讓 analyze_vcp 自行嘗試

            # 2) 已含後綴代碼 (如 2330.TW)
            elif raw.upper() in ticker_industry_map:
                search_ticker = raw.upper()

            # 3) 公司名稱搜尋（模糊比對）
            else:
                query = raw.lower()
                seen = set()
                matches = []
                # 比對公司名稱
                for name_key, tklist in name_to_tickers.items():
                    if query in name_key:
                        for t in tklist:
                            if t not in seen:
                                seen.add(t)
                                matches.append(t)
                # 比對產業別（例如搜尋「半導體」→ 找出所有半導體業）
                for t, ind_val in ticker_industry_map.items():
                    if query in ind_val.lower() and t not in seen:
                        seen.add(t)
                        matches.append(t)

                if not matches:
                    print(f"❌ 找不到『{raw}』，請確認代碼或公司名稱後重試。\n")
                    continue
                elif len(matches) == 1:
                    search_ticker = matches[0]
                else:
                    print(f"🔍 找到 {len(matches)} 個符合『{raw}』的公司：")
                    for i, t in enumerate(matches, 1):
                        n   = ticker_name_map.get(t, '')
                        ind = ticker_industry_map.get(t, '')
                        print(f"  {i:>2}. {t:<14} {n} ({ind})")
                    sel = input("請輸入編號選擇（直接 Enter 取消）：").strip()
                    if not sel.isdigit() or not (1 <= int(sel) <= len(matches)):
                        print("已取消。\n")
                        continue
                    search_ticker = matches[int(sel) - 1]

            if search_ticker in ticker_industry_map:
                name = ticker_name_map.get(search_ticker, '未知名稱')
                ind  = ticker_industry_map.get(search_ticker, '未知產業')
                print(f"\n🏷️ 查詢標的：{search_ticker} {name} ({ind})")

            # 抓取基本面資訊 (優先使用 Session 暫存)
            is_cached = (search_ticker in fundamental_cache["revenue"]) or (search_ticker in fundamental_cache["eps"])
            if not is_cached:
                print(f"📡 正在從 FinMind 抓取 {search_ticker} 的基本面數據...")

            rv_info = get_revenue_yoy(search_ticker)
            ep_info = get_eps_and_margins(search_ticker)

            # --- 計算個股 RS Score 與大盤比較 ---
            try:
                import yfinance as yf
                _end = datetime.now()
                _start = _end - timedelta(days=380)
                import io, contextlib
                _buf = io.StringIO()
                with contextlib.redirect_stderr(_buf):
                    # 同時下載個股與大盤(加權指數)資料
                    _df = yf.download([search_ticker, "^TWII"], start=_start, end=_end, progress=False)
                
                if isinstance(_df.columns, pd.MultiIndex):
                    # 處理 yfinance 下載多檔標的的 MultiIndex 結構
                    _closes_stock = _df['Close'][search_ticker].dropna() if search_ticker in _df['Close'] else pd.Series()
                    _closes_market = _df['Close']['^TWII'].dropna() if '^TWII' in _df['Close'] else pd.Series()
                else:
                    _closes_stock = _df['Close'].dropna() if not _df.empty else pd.Series()
                    _closes_market = pd.Series() # 備用防錯

                if len(_closes_stock) > 60 and len(_closes_market) > 60:
                    # 個股價格
                    c0   = float(_closes_stock.iloc[-1])
                    c63  = float(_closes_stock.iloc[-64])  if len(_closes_stock) > 63  else float(_closes_stock.iloc[0])
                    c126 = float(_closes_stock.iloc[-127]) if len(_closes_stock) > 126 else float(_closes_stock.iloc[0])
                    c189 = float(_closes_stock.iloc[-190]) if len(_closes_stock) > 189 else float(_closes_stock.iloc[0])
                    c250 = float(_closes_stock.iloc[-251]) if len(_closes_stock) > 250 else float(_closes_stock.iloc[0])
                    
                    # 大盤價格
                    m0   = float(_closes_market.iloc[-1])
                    m63  = float(_closes_market.iloc[-64])  if len(_closes_market) > 63  else float(_closes_market.iloc[0])
                    m126 = float(_closes_market.iloc[-127]) if len(_closes_market) > 126 else float(_closes_market.iloc[0])
                    m250 = float(_closes_market.iloc[-251]) if len(_closes_market) > 250 else float(_closes_market.iloc[0])

                    # 個股區間漲幅
                    p3m  = (c0 / c63  - 1) * 100
                    p6m  = (c0 / c126 - 1) * 100
                    p12m = (c0 / c250 - 1) * 100
                    
                    # 大盤區間漲幅
                    mp3m  = (m0 / m63  - 1) * 100
                    mp6m  = (m0 / m126 - 1) * 100
                    mp12m = (m0 / m250 - 1) * 100

                    # 計算優於大盤的超額報酬 (Alpha，百分點)
                    alpha_3m = p3m - mp3m
                    alpha_6m = p6m - mp6m
                    alpha_12m = p12m - mp12m

                    # 原本的絕對加權分數
                    raw_rs = (c0/c63*0.4) + (c0/c126*0.2) + (c0/c189*0.2) + (c0/c250*0.2)
                    rs_label = "🚀 強勢" if raw_rs >= 1.15 else ("✅ 偏強" if raw_rs >= 1.02 else ("⚠️ 偏弱" if raw_rs >= 0.95 else "❌ 弱勢"))
                    
                    print(f"\n📊 相對強度 (RS) 分析 (對標大盤加權指數 ^TWII):")
                    print(f"  {rs_label} 絕對加權分數: {raw_rs:.4f}  (>1.10 為強勢)")
                    print(f"  3月漲幅: {p3m:>+6.1f}% (大盤 {mp3m:>+6.1f}%) | 勝出大盤: {alpha_3m:>+6.1f}%")
                    print(f"  6月漲幅: {p6m:>+6.1f}% (大盤 {mp6m:>+6.1f}%) | 勝出大盤: {alpha_6m:>+6.1f}%")
                    print(f"  12月漲幅:{p12m:>+6.1f}% (大盤 {mp12m:>+6.1f}%) | 勝出大盤: {alpha_12m:>+6.1f}%")
                else:
                    print("\n📊 相對強度 (RS) 分析: 數據不足，無法計算")
            except Exception as e:
                print(f"\n📊 相對強度 (RS) 分析: 計算失敗 ({e})")

            analyze_vcp(search_ticker, silent=False, revenue_info=rv_info, eps_info=ep_info)
            print("  👴🏿 祝尼發大財！👴🏿\n")

    else:
        print("無效的選擇，程式終止。")