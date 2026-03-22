import os
import time
import requests
import urllib3
import pandas as pd

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_twse_revenue():
    print("下載上市營收資料 (TWSE)...")
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    try:
        resp = requests.get(url, timeout=15, verify=False)
        return resp.json()
    except Exception as e:
        print(f"上市營收下載失敗: {e}")
        return []

def fetch_otc_revenue():
    print("下載上櫃營收資料 (OTC)...")
    url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
    try:
        resp = requests.get(url, timeout=15, verify=False)
        return resp.json()
    except Exception as e:
        print(f"上櫃營收下載失敗: {e}")
        return []

def build_fast_revenue_csv():
    print("====================================")
    print("🚀 極速快取：政府公開資訊大全大掃描")
    print("====================================\n")
    
    twse_data = fetch_twse_revenue()
    otc_data = fetch_otc_revenue()
    
    all_records = []
    
    for item in twse_data:
        ticker = item.get("公司代號", "") + ".TW"
        yoy_str = item.get("營業收入-去年同月增減(%)", "")
        try:
            yoy = float(yoy_str) if yoy_str != "出表日期" else float('nan')
        except ValueError:
            yoy = float('nan')
        
        all_records.append({"ticker": ticker, "revenue_yoy": yoy})
        
    for item in otc_data:
        ticker = item.get("公司代號", "") + ".TWO"
        yoy_str = item.get("營業收入-去年同月增減(%)", "")
        try:
            yoy = float(yoy_str)
        except ValueError:
            yoy = float('nan')
            
        all_records.append({"ticker": ticker, "revenue_yoy": yoy})
        
    if not all_records:
        print("❌ 下載失敗，未取得任何資料")
        return
        
    df = pd.DataFrame(all_records)
    csv_file = "taiwan_revenue.csv"
    df.to_csv(csv_file, index=False)
    
    print(f"\n✅ 極速營收資料更新完成！共取得 {len(all_records)} 筆紀錄。")
    print(f"📁 已寫入 {csv_file}，掃描程式現在可以瞬間讀取了！")

if __name__ == "__main__":
    start = time.time()
    build_fast_revenue_csv()
    print(f"⏱️ 總耗時: {time.time() - start:.2f} 秒")
