import os
import ssl

# 解決 macOS 上 Python 3.x 抓取網頁時的 SSL 憑證驗證失敗問題
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['PYTHONHTTPSVERIFY'] = '0'

from datetime import datetime
import pandas as pd # Import pandas for data processing
import re # Import re for regular expressions
from vcp_analyzer import analyze_vcp # Assuming vcp_analyzer.py is in the same directory

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
        # 2. 遍歷第一欄，抓取『4位數字 + 空格』開頭的字串
        for val in full_df.iloc[:, 0]:
            s_val = str(val)
            if re.match(r'^\d{4}\s', s_val):
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

def batch_scan_vcp(tickers_to_scan):
    output_dir = "vcp_plots_batch"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    print(f"開始批次掃描 VCP 型態，結果將儲存至 {output_dir}/")
    
    ultimate_picks = [] # 儲存通過所有四層篩選的股票
    total_scanned = len(tickers_to_scan)
    ma150_passed_count = 0
    liquidity_passed_count = 0
    accumulation_passed_count = 0
    vcp_tight_count = 0

    for i, ticker in enumerate(tickers_to_scan):
        print(f"\n--- 篩選股票: {ticker} ({i+1}/{total_scanned}) ---")
        
        # 為每個股票生成唯一的輸出檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plot_filename = os.path.join(output_dir, f"vcp_plot_{ticker}_{timestamp}.png")
        
        # 以靜默模式呼叫 analyze_vcp，讓它返回數據而不打印詳細信息
        result = analyze_vcp(ticker, output_filename=plot_filename, silent=True)
        
        # 性能優化：如果數據抓取失敗或數據不足，立刻跳過
        if result is None:
            print(f"股票 {ticker} 數據抓取失敗或數據不足，快速跳過。")
            continue

        # 第一層：趨勢濾網 (綜合趨勢與相對強度)
        if not result["is_uptrend"]:
            print(f"股票 {ticker} 未通過趨勢濾網 (不符合上升趨勢或相對強度不足)，快速跳過。")
            continue
        ma150_passed_count += 1

        # 第二層：流動性濾網 (Volume) — 20 日平均成交量 > 1000,0000 股
        if result["avg_volume"] < 10_000_000:
            print(f"股票 {ticker} 未通過流動性濾網 (20日平均成交量 < 1000,0000 股)，快速跳過。")
            continue
        liquidity_passed_count += 1

        # 第三層：買盤動能 (Accumulation) — 近 5 日量 > 近 20 日量，且今日價 > 5 日前價
        is_accumulating = (result["vol_5_ma"] > result["vol_20_ma"]) and \
                          (result["current_price"] > result["price_5_days_ago"])
        if not is_accumulating:
            print(f"股票 {ticker} 未通過買盤動能濾網 (未見明顯買盤動能)，快速跳過。")
            continue
        accumulation_passed_count += 1

        # 第四層：籌碼乾淨度 (VCP) — 最近一波收縮 < 7%
        if not (result["t_count"] > 0 and result["current_volatility_percentage"] < 7.0):
            print(f"股票 {ticker} 未通過籌碼乾淨度濾網 (VCP收縮不夠緊密)，快速跳過。")
            continue
        vcp_tight_count += 1

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

        # 如果通過所有四層篩選，加入最終清單
        ultimate_picks_info = {
            "ticker": result["ticker"],
            "current_price": result["current_price"],
            "ma150": result["ma150"],
            "avg_volume_shares": int(result["avg_volume"] / 1000), # 轉換為張
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
        print(f"{'股票代碼':<12} | {'最新價格':<10} | {'MA150':<10} | {'平均成交量(張)':<15} | {'波動度':<8} | {'狀態':<15}")
        print("-" * 90) 
        for pick in ultimate_picks:
            print(f"{pick['ticker']:<12} | {pick['current_price']:.2f}{'':<4} | {pick['ma150']:.2f}{'':<4} | {pick['avg_volume_shares']:<15} | {pick['current_volatility_percentage']:.2f}%{'':<3} | {pick['status']:<15}")
        print("="*90)
    else:
        print("\n今日沒有偵測到全市場最優選股票。")
    
    print("\n" + "="*50)
    print("今日全市場掃描統計:")
    print("="*50)
    print(f"今日總計掃描 {total_scanned} 檔股票。")
    print(f"通過趨勢濾網 (上升趨勢 & 相對強度): {ma150_passed_count} 檔。")
    print(f"通過流動性濾網 (20日均量 > 1000萬): {liquidity_passed_count} 檔。")
    print(f"通過買盤動能濾網 (近5日量 > 近20日量 且 今日價 > 5日前價): {accumulation_passed_count} 檔。")
    print(f"通過籌碼乾淨度濾網 (VCP < 7%): {vcp_tight_count} 檔。")
    print("==================================================")


if __name__ == "__main__":
    user_choice = input("是否掃描全台股市場？(Y/N): ").upper()

    if user_choice == 'Y':
        print("開始下載台灣所有股票清單...")
        tickers = get_stock_list()
        print(f"成功下載 {len(tickers)} 檔股票。")
        batch_scan_vcp(tickers)
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
