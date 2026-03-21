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

def calculate_recent_pullbacks(df, lookback=120, order=5):
    """
    計算最近幾波的回檔深度 (波峰到波谷)
    order: 波峰/波谷的左右區間大小
    """
    if len(df) < lookback:
        df_recent = df
    else:
        df_recent = df.iloc[-lookback:]
        
    highs = df_recent['High'].values
    lows = df_recent['Low'].values
    
    peaks = []
    for i in range(order, len(highs) - order):
        if all(highs[i] >= highs[i-order:i]) and all(highs[i] >= highs[i+1:i+order+1]):
            peaks.append((i, highs[i]))
            
    pullbacks = []
    for j in range(len(peaks)):
        peak_idx, peak_val = peaks[j]
        next_peak_idx = peaks[j+1][0] if j + 1 < len(peaks) else len(highs)
        
        segment_lows = lows[peak_idx:next_peak_idx]
        if len(segment_lows) > 0:
            min_low = min(segment_lows)
            drop_pct = (peak_val - min_low) / peak_val * 100
            pullbacks.append(drop_pct)
            
    recent_3 = pullbacks[-3:] if len(pullbacks) >= 3 else pullbacks
    
    is_decreasing = False
    if len(recent_3) >= 2:
        is_decreasing = all(recent_3[i] > recent_3[i+1] for i in range(len(recent_3)-1))
        
    return recent_3, is_decreasing

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

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.droplevel(1)

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

    # 計算成交額、5日與50日均成交額 (雙軌流動性)
    data['Turnover'] = data['Close'] * data['Volume']
    data['Turnover_5_MA'] = data['Turnover'].rolling(window=5).mean()
    data['Turnover_50_MA'] = data['Turnover'].rolling(window=50).mean()

    # 獲取最新的數據點並明確提取為純數值
    latest_close = data['Close'].iloc[-1].item()
    latest_200MA = data['200MA'].iloc[-1].item()
    latest_150MA = data['150MA'].iloc[-1].item()
    latest_50MA = data['50MA'].iloc[-1].item()
    latest_vol_5_ma = data['Vol_5_MA'].iloc[-1].item()
    latest_vol_20_ma = data['Vol_20_MA'].iloc[-1].item()
    latest_turnover_50_ma = data['Turnover_50_MA'].iloc[-1].item()
    latest_turnover_5_ma = data['Turnover_5_MA'].iloc[-1].item()

    # 計算流動性
    is_liquid = (latest_turnover_50_ma > 30_000_000) and (latest_turnover_5_ma > 50_000_000)

    # 取得 5 日前的收盤價，用於買盤動能判斷
    price_5_days_ago = None
    if len(data) >= 5:
        price_5_days_ago = data['Close'].iloc[-5].item()

    # 檢查關鍵數據點是否為 NaN
    if pd.isna(latest_200MA) or pd.isna(latest_150MA) or pd.isna(latest_50MA) or \
       pd.isna(latest_vol_5_ma) or pd.isna(latest_vol_20_ma) or price_5_days_ago is None:
        if not silent: print("移動平均線、成交量或價格數據不足以進行完整分析。")
        return None # 返回 None 表示數據不足

    # 計算 250 日最高/最低價
    highest_250_day_price = data['High'].iloc[-250:].max().item()
    lowest_250_day_price = data['Low'].iloc[-250:].min().item()

    # 計算 20天前的 200MA
    ma200_series = data['200MA'].dropna()
    ma200_20_days_ago = ma200_series.iloc[-20].item() if len(ma200_series) >= 20 else None

    # 現在比較的是純數字，不會有 Series 標籤對齊問題
    # 嚴格趨勢檢查：確保符合 Close > 50MA > 150MA > 200MA 的多頭排列
    is_uptrend = (latest_close > latest_50MA > latest_150MA > latest_200MA)

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
    import numpy as np
    data['Volatility'] = ((data['High'] - data['Low']) / data['Close']) * 100
    data['Volatility'] = data['Volatility'].replace([np.inf, -np.inf], np.nan).fillna(0)

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

    # 計算 Volume Dry Up (VDU)
    # 在最後一次收縮處，成交量必須低於過去 20 天平均量的 50%
    is_vdu = False
    vdu_vol_ratio = None
    if contraction_points:
        last_contraction_date, _ = contraction_points[-1]
        if last_contraction_date in data.index:
            last_vol = data['Volume'].loc[last_contraction_date]
            last_vol_20ma = data['Vol_20_MA'].loc[last_contraction_date]
            if hasattr(last_vol, "item"): last_vol = last_vol.item()
            if hasattr(last_vol_20ma, "item"): last_vol_20ma = last_vol_20ma.item()
            if not pd.isna(last_vol) and not pd.isna(last_vol_20ma) and last_vol_20ma > 0:
                vdu_vol_ratio = last_vol / last_vol_20ma
                if vdu_vol_ratio < 0.5:
                    is_vdu = True

    # 計算最近三波的回檔深度並驗證遞減規則
    recent_pullbacks, pullbacks_decreasing = calculate_recent_pullbacks(data)

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
    results = {
        "ticker": ticker_symbol,
        "is_vdu": is_vdu,
        "vdu_vol_ratio": vdu_vol_ratio,
        "recent_pullbacks": recent_pullbacks,
        "pullbacks_decreasing": pullbacks_decreasing,
        "current_price": latest_close,
        "ma150": latest_150MA,
        "avg_volume": latest_vol_20_ma,
        "vol_5_ma": latest_vol_5_ma,
        "vol_20_ma": latest_vol_20_ma,
        "price_5_days_ago": price_5_days_ago,
        "current_volatility_percentage": current_volatility_percentage,
        "t_count": T_count,
        "is_uptrend": is_uptrend,
        "is_liquid": is_liquid,
        "is_safe_liquidity": is_liquid,
        "highest_250_day_price": highest_250_day_price,
        "lowest_250_day_price": lowest_250_day_price,
        "ma50": latest_50MA,
        "ma200": latest_200MA,
        "ma200_20_days_ago": ma200_20_days_ago,
        "turnover_5_ma": latest_turnover_5_ma,
        "turnover_50_ma": latest_turnover_50_ma
    }

    # 繪圖引擎：由外部決定是否傳入 output_filename，有傳入即無條件繪圖
    if output_filename and not data.empty:
        # 只有符合條件才執行繪圖
        fig, (ax_price, ax_vol) = plt.subplots(2, 1, figsize=(12, 10), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)

        ax_price.plot(data.index, data['Close'], label='Close Price', color='black', linewidth=1.5)
        ax_price.plot(data.index, data['50MA'], label='50MA', color='blue', linestyle='--')
        ax_price.plot(data.index, data['150MA'], label='150MA', color='orange', linestyle='--')
        ax_price.plot(data.index, data['200MA'], label='200MA', color='red', linestyle='--')

        # VCP 收縮三角形視覺化
        if contraction_points:
            start_date = contraction_points[0][0]
            end_date = data.index[-1]
            vcp_data = data.loc[start_date:end_date]
            if len(vcp_data) > 1:
                x_coords = [start_date, end_date]
                
                max_high = vcp_data['High'].max()
                min_low = vcp_data['Low'].min()
                if hasattr(max_high, "item"): max_high = max_high.item()
                if hasattr(min_low, "item"): min_low = min_low.item()
                
                y_upper = [max_high, latest_close]
                y_lower = [min_low, latest_close]
                ax_price.fill_between(x_coords, y_lower, y_upper, color='gray', alpha=0.2, lw=0)

        # 標註最後三波收縮區間
        if len(contraction_points) >= 3:
            last_three_contraction_points = contraction_points[-3:]
            
            # 從最舊的收縮點開始標註
            for i, (date, vol_pct) in enumerate(last_three_contraction_points):
                # 為了標註一整天，我們從收縮日期的開始到結束
                ax_price.axvspan(date - timedelta(hours=12), date + timedelta(hours=12), color='lightgreen', alpha=0.3, lw=0)
                # 在日期附近標註百分比，稍微偏移以避免重疊
                ax_price.text(date, ax_price.get_ylim()[1] * (0.95 - i*0.02), f"{vol_pct:.2f}%", 
                        color='darkgreen', fontsize=9, ha='center', va='top')
            
        ax_price.set_title(f"{ticker_symbol} Price Trend and VCP Analysis", fontsize=16)
        ax_price.set_ylabel("Price", fontsize=12)
        ax_price.legend(loc='upper left')
        ax_price.grid(True, linestyle='--', alpha=0.6)

        # 繪製成交量子圖 (紅漲綠跌)
        if 'Open' in data.columns:
            colors = ['red' if c >= o else 'green' for c, o in zip(data['Close'], data['Open'])]
        else:
            colors = ['red' if i == 0 or data['Close'].iloc[i] >= data['Close'].iloc[i-1] else 'green' for i in range(len(data))]
            
        ax_vol.bar(data.index, data['Volume'], color=colors, alpha=0.7)
        ax_vol.set_ylabel("Volume", fontsize=12)
        ax_vol.set_xlabel("Date", fontsize=12)
        ax_vol.grid(True, linestyle='--', alpha=0.6)

        # 若為 VDU 狀態，在最後一次收縮處標記 VDU (量縮窒息)
        if is_vdu and contraction_points:
            vdu_date = contraction_points[-1][0]
            if vdu_date in data.index:
                vdu_vol = data['Volume'].loc[vdu_date]
                if hasattr(vdu_vol, "item"): vdu_vol = vdu_vol.item()
                ax_vol.annotate('VDU', xy=(vdu_date, vdu_vol), xytext=(0, 25),
                                textcoords='offset points', ha='center', va='bottom',
                                arrowprops=dict(facecolor='blue', shrink=0.05, width=1.5, headwidth=6),
                                fontsize=10, color='blue', fontweight='bold',
                                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="blue", alpha=0.8))

        # 格式化x軸日期
        fig.autofmt_xdate()

        plt.tight_layout()
        plt.savefig(output_filename)
        plt.clf()
        plt.close('all')
        import gc; gc.collect()
        if not silent: print(f"\n股價走勢圖已儲存為 {output_filename}")
        
    return results

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
