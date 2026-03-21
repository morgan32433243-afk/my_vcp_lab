import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import warnings
import os
import ssl

# 解決 SSL 憑證驗證失敗問題
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['PYTHONHTTPSVERIFY'] = '0'

# 隱藏所有警告，包括 matplotlib 的字體警告
warnings.filterwarnings('ignore')

def analyze_vcp(ticker_symbol, output_filename=None, silent=False):
    original_ticker = ticker_symbol
    # 抓取數據：使用 yfinance 抓取單一美股或台股過去 250 天的歷史數據。
    end_date = datetime.now()
    # 獲取約 375 天的數據以確保有足夠的 250 個交易日來計算移動平均線
    start_date = end_date - timedelta(days=250 * 1.5)

    data = pd.DataFrame() # 初始化空的 DataFrame

    # 自動修正格式：如果輸入是純數字（台股代號），請自動幫我補上 .TW 或 .TWO 後綴並嘗試抓取
    if ticker_symbol.isdigit():
        ticker_tw = ticker_symbol + ".TW"
        ticker_two = ticker_symbol + ".TWO"
        
        final_ticker = None # 用於儲存成功抓取數據的股票代碼

        # 嘗試 .TW (上市)
        if not silent: print(f"嘗試分析股票: {ticker_tw}")
        try:
            data = yf.download(ticker_tw, start=start_date, end=end_date, progress=False)
            if not data.empty:
                final_ticker = ticker_tw
        except Exception:
            pass # 忽略第一次下載的錯誤

        # 如果 .TW 失敗或數據為空，則嘗試 .TWO (上櫃)
        if data.empty:
            if not silent: print(f"嘗試分析股票: {ticker_two}")
            try:
                data = yf.download(ticker_two, start=start_date, end=end_date, progress=False)
                if not data.empty:
                    final_ticker = ticker_two
            except Exception:
                pass # 忽略第二次下載的錯誤

        # 如果兩次都失敗
        if data.empty:
            if not silent: print(f"錯誤: 無法抓取 {original_ticker} (或其 .TW/.TWO 變體) 的數據。請檢查股票代碼是否正確。")
            return None # 返回 None 表示失敗
        else:
            # 更新 ticker_symbol 為成功抓取的代碼
            ticker_symbol = final_ticker
            if not silent: print(f"成功分析股票: {ticker_symbol}") # 顯示最終分析的股票代碼

    else: # 如果不是純數字，則直接使用原始輸入
        if not silent: print(f"分析股票: {ticker_symbol}")
        try:
            data = yf.download(ticker_symbol, start=start_date, end=end_date, progress=False)
        except Exception:
            if not silent: print(f"抓取 {ticker_symbol} 數據時發生未預期錯誤。請稍後再試或檢查網路連線。")
            return None # 返回 None 表示失敗
        if data.empty:
            if not silent: print(f"錯誤: 無法抓取 {ticker_symbol} 的數據。請檢查股票代碼是否正確。")
            return None # 返回 None 表示失敗

    # 確保有足夠的數據來計算 200MA 和平均成交量
    if len(data) < 200:
        if not silent: print(f"數據不足以計算移動平均線，目前只有 {len(data)} 天數據。")
        return None # 返回 None 表示數據不足

    # 計算移動平均線、平均成交量和累積動能相關數據
    data['200MA'] = data['Close'].rolling(window=200).mean()
    data['150MA'] = data['Close'].rolling(window=150).mean()
    data['50MA'] = data['Close'].rolling(window=50).mean()
    data['Vol_5_MA'] = data['Volume'].rolling(window=5).mean() # 近5日平均成交量
    data['Vol_20_MA'] = data['Volume'].rolling(window=20).mean() # 近20日平均成交量

    # 獲取最新的數據點並明確提取為純數值
    latest_close = data['Close'].iloc[-1].item()
    latest_200MA = data['200MA'].iloc[-1].item()
    latest_150MA = data['150MA'].iloc[-1].item()
    latest_50MA = data['50MA'].iloc[-1].item()
    latest_vol_5_ma = data['Vol_5_MA'].iloc[-1].item()
    latest_vol_20_ma = data['Vol_20_MA'].iloc[-1].item()

    # 取得 5 日前的收盤價，用於買盤動能判斷
    price_5_days_ago = None
    if len(data) >= 5:
        price_5_days_ago = data['Close'].iloc[-5].item()

    # 檢查關鍵數據點是否為 NaN
    if pd.isna(latest_200MA) or pd.isna(latest_150MA) or pd.isna(latest_50MA) or \
       pd.isna(latest_vol_5_ma) or pd.isna(latest_vol_20_ma) or price_5_days_ago is None:
        if not silent: print("移動平均線、成交量或價格數據不足以進行完整分析。")
        return None # 返回 None 表示數據不足

    # 計算 250 日最高價
    highest_250_day_price = data['High'].iloc[-250:].max().item()

    # 現在比較的是純數字，不會有 Series 標籤對齊問題
    # 新增相對強度檢查：當前價格在 250 日最高價的 25% 範圍內 (即 >= 75% 最高價)
    is_uptrend = (latest_close > latest_200MA) and \
                 (latest_150MA > latest_200MA) and \
                 (latest_close >= highest_250_day_price * 0.75)

    if not silent:
        if not is_uptrend:
            print(f"股票 {ticker_symbol} 不符合上升趨勢或相對強度條件。")
            print(f"  最新收盤價: {latest_close:.2f}")
            print(f"  50MA: {latest_50MA:.2f}")  # 顯示 50MA
            print(f"  150MA: {latest_150MA:.2f}")
            print(f"  200MA: {latest_200MA:.2f}")
            print(f"  250日最高價: {highest_250_day_price:.2f}")
        else:
            print(f"股票 {ticker_symbol} 符合上升趨勢與相對強度條件。")
            print(f"  最新收盤價: {latest_close:.2f}")
            print(f"  50MA: {latest_50MA:.2f}")  # 顯示 50MA
            print(f"  150MA: {latest_150MA:.2f}")
            print(f"  200MA: {latest_200MA:.2f}")
            print(f"  250日最高價: {highest_250_day_price:.2f}")

    # VCP 型態偵測：找出過去 20 個交易日內，價格波動（High-Low 的百分比）是否呈現逐漸縮小的趨勢（收縮型態）。
    # 計算每日波動百分比
    data['Volatility'] = ((data['High'] - data['Low']) / data['Close']) * 100

    # 考慮過去 20 個交易日的波動數據
    last_20_days_volatility = data['Volatility'].iloc[-20:].dropna()

    if len(last_20_days_volatility) < 2: # 至少需要 2 天數據才能比較波動
        if not silent: print("過去 20 個交易日數據不足以分析 VCP 型態。")
        return None # 返回 None 表示數據不足

    # 計算收縮次數 (T) 和記錄收縮波動百分比 (包含日期)
    T_count = 0
    # 修改：用於儲存每次收縮時的 (日期, 波動百分比)
    contraction_points = [] 

    for i in range(1, len(last_20_days_volatility)):
        if last_20_days_volatility.iloc[i] < last_20_days_volatility.iloc[i-1]:
            T_count += 1
            # 記錄當前收縮時的 (日期, 波動百分比)
            contraction_points.append((last_20_days_volatility.index[i], last_20_days_volatility.iloc[i]))

    # 目前的波動百分比
    current_volatility_percentage = last_20_days_volatility.iloc[-1]

    if not silent:
        # 顯示結果：列印出計算出的收縮次數（T）與目前的波動百分比。
        print(f"\nVCP 型態偵測 (過去 {len(last_20_days_volatility)} 個交易日):")
        print(f"  收縮次數 (T): {T_count}")
        print(f"  目前的波動百分比: {current_volatility_percentage:.2f}%")

        # VCP 邏輯加強：如果檢測到股價正在處於『波動收縮』階段，計算最近三波的高低差比例。
        if T_count > 0: # 只有在有收縮發生時才顯示此信息
            if len(contraction_points) >= 3: # contraction_volatility_levels 替換為 contraction_points
                print("  最近三波波動收縮比例 (由最新往回): ", end="")
                # 取得最後三波收縮的波動百分比
                last_three_contractions_values = [f"{v[1]:.2f}%" for v in contraction_points[-3:]] # 提取數值部分
                print(" -> ".join(last_three_contractions_values))
            elif len(contraction_points) > 0: # contraction_volatility_levels 替換為 contraction_points
                print(f"  已檢測到 {len(contraction_points)} 波波動收縮。")
                print("  所有波動收縮比例: ", end="")
                all_contractions_values = [f"{v[1]:.2f}%" for v in contraction_points] # 提取數值部分
                print(" -> ".join(all_contractions_values))
        else:
            print("  未檢測到波動收縮階段。")

        # 新增的波動收縮小於 2% 的提醒
        if current_volatility_percentage < 2.0:
            print("\n" + "⭐⭐⭐" * 5) # 大大的星星
            print("高度關注！洗盤可能已結束，型態極度緊縮。")
            print("⭐⭐⭐" * 5 + "\n")

        # 最後輸出一句：祝劉先生在投資路上穩定獲利！
        print("\n祝劉先生在投資路上穩定獲利！")

    # 繪圖功能
    if not data.empty and output_filename: # 只有在提供檔名時才繪圖
        fig, ax = plt.subplots(figsize=(12, 7))

        ax.plot(data.index, data['Close'], label='Close Price', color='black', linewidth=1.5)
        ax.plot(data.index, data['50MA'], label='50MA', color='blue', linestyle='--')
        ax.plot(data.index, data['150MA'], label='150MA', color='orange', linestyle='--')
        ax.plot(data.index, data['200MA'], label='200MA', color='red', linestyle='--')

        # 標註最後三波收縮區間
        if len(contraction_points) >= 3:
            last_three_contraction_points = contraction_points[-3:]
            
            # 從最舊的收縮點開始標註
            for i, (date, vol_pct) in enumerate(last_three_contraction_points):
                # 為了標註一整天，我們從收縮日期的開始到結束
                ax.axvspan(date - timedelta(hours=12), date + timedelta(hours=12), color='lightgreen', alpha=0.3, lw=0)
                # 在日期附近標註百分比，稍微偏移以避免重疊
                ax.text(date, ax.get_ylim()[1] * (0.95 - i*0.02), f"{vol_pct:.2f}%", 
                        color='darkgreen', fontsize=9, ha='center', va='top')
            
        ax.set_title(f"{ticker_symbol} Price Trend and VCP Analysis", fontsize=16)
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel("Price", fontsize=12)
        ax.legend(loc='upper left')
        ax.grid(True, linestyle='--', alpha=0.6)

        # 格式化x軸日期
        fig.autofmt_xdate()

        plt.tight_layout()
        plt.savefig(output_filename)
        plt.close()
        if not silent: print(f"\n股價走勢圖已儲存為 {output_filename}")

    # 返回分析結果
    return {
        "ticker": ticker_symbol,
        "current_price": latest_close,
        "ma150": latest_150MA,
        "avg_volume": latest_vol_20_ma, # 將 avg_volume 更新為 latest_vol_20_ma (20日平均成交量)
        "vol_5_ma": latest_vol_5_ma,
        "vol_20_ma": latest_vol_20_ma,
        "price_5_days_ago": price_5_days_ago,
        "current_volatility_percentage": current_volatility_percentage,
        "t_count": T_count,
        "is_uptrend": is_uptrend,
        "highest_250_day_price": highest_250_day_price # 將 250 日最高價加入結果
    }

if __name__ == "__main__":
    while True:
        ticker = input("請輸入股票代碼（輸入 q 結束）：").upper()
        if ticker == 'Q':
            break
        # 在交互模式下，不靜默輸出，並將圖表保存到手動模式專用目錄
        output_dir_manual = "vcp_plots_manual"
        if not os.path.exists(output_dir_manual):
            os.makedirs(output_dir_manual)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plot_filename = os.path.join(output_dir_manual, f"vcp_plot_{ticker}_{timestamp}.png")
        analyze_vcp(ticker, output_filename=plot_filename, silent=False)
