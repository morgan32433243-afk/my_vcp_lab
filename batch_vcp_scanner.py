import os
import ssl

# 解決 macOS 上 Python 3.x 抓取網頁時的 SSL 憑證驗證失敗問題
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['PYTHONHTTPSVERIFY'] = '0'

from datetime import datetime
import pandas as pd # Import pandas for data processing
import re # Import re for regular expressions
import requests
from vcp_analyzer import analyze_vcp # Assuming vcp_analyzer.py is in the same directory

def get_revenue_yoy(ticker_symbol):
    """
    使用 FinMind API 獲取最近一個月的營收年增率 (YoY)。
    """
    # 處理台股代號 (如 2330.TW -> 2330)
    stock_id = ticker_symbol.split('.')[0]
    
    # 設置查詢日期範圍 (過去 450 天以確保包含去年同期)
    from datetime import date, timedelta
    start_date = (date.today() - timedelta(days=450)).strftime('%Y-%m-%d')
    
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockMonthRevenue",
        "data_id": stock_id,
        "start_date": start_date
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json().get('data', [])
        
        if len(data) < 13:
            return None, "數據不足"
        
        # 獲取最新的一個月資料
        latest_revenue = data[-1]
        
        # 尋找去年同期的資料 (同月份但年份減1)
        target_month = latest_revenue['revenue_month']
        target_year = latest_revenue['revenue_year'] - 1
        
        last_year_revenue = None
        for item in reversed(data[:-1]):
            if item['revenue_month'] == target_month and item['revenue_year'] == target_year:
                last_year_revenue = item
                break
        
        if last_year_revenue:
            rev_now = latest_revenue['revenue']
            rev_then = last_year_revenue['revenue']
            if rev_then > 0:
                yoy = ((rev_now - rev_then) / rev_then) * 100
                return yoy, f"{latest_revenue['revenue_year']}/{latest_revenue['revenue_month']} 營收年增: {yoy:.2f}%"
        return None, "資料缺漏"
            
    except Exception:
        return None, "API 異常"

def get_stock_list():
    import pandas as pd
    import re
    print("開始下載台灣所有股票清單...")
    try:
        # 1. 抓取上市與上櫃 (指定 cp950 編碼並跳過錯誤)
        twse_url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=2'
        tpex_url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=4'
        
        twse = pd.read_html(twse_url, encoding='cp950')[0]
        tpex = pd.read_html(tpex_url, encoding='cp950')[0]
        full_df = pd.concat([twse, tpex])
        
        ticker_list = []
        # 2. 遍歷第一欄，抓取『4位數字 + 空格』或『ETF (00開頭)』開頭的字串
        for val in full_df.iloc[:, 0]:
            s_val = str(val)
            if re.match(r'^\d{4}\s', s_val) or re.match(r'^00[a-zA-Z0-9]{2,4}\s', s_val):
                ticker = s_val.split('\u3000')[0].strip() # 處理全型空白
                # 判斷歸屬市場
                suffix = ".TW" if s_val in twse.iloc[:, 0].values else ".TWO"
                ticker_list.append(f"{ticker}{suffix}")
        
        final_tickers = sorted(list(set(ticker_list)))
        print(f"成功篩選出 {len(final_tickers)} 檔真實股票代號")
        return final_tickers
    except Exception as e:
        print(f"下載失敗: {e}")
        return []

def load_revenue_cache():
    import pandas as pd
    import os
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

