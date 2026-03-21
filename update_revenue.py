import os
import time
import requests
import pandas as pd
from datetime import datetime
from batch_vcp_scanner import get_stock_list

def get_single_revenue_yoy(ticker_symbol):
    """
    依賴 FinMind API 單獨拉取個股營收資料
    """
    stock_id = ticker_symbol.split('.')[0]
    # 取約一年半，確保有最新月份與去年同月份
    from datetime import date, timedelta
    start_date = (date.today() - timedelta(days=450)).strftime('%Y-%m-%d')
    
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockMonthRevenue",
        "data_id": stock_id,
        "start_date": start_date
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        res_json = response.json()
        
        msg = res_json.get('msg', '')
        if 'limit' in str(msg).lower():
            return "LIMIT_EXCEEDED"
            
        data = res_json.get('data', [])
        if not data:
            return None
            
        if len(data) < 13:
            return None
        
        latest_revenue = data[-1]
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
                return ((rev_now - rev_then) / rev_then) * 100
        return None
            
    except Exception as e:
        # FinMind 402 Limit Exceeded 等錯誤皆會觸發 None
        return None


def build_revenue_csv():
    print("====================================")
    print("開始更新全台股營收資料 (taiwan_revenue.csv)")
    print("注意: FinMind 免費版具備 300次/小時 限制，此程式會自動儲存已達成的進度！")
    print("====================================\n")
    
    csv_file = "taiwan_revenue.csv"
    existing_data = {}
    
    if os.path.exists(csv_file):
        file_mtime = os.path.getmtime(csv_file)
        file_month = datetime.fromtimestamp(file_mtime).month
        current_month = datetime.now().month
        
        if file_month != current_month:
            print(f"[*] 發現非當月的營收快取檔，為確保資料最新，已自動為您清除並準備重新抓取全新月份資料。")
            os.remove(csv_file)
        else:
            try:
                df_exist = pd.read_csv(csv_file)
                for idx, row in df_exist.iterrows():
                    existing_data[str(row['ticker'])] = row['revenue_yoy']
                print(f"[*] 讀取到 {len(existing_data)} 筆既有的當月營收資料，準備接續抓取。")
            except Exception as e:
                print("[!] 無法讀取現有 CSV 或格式錯誤，將重新抓取。")
            
    tickers, _, _ = get_stock_list()
    print(f"[*] 共計需掃描 {len(tickers)} 檔股票清單 (包含 ETF)")


    results = []
    # 將舊有資料回填陣列 (順便過濾掉這一次沒出現的下市股票)
    for t in tickers:
        if t in existing_data:
            results.append({"ticker": t, "revenue_yoy": existing_data[t]})

    count = 0
    save_threshold = 20 # 每 20 筆儲存一次以防中斷

    for t in tickers:
        if t in existing_data:
            continue
            
        # ETF 跳過不抓營收
        if t.startswith("00"):
            results.append({"ticker": t, "revenue_yoy": 0.0})
            existing_data[t] = 0.0
            continue
            
        print(f"正在抓取 {t} 的營收資料...", end=" ", flush=True)
        
        while True:
            yoy = get_single_revenue_yoy(t)
            
            if yoy == "LIMIT_EXCEEDED":
                pd.DataFrame(results).to_csv(csv_file, index=False)
                print("\n[!] 遇到 FinMind 300次/小時 API 上限！自動休眠 61 分鐘後繼續 (請保持此程式開啟)...")
                time.sleep(3660) # 61 分鐘
                print(f"[*] 喚醒，重試抓取 {t} ...", end=" ", flush=True)
            elif yoy is not None:
                results.append({"ticker": t, "revenue_yoy": yoy})
                existing_data[t] = yoy
                print(f"年增率: {yoy:.2f}%")
                break
            else:
                # 寫入 nan 以利後續程式辨識為無資料，而不是 0.0 (因為有可能真的是 0.0)
                results.append({"ticker": t, "revenue_yoy": float('nan')})
                existing_data[t] = float('nan')
                print("無效資料或數據不足。")
                break
            
        count += 1
        if count % save_threshold == 0:
            pd.DataFrame(results).to_csv(csv_file, index=False)
            print(f" > 進度已快取儲存至 {csv_file}")
            
        time.sleep(0.5) # 間隔防擋
        
    # 最後確保儲存
    pd.DataFrame(results).to_csv(csv_file, index=False)
    print(f"\n✅ 營收資料更新完成，共 {len(results)} 筆紀錄，已寫入 {csv_file}")

if __name__ == "__main__":
    build_revenue_csv()
