import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import os
import ssl

# 解決 SSL 憑證驗證失敗問題
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['PYTHONHTTPSVERIFY'] = '0'

warnings.filterwarnings('ignore')

def calculate_recent_pullbacks(df, lookback=140, order=5):
    """
    計算最近幾波的回檔深度 (波峰到波谷)
    lookback: 約 20 週 (140 個交易日)，符合 VCP 理論的時間窗限制
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


def calculate_ud_volume_ratio(data, lookback=50):
    """
    計算 U/D Volume Ratio (上漲日總量 / 下跌日總量)
    > 1.0 代表多頭吃貨痕跡
    """
    df = data.iloc[-lookback:].copy()
    df['price_change'] = df['Close'].diff()
    up_vol = df[df['price_change'] > 0]['Volume'].sum()
    down_vol = df[df['price_change'] < 0]['Volume'].sum()
    if down_vol == 0:
        return 999.0  # 無下跌日，極端多頭
    return round(up_vol / down_vol, 2)


def analyze_vcp(ticker_symbol, silent=False):
    original_ticker = ticker_symbol
    end_date = datetime.now()
    start_date = end_date - timedelta(days=int(250 * 1.6))

    data = pd.DataFrame()

    # 自動修正格式：純數字台股代號自動嘗試 .TW 再 .TWO
    if ticker_symbol.isdigit():
        ticker_tw = ticker_symbol + ".TW"
        ticker_two = ticker_symbol + ".TWO"
        final_ticker = None

        if not silent: print(f"嘗試分析股票: {ticker_tw}")
        try:
            import io, contextlib
            _b = io.StringIO()
            ctx = contextlib.redirect_stderr(_b) if silent else contextlib.nullcontext()
            with ctx:
                data = yf.download(ticker_tw, start=start_date, end=end_date, progress=False)
            if not data.empty:
                final_ticker = ticker_tw
        except Exception:
            pass

        if data.empty:
            if not silent: print(f"嘗試分析股票: {ticker_two}")
            try:
                _b = io.StringIO()
                ctx = contextlib.redirect_stderr(_b) if silent else contextlib.nullcontext()
                with ctx:
                    data = yf.download(ticker_two, start=start_date, end=end_date, progress=False)
                if not data.empty:
                    final_ticker = ticker_two
            except Exception:
                pass

        if data.empty:
            if not silent: print(f"錯誤: 無法抓取 {original_ticker} 的數據。")
            return None
        else:
            ticker_symbol = final_ticker
            if not silent: print(f"成功分析股票: {ticker_symbol}")

    else:
        if not silent: print(f"分析股票: {ticker_symbol}")
        try:
            import io, contextlib
            _b = io.StringIO()
            ctx = contextlib.redirect_stderr(_b) if silent else contextlib.nullcontext()
            with ctx:
                data = yf.download(ticker_symbol, start=start_date, end=end_date, progress=False)
        except Exception:
            if not silent: print(f"抓取 {ticker_symbol} 數據時發生未預期錯誤。")
            return None
        if data.empty:
            if not silent: print(f"錯誤: 無法抓取 {ticker_symbol} 的數據。")
            return None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.droplevel(1)

    if len(data) < 200:
        if not silent: print(f"數據不足以計算移動平均線，目前只有 {len(data)} 天數據。")
        return None

    # 移動平均線
    data['200MA'] = data['Close'].rolling(window=200).mean()
    data['150MA'] = data['Close'].rolling(window=150).mean()
    data['50MA']  = data['Close'].rolling(window=50).mean()
    data['20MA']  = data['Close'].rolling(window=20).mean()
    data['10MA']  = data['Close'].rolling(window=10).mean()
    data['5MA']   = data['Close'].rolling(window=5).mean()
    data['Vol_20_MA'] = data['Volume'].rolling(window=20).mean()
    data['Vol_5_MA']  = data['Volume'].rolling(window=5).mean()

    # 成交金額
    data['Turnover'] = data['Close'] * data['Volume']
    data['Turnover_5_MA'] = data['Turnover'].rolling(window=5).mean()
    data['Turnover_50_MA'] = data['Turnover'].rolling(window=50).mean()

    latest_close   = data['Close'].iloc[-1].item()
    latest_200MA   = data['200MA'].iloc[-1].item()
    latest_150MA   = data['150MA'].iloc[-1].item()
    latest_50MA    = data['50MA'].iloc[-1].item()
    latest_20MA    = data['20MA'].iloc[-1].item()
    latest_10MA    = data['10MA'].iloc[-1].item()
    latest_5MA     = data['5MA'].iloc[-1].item()
    latest_vol_5_ma    = data['Vol_5_MA'].iloc[-1].item()
    latest_vol_20_ma   = data['Vol_20_MA'].iloc[-1].item()
    latest_turnover_50_ma = data['Turnover_50_MA'].iloc[-1].item()
    latest_turnover_5_ma  = data['Turnover_5_MA'].iloc[-1].item()

    is_liquid = (latest_turnover_50_ma > 30_000_000) and (latest_turnover_5_ma > 50_000_000)

    price_5_days_ago = data['Close'].iloc[-5].item() if len(data) >= 5 else None

    if pd.isna(latest_200MA) or pd.isna(latest_150MA) or pd.isna(latest_50MA) or \
       pd.isna(latest_vol_5_ma) or pd.isna(latest_vol_20_ma) or price_5_days_ago is None:
        if not silent: print("移動平均線、成交量或價格數據不足以進行完整分析。")
        return None

    highest_250_day_price = data['High'].iloc[-250:].max().item()
    lowest_250_day_price  = data['Low'].iloc[-250:].min().item()

    ma200_series = data['200MA'].dropna()
    ma200_20_days_ago = ma200_series.iloc[-20].item() if len(ma200_series) >= 20 else None

    # ===========================================================
    # 均線多頭排列診斷：逐條檢查 Close > 5MA > 10MA > 20MA > 50MA > 150MA > 200MA
    # ===========================================================
    ma_chain = [
        ("Close",  latest_close),
        ("5MA",    latest_5MA),
        ("10MA",   latest_10MA),
        ("20MA",   latest_20MA),
        ("50MA",   latest_50MA),
        ("150MA",  latest_150MA),
        ("200MA",  latest_200MA),
    ]
    ma_broken = []  # 未達標的連結
    for k in range(len(ma_chain) - 1):
        name_a, val_a = ma_chain[k]
        name_b, val_b = ma_chain[k + 1]
        if not (val_a > val_b):
            ma_broken.append(f"{name_a} < {name_b}")


    # 核心趨勢定義：至少需要 Close > 50MA > 150MA > 200MA
    is_uptrend = (latest_close > latest_50MA > latest_150MA > latest_200MA)

    if not silent:
        print("\n均線多頭排列診斷 (Close > 5MA > 10MA > 20MA > 50MA > 150MA > 200MA):")
        if not ma_broken:
            print("  ✅ 全部均線完美多頭排列！")
        else:
            print(f"  ✅ 達標連結: {len(ma_chain)-1 - len(ma_broken)}/{len(ma_chain)-1}")
            for broken in ma_broken:
                print(f"  ❌ 未達標: {broken}")
        ma_vals = " | ".join([f"{n}:{v:.2f}" for n, v in ma_chain])
        print(f"  📊 {ma_vals}")

    # U/D Volume Ratio (近 50 日)
    ud_ratio = calculate_ud_volume_ratio(data, lookback=50)

    # VCP 波動率計算
    data['Volatility'] = ((data['High'] - data['Low']) / data['Close']) * 100
    data['Volatility'] = data['Volatility'].replace([np.inf, -np.inf], np.nan).fillna(0)

    last_20_days_volatility = data['Volatility'].iloc[-20:].dropna()

    if len(last_20_days_volatility) < 2:
        if not silent: print("過去 20 個交易日數據不足以分析 VCP 型態。")
        return None

    T_count = 0
    contraction_points = []

    for i in range(1, len(last_20_days_volatility)):
        if last_20_days_volatility.iloc[i] < last_20_days_volatility.iloc[i-1]:
            T_count += 1
            contraction_points.append((last_20_days_volatility.index[i], last_20_days_volatility.iloc[i]))

    current_volatility_percentage = last_20_days_volatility.iloc[-1]

    # VDU：最後一次收縮日成交量 < 20MA 的 40%，且收盤必須在當日區間的上半段
    # 確保縮量是在「撐住」而非「陰跌」
    is_vdu = False
    vdu_vol_ratio = None
    vdu_close_position = None  # 收盤位置 (0=底部, 1=頂部)
    if contraction_points:
        last_contraction_date, _ = contraction_points[-1]
        if last_contraction_date in data.index:
            last_vol      = data['Volume'].loc[last_contraction_date]
            last_vol_20ma = data['Vol_20_MA'].loc[last_contraction_date]
            last_close    = data['Close'].loc[last_contraction_date]
            last_high     = data['High'].loc[last_contraction_date]
            last_low      = data['Low'].loc[last_contraction_date]
            for v in [last_vol, last_vol_20ma, last_close, last_high, last_low]:
                if hasattr(v, "item"): v = v.item()
            if hasattr(last_vol, "item"):      last_vol = last_vol.item()
            if hasattr(last_vol_20ma, "item"): last_vol_20ma = last_vol_20ma.item()
            if hasattr(last_close, "item"):    last_close = last_close.item()
            if hasattr(last_high, "item"):     last_high = last_high.item()
            if hasattr(last_low, "item"):      last_low = last_low.item()
            if not pd.isna(last_vol) and not pd.isna(last_vol_20ma) and last_vol_20ma > 0:
                vdu_vol_ratio = last_vol / last_vol_20ma
                day_range = last_high - last_low
                # 收盤位置：0 = 日低點，1 = 日高點
                if day_range > 0:
                    vdu_close_position = (last_close - last_low) / day_range
                else:
                    vdu_close_position = 0.5  # 無實體K棒視為中性
                # 窒息量標準：成交量 < 40% 且收盤在區間上半段 (≥ 50%)
                close_in_upper = vdu_close_position >= 0.5
                if vdu_vol_ratio < 0.40 and close_in_upper:
                    is_vdu = True


    recent_pullbacks, pullbacks_decreasing = calculate_recent_pullbacks(data)

    if not silent:
        print(f"\nVCP 型態偵測 (過去 {len(last_20_days_volatility)} 個交易日):")
        print(f"  收縮次數 (T): {T_count}")
        print(f"  目前的波動百分比: {current_volatility_percentage:.2f}%")
        print(f"  U/D Volume Ratio (近50日): {ud_ratio:.2f}")
        print(f"  VDU 量比: {f'{vdu_vol_ratio:.2f}' if vdu_vol_ratio is not None else '無資料'} ({'✅ 窒息量' if is_vdu else '❌ 量能未枯竭'})")

        if T_count > 0:
            if len(contraction_points) >= 3:
                print("  最近三波波動收縮比例 (由最舊到最新): ", end="")
                last_three_contractions_values = [f"{v[1]:.2f}%" for v in contraction_points[-3:]]
                print(" -> ".join(last_three_contractions_values))
            elif len(contraction_points) > 0:
                print(f"  已檢測到 {len(contraction_points)} 波波動收縮。")
                print("  所有波動收縮比例 (由最舊到最新): ", end="")
                print(" -> ".join([f"{v[1]:.2f}%" for v in contraction_points]))
        else:
            print("  未檢測到波動收縮階段。")

        # 分級提示 (更新為 2.5% 臨界點)
        if current_volatility_percentage < 2.5:
            print("\n" + "🔥" * 8)
            print("VCP 緊縮臨界點！洗盤已極度乾淨，隨時準備引爆！")
            print("🔥" * 8 + "\n")
        elif current_volatility_percentage < 7.0:
            print("  ✨ 高度關注：VCP 緊縮程度佳 (< 7%)")

    # ===========================================================
    # 突破偵測：Pivot Point = VCP 盤整區間最高點 (Recent 14 日)
    # ===========================================================
    vcp_window = 14
    pivot_point = data['High'].iloc[-vcp_window:].max().item()

    today_vol = data['Volume'].iloc[-1].item()
    breakout_vol_ratio = today_vol / latest_vol_20_ma if latest_vol_20_ma > 0 else 0

    # 突破判定：收盤 > Pivot 且 量能 >= 200%
    is_breakout = (latest_close > pivot_point) and (breakout_vol_ratio >= 2.0)
    # 假突破：盤中曾突破 (最高價 > Pivot) 但收盤跌回區間內
    is_false_breakout = (data['High'].iloc[-1].item() > pivot_point) and (latest_close <= pivot_point)

    if not silent:
        print(f"\n  🎯 Pivot Point (VCP 盤整最高點): {pivot_point:.2f}")
        if is_breakout:
            print(f"  🚀 【已突破！】放量 {breakout_vol_ratio*100:.0f}%，收盤 {latest_close:.2f} 超越 Pivot {pivot_point:.2f}")
        elif is_false_breakout:
            print(f"  ⚠️  【假突破！】盤中曾衝破 Pivot，但收盤跌回 {latest_close:.2f}，需觀察")
        else:
            vol_needed = latest_vol_20_ma * 2
            print(f"  ⏳ 尚未突破，條件：收盤 > {pivot_point:.2f} 且成交量 ≥ {vol_needed:,.0f} 張 (20日均量×200%，今日僅達 {breakout_vol_ratio*100:.0f}%)")




    results = {
        "ticker": ticker_symbol,
        "is_vdu": is_vdu,
        "vdu_vol_ratio": vdu_vol_ratio,
        "vdu_close_position": vdu_close_position,
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
        "turnover_50_ma": latest_turnover_50_ma,
        "ud_ratio": ud_ratio,
        # 突破訊號
        "pivot_point": pivot_point,
        "is_breakout": is_breakout,
        "is_false_breakout": is_false_breakout,
        "breakout_vol_ratio": breakout_vol_ratio,
    }

    return results


if __name__ == "__main__":
    while True:
        ticker = input("請輸入股票代碼（輸入 q 結束）：").upper()
        if ticker == 'Q':
            break
        analyze_vcp(ticker, silent=False)