def batch_scan_vcp(tickers_to_scan, enable_revenue_filter=False):
    output_dir = "vcp_plots_batch"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    print(f"開始批次掃描 VCP 型態，結果將儲存至 {output_dir}/")
    
    revenue_cache = {}
    if enable_revenue_filter:
        revenue_cache = load_revenue_cache()
        if not revenue_cache:
            print("[警告] 尚未發現 taiwan_revenue.csv 快取，將觸發即時 FinMind 抓取 (受限於 300次/小時)！")
            print("建議先獨立執行 python3 update_revenue.py 抓取整包營收資料。")
    
    ultimate_picks = [] # 儲存通過所有篩選的股票
    total_scanned = len(tickers_to_scan)
    
    ma150_passed_tickers = []
    liquidity_passed_tickers = []
    revenue_passed_tickers = []
    accumulation_passed_tickers = []
    vcp_tight_tickers = []

    for i, ticker in enumerate(tickers_to_scan):
        if (i+1) % 30 == 0:
            import time
            time.sleep(2)
            print(f"\n--- 進度報告: 已完成 {i+1}/{total_scanned} ---")
            
        print(f"\n--- 篩選股票: {ticker} ({i+1}/{total_scanned}) ---")
        
        # 為每個股票生成唯一的輸出檔名 (後移)
        
        # 以靜默模式呼叫 analyze_vcp，讓它純運算不繪圖，大幅增進效能避免無用的 IO
        try:
            result = analyze_vcp(ticker, output_filename=None, silent=True)
        except Exception as e:
            print(f"股票 {ticker} 分析過程中發生未預期錯誤 ({e})，安全跳過。")
            continue
        
        # 性能優化：如果數據抓取失敗或數據不足，立刻跳過
        if result is None:
            print(f"股票 {ticker} 數據抓取失敗或數據不足，快速跳過。")
            continue

        # 取得流動性與趨勢，主迴圈攔截
        is_uptrend = result.get("is_uptrend", False)
        is_liquid = result.get("is_liquid", False)

        # 2. 在主迴圈判斷
        if result and result.get('is_uptrend') and result.get('is_safe_liquidity'):
            print(f"✅ 符合條件！開始繪製: {ticker}")
            # 第二次呼叫：只有符合條件才傳入檔名開始畫圖
            analyze_vcp(ticker, output_filename=f"{output_dir}/{ticker}.png", silent=False)
            import matplotlib.pyplot as plt
            plt.close('all')
            import gc; gc.collect()
        else:
            # 完全不呼叫繪圖函式
            pass

        # 取得所需數據
        close = result["current_price"]
        ma50 = result.get("ma50")
        ma150 = result["ma150"]
        ma200 = result.get("ma200")
        ma200_20_days_ago = result.get("ma200_20_days_ago")
        year_high = result["highest_250_day_price"]
        year_low = result.get("lowest_250_day_price")

        # 確認數據完整
        if None in [ma50, ma200, ma200_20_days_ago, year_low]:
            print(f"股票 {ticker} 缺乏均線或高低點數據，快速跳過。")
            continue

        # 距離高低點位置 (保留經典馬克米奈爾維尼位置濾網以提高勝率)
        within_high_range = close >= (year_high * 0.75)
        above_low_range = close >= (year_low * 1.30)

        # 第一層：趨勢濾網 (綜合趨勢與相對強度)
        if not (is_uptrend and within_high_range and above_low_range):
            print(f"股票 {ticker} 未通過趨勢濾網 (不符合多頭排列、或距離高低點位置限制)，快速跳過。")
            continue
        ma150_passed_tickers.append(ticker)

        # 第二層：流動性濾網 (雙軌流動性)
        # (50日均成交額 > 3000萬) 且 (5日均成交額 > 5000萬)
        turnover_5_ma = result.get("turnover_5_ma", 0)
        turnover_50_ma = result.get("turnover_50_ma", 0)
        is_liquid = (turnover_50_ma > 30_000_000) and (turnover_5_ma > 50_000_000)
        
        if not is_liquid:
            print(f"股票 {ticker} 未通過流動性濾網 (不符合 50日>3000萬 且 5日>5000萬)，快速跳過。")
            continue
        liquidity_passed_tickers.append(ticker)

        # 第三層：基本面濾網 (Revenue) — 營收年增率 > 10% (ETF 免檢驗)
        import math
        yoy_val = 0.0
        if enable_revenue_filter:
            is_etf = ticker.startswith("00")
            if not is_etf:
                if ticker in revenue_cache:
                    yoy_val = revenue_cache[ticker]
                    if math.isnan(yoy_val) or yoy_val < 10.0:
                        y_fmt = f"{yoy_val:.2f}%" if not math.isnan(yoy_val) else "無資料"
                        print(f"股票 {ticker} 未通過基本面濾網 (營收年增未達 10%，快取紀錄為 {y_fmt})，快速跳過。")
                        continue
                    yoy_msg = f"營收年增: {yoy_val:.2f}% (來自本地快取)"
                else:
                    yoy_val_real, yoy_msg = get_revenue_yoy(ticker)
                    if yoy_val_real is not None:
                        yoy_val = yoy_val_real
                    if yoy_val_real is None or yoy_val_real < 10.0:
                        reason = yoy_msg if yoy_val_real is not None else "無法取得營收資料"
                        print(f"股票 {ticker} 未通過基本面濾網 ({reason})，快速跳過。")
                        continue
                print(f"股票 {ticker} 通過基本面濾網 ({yoy_msg})")
                revenue_passed_tickers.append(ticker)
            else:
                print(f"股票 {ticker} 為 ETF，免除基本面營收檢驗。")
                revenue_passed_tickers.append(ticker)
        else:
            # 關閉營收檢驗時，所有標的自動通過
            revenue_passed_tickers.append(ticker)

        # 第四層：買盤動能 (Accumulation) — 近 5 日量 > 近 20 日量，且今日價 > 5 日前價
        is_accumulating = (result["vol_5_ma"] > result["vol_20_ma"]) and \
                          (result["current_price"] > result["price_5_days_ago"])
        if not is_accumulating:
            print(f"股票 {ticker} 未通過買盤動能濾網 (未見明顯買盤動能)，快速跳過。")
            continue
        accumulation_passed_tickers.append(ticker)

        # 第五層：籌碼乾淨度 (VCP) — 最近一波收縮 < 7%
        if not (result["t_count"] > 0 and result["current_volatility_percentage"] < 7.0):
            print(f"股票 {ticker} 未通過籌碼乾淨度濾網 (VCP收縮不夠緊密)，快速跳過。")
            continue
        vcp_tight_tickers.append(ticker)

        # 第五層：量能極度萎縮 (Volume Dry Up)
        if not result.get("is_vdu", False):
            print(f"股票 {ticker} 未通過量能萎縮濾網 (最後一次收縮處成交量 >= 20MA 的 50%)，快速跳過。")
            continue

        # 第六層：回檔遞減規則
        pullbacks = result.get("recent_pullbacks", [])
        is_decreasing = result.get("pullbacks_decreasing", False)
        if not is_decreasing:
            formatted_pb = " -> ".join([f"{p:.1f}%" for p in pullbacks]) if pullbacks else "無"
            print(f"股票 {ticker} 未通過回檔遞減濾網 (沒有呈現遞減規則: {formatted_pb})，快速跳過。")
            continue

        # 實作分級標註
        vcp_label = ""
        if result["current_volatility_percentage"] < 3.0:
            vcp_label = "🔥 極度緊縮"
        elif 3.0 <= result["current_volatility_percentage"] < 5.0:
            vcp_label = "✨ 高度關注"
        elif 5.0 <= result["current_volatility_percentage"] < 7.0:
            vcp_label = "⭐ 潛力標的"
        else:
            vcp_label = "未分類" # 應不會觸發，但作為預防

        # 分析完畢


        # 如果通過所有四層篩選，加入最終清單
        ultimate_picks_info = {
            "ticker": result["ticker"],
            "current_price": result["current_price"],
            "ma150": result["ma150"],
            "avg_volume_shares": int(result["avg_volume"] / 1000), # 轉換為張
            "revenue_yoy": yoy_val,
            "current_volatility_percentage": result["current_volatility_percentage"],
            "status": vcp_label # 使用新的分級標註
        }
        ultimate_picks.append(ultimate_picks_info)
        print(f"股票 {ticker} 通過所有四層篩選，標註為 '{vcp_label}'！")
            
        print(f"--- 股票 {ticker} 篩選完成 ---")

    print("\n所有批次掃描已完成。")

    # 最終戰報：列出所有通過四層考驗的『全市場最優選』，並按波動度由小到大排序
    if ultimate_picks:
        # 按波動度由小到大排序
        ultimate_picks.sort(key=lambda x: x["current_volatility_percentage"])

        print("\n" + "="*60)
        print("今日全市場最優選:")
        print("="*60)
        # 打印表頭
        print(f"{'股票代碼':<12} | {'最新價格':<10} | {'MA150':<10} | {'營收年增':<12} | {'均量(張)':<12} | {'波動度':<8} | {'狀態':<15}")
        print("-" * 110) 
        for pick in ultimate_picks:
            print(f"{pick['ticker']:<12} | {pick['current_price']:.2f}{'':<4} | {pick['ma150']:.2f}{'':<4} | {pick['revenue_yoy']:>8.2f}%{'':<3} | {pick['avg_volume_shares']:<12} | {pick['current_volatility_percentage']:.2f}%{'':<3} | {pick['status']:<15}")
        print("="*110)
    else:
        print("\n今日沒有偵測到全市場最優選股票。")
    
    print("\n" + "="*50)
    print("今日全市場掃描統計:")
    print("="*50)
    print(f"今日總計掃描 {total_scanned} 檔股票。")
    print(f"通過趨勢濾網 (上升趨勢 & 相對強度): {len(ma150_passed_tickers)} 檔。")
    print(f"通過流動性濾網 (50日>3000W 且 5日>5000W): {len(liquidity_passed_tickers)} 檔。")
    print(f"通過基本面濾網 (營收年增 > 10%): {len(revenue_passed_tickers)} 檔。")
    print(f"通過買盤動能濾網 (近5日量 > 近20日量 且 今日價 > 5日前價): {len(accumulation_passed_tickers)} 檔。")
    print(f"通過籌碼乾淨度濾網 (VCP < 7%): {len(vcp_tight_tickers)} 檔。")
    print("==================================================")
    
    # === 互動式查詢 ===
    def ask_to_show_list(prompt_text, tickers_list):
        if not tickers_list: return
        try:
            ans = input(f"是否想查看 {prompt_text}: {len(tickers_list)} 檔清單？(Y/N): ").upper()
            if ans == 'Y':
                print(f"\n[ {prompt_text} - 清單共 {len(tickers_list)} 檔 ]")
                print("-" * 50)
                
                # 自動排版為直式，每 3 欄並列
                cols = 3
                rows = (len(tickers_list) + cols - 1) // cols
                for r in range(rows):
                    line = ""
                    for c in range(cols):
                        idx = c * rows + r
                        if idx < len(tickers_list):
                            line += f"{idx+1:02d} | {tickers_list[idx]:<10}"
                    print(line)
                print("-" * 50 + "\n")
        except EOFError:
            pass

    print("\n")
    ask_to_show_list("通過趨勢濾網", ma150_passed_tickers)
    ask_to_show_list("通過流動性濾網", liquidity_passed_tickers)
    ask_to_show_list("通過基本面濾網", revenue_passed_tickers)
    ask_to_show_list("通過買盤動能濾網", accumulation_passed_tickers)
    ask_to_show_list("通過籌碼乾淨度濾網", vcp_tight_tickers)


