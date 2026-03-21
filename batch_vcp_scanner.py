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
from vcp_analyzer import analyze_vcp


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
# RS Rating 計算 (全市場相對強度 Percentile Rank)
# ============================================================
RS_CACHE_FILE = f"rs_cache_{datetime.now().strftime('%Y-%m-%d')}.json"

def calculate_rs_ratings(tickers):
    """
    批次下載全市場 1 年期收益率，並對每一檔計算 Percentile Rank (0~100)。
    結果快取至當日的 rs_cache_YYYY-MM-DD.json，同一天重複執行直接讀取，不重算。
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
                            ret = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
                            batch[t] = float(ret)
                    except Exception:
                        pass
            else:
                closes = df['Close'].dropna()
                if len(closes) > 50 and len(chunk) == 1:
                    ret = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
                    batch[chunk[0]] = float(ret)
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
# 本地營收快取載入
# ============================================================
def load_revenue_cache():
    cache = {}
    if os.path.exists("taiwan_revenue.csv"):
        try:
            df = pd.read_csv("taiwan_revenue.csv")
            for _, r in df.iterrows():
                cache[str(r['ticker'])] = float(r['revenue_yoy'])
            print(f"\n✅ 成功載入本地營收快取 (共 {len(cache)} 筆)。")
        except Exception as e:
            print("\n❌ 讀取 taiwan_revenue.csv 失敗:", e)
    return cache


# ============================================================
# FinMind Lazy Fetcher (僅對技術面過關的股票呼叫)
# ============================================================
def get_revenue_yoy(ticker_symbol):
    """最新單月營收 YoY，並判斷是否具備加速性 (本月 YoY > 上月 YoY)"""
    stock_id = ticker_symbol.split('.')[0]
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
    """
    從 FinMind 取得最近一季 EPS YoY 與三率 (毛利、營利、淨利) 是否較去年同期成長。
    回傳 (eps_yoy, margins_improving, msg)
    """
    stock_id = ticker_symbol.split('.')[0]
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
        # 建立季度財報索引
        eps_data = df[df['type'] == 'EPS'].tail(8)
        gp_data  = df[df['type'] == 'GrossProfit'].tail(8)     # 毛利率 proxy
        op_data  = df[df['type'] == 'OperatingIncome'].tail(8)  # 營業利益
        ni_data  = df[df['type'] == 'NetIncome'].tail(8)        # 淨利
        if len(eps_data) < 2:
            return None, None, "EPS 數據不足"
        latest_eps = float(eps_data.iloc[-1]['value'])
        prev_eps   = float(eps_data.iloc[-2]['value'])
        eps_yoy = ((latest_eps - prev_eps) / abs(prev_eps) * 100) if prev_eps != 0 else None
        # 三率：只要最新 > 前一期即視為成長
        def is_improving(sdf):
            if len(sdf) < 2: return True  # 缺數據則放行
            return float(sdf.iloc[-1]['value']) > float(sdf.iloc[-2]['value'])
        margins_improving = is_improving(gp_data) and is_improving(op_data) and is_improving(ni_data)
        msg = f"EPS YoY:{eps_yoy:.1f}% | 三率{'✅成長' if margins_improving else '❌退步'}" if eps_yoy is not None else "EPS 計算異常"
        return eps_yoy, margins_improving, msg
    except Exception:
        return None, None, "API 異常"


def get_institutional_net(ticker_symbol, days=20):
    """
    從 FinMind 取得近 N 日外資 + 投信累計買賣超。
    回傳 (net_buy, msg)，net_buy > 0 表示法人為淨增加。
    """
    stock_id = ticker_symbol.split('.')[0]
    start_date = (date.today() - timedelta(days=days + 10)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockInstitutionalInvestorsBuySell", "data_id": stock_id, "start_date": start_date}
    try:
        resp = requests.get(url, params=params, timeout=10)
        res_json = resp.json()
        if 'limit' in str(res_json.get('msg', '')).lower():
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
            print("[警告] 尚未發現 taiwan_revenue.csv，建議先執行 python3 update_revenue.py")
    
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
        is_liquid = (t50 > 30_000_000) and (t5 > 50_000_000)
        if not is_liquid:
            print(f"股票 {ticker} 未通過流動性濾網 (50日均成交<3000萬 或 5日均成交<5000萬)，快速跳過。")
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
                        print(f"[!] FinMind API 上限！暫停 61 分鐘...")
                        time.sleep(3660)
                        rv_yoy, rv_accel, rv_msg = get_revenue_yoy(ticker)
                    if rv_yoy is None or rv_yoy < 20.0:
                        print(f"股票 {ticker} 未通過基本面-營收濾網 ({rv_msg})，跳過。")
                        continue
                    yoy_val  = rv_yoy
                    is_accel = rv_accel
                    print(f"股票 {ticker} 通過營收濾網 ({rv_msg}{'，具加速性🚀' if rv_accel else ''})")

                # EPS + 三率
                eps_yoy_val, margins_ok, eps_msg = get_eps_and_margins(ticker)
                if eps_msg == "LIMIT_EXCEEDED":
                    print(f"[!] FinMind API 上限！暫停 61 分鐘...")
                    time.sleep(3660)
                    eps_yoy_val, margins_ok, eps_msg = get_eps_and_margins(ticker)
                if eps_yoy_val is not None and eps_yoy_val < 20.0:
                    print(f"股票 {ticker} 未通過基本面-EPS 濾網 ({eps_msg})，跳過。")
                    continue
                if margins_ok is False:
                    print(f"股票 {ticker} 未通過三率成長濾網 ({eps_msg})，跳過。")
                    continue
                if eps_yoy_val is not None:
                    print(f"股票 {ticker} 通過 EPS 濾網 ({eps_msg})")

                # 法人籌碼
                inst_net, inst_msg = get_institutional_net(ticker, days=20)
                if inst_msg == "LIMIT_EXCEEDED":
                    print(f"[!] FinMind API 上限！暫停 61 分鐘...")
                    time.sleep(3660)
                    inst_net, inst_msg = get_institutional_net(ticker, days=20)
                if inst_net is not None and inst_net <= 0:
                    print(f"股票 {ticker} 未通過法人籌碼濾網 ({inst_msg})，跳過。")
                    continue
                if inst_net is not None:
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
            "pivot_point":     result.get("pivot_point"),
            "is_breakout":     result.get("is_breakout", False),
            "is_false_breakout": result.get("is_false_breakout", False),
            "breakout_vol_ratio": result.get("breakout_vol_ratio", 0),
        })
        print(f"🏆 股票 {ticker} 通過全部濾網！得分: {total_score:.1f} / 100，標註為 '{vcp_label}'")

    print("\n所有批次掃描已完成。")

    # ==================== 輸出最終戰報 ====================
    if ultimate_picks:
        ultimate_picks.sort(key=lambda x: x["total_score"], reverse=True)
        industry_groups = defaultdict(list)
        for pick in ultimate_picks:
            ind = ticker_industry_map.get(pick['ticker'], "未知產業") if ticker_industry_map else "未知產業"
            industry_groups[ind].append(pick)
            
        print("\n" + "="*80)
        print("🏆 今日全市場最優選 (依產業分類，得分由高到低):")
        print("="*80)
        
        tv_watchlist = []
        for industry, picks in industry_groups.items():
            picks.sort(key=lambda x: x["total_score"], reverse=True)
            print(f"\n📂 【{industry}】 (共 {len(picks)} 檔)")
            print("-" * 60)
            for pick in picks:
                t = pick['ticker']
                name = ticker_name_map.get(t, "") if ticker_name_map else ""
                yoy_str = f"{pick['revenue_yoy']:.1f}%" if not math.isnan(pick['revenue_yoy'] or 0) else "N/A"
                eps_str = f"{pick['eps_yoy']:.1f}%" if pick.get('eps_yoy') is not None else "N/A"
                accel_str = "🚀" if pick.get('is_accel') else ""
                # 突破狀態標註
                if pick.get('is_breakout'):
                    pivot_str = f"🚀 已突破! 放量{pick['breakout_vol_ratio']*100:.0f}% Pivot:{pick['pivot_point']:.2f}"
                elif pick.get('is_false_breakout'):
                    pivot_str = f"⚠️  假突破 Pivot:{pick['pivot_point']:.2f}"
                else:
                    pivot_str = f"⏳ 等待突破 Pivot:{pick['pivot_point']:.2f}" if pick.get('pivot_point') else ""
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
        while True:
            ticker = input("請輸入股票代碼（純數字或加後綴，輸入 q 結束）：").upper()
            if ticker == 'Q':
                break
                
            search_ticker = ticker
            if ticker.isdigit():
                if f"{ticker}.TW" in ticker_industry_map:
                    search_ticker = f"{ticker}.TW"
                elif f"{ticker}.TWO" in ticker_industry_map:
                    search_ticker = f"{ticker}.TWO"
            
            if search_ticker in ticker_industry_map:
                name = ticker_name_map.get(search_ticker, '未知名稱')
                ind  = ticker_industry_map.get(search_ticker, '未知產業')
                print(f"\n🏷️ 查詢標的：{search_ticker} {name} ({ind})")
                
            analyze_vcp(search_ticker, silent=False)
            print("  👴🏿 祝您發大財！👴🏿\n")




    else:
        print("無效的選擇，程式終止。")