if __name__ == "__main__":
    try:
        user_choice = input("是否掃描全台股市場？(Y/N): ").upper()
    except EOFError:
        user_choice = 'Y'

    if user_choice == 'Y':
        try:
            rev_choice = input("是否開啟營收年增濾網 (需注意 FinMind API 300次/小時 限制)？(Y/N): ").upper()
            enable_revenue_filter = (rev_choice == 'Y')
        except EOFError:
            enable_revenue_filter = False # 預設關閉營收濾網以防中斷
            
        tickers = get_stock_list()
        print(f"成功下載 {len(tickers)} 檔股票。")
        batch_scan_vcp(tickers, enable_revenue_filter=enable_revenue_filter)
    elif user_choice == 'N':
        print("\n進入手動輸入模式。")
        while True:
            ticker = input("請輸入股票代碼（輸入 q 結束）：").upper()
            if ticker == 'Q':
                break
            # 在交互模式下，不靜默輸出，並將圖表保存到手動模式專用目錄
            # output_dir_manual 的創建已移動到 analyze_vcp 內部調用，確保它始終存在
            analyze_vcp(ticker, silent=False) # analyze_vcp now handles output_dir_manual for interactive mode
            print("--- 單檔股票分析完成 ---")
    else:
        print("無效的選擇，程式終止。")
