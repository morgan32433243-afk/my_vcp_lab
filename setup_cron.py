import os
import sys

def setup_mac_cron():
    # 取得絕對路徑
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "update_revenue.py")
    python_path = sys.executable
    log_path = os.path.join(current_dir, "cron_revenue.log")
    
    # 設定排程時間：每月 11 號凌晨 1:00 執行
    # 由於每月 10 號為上市櫃公司營收公布截止日，11 號抓取會是最完整的。
    cron_time = "0 1 11 * *"
    cron_command = f"{cron_time} cd {current_dir} && {python_path} {script_path} >> {log_path} 2>&1"
    
    print("====================================")
    print("  準備將營收自動更新腳本加入背景排程  ")
    print("====================================")
    print(f"欲加入的指令:\n{cron_command}\n")
    
    # 讀取現有的 crontab
    os.system("crontab -l > mycron.tmp 2>/dev/null")
    
    with open("mycron.tmp", "r") as f:
        existing = f.read()
        
    if "update_revenue.py" in existing:
        print("[!] 系統中已經有設定過 update_revenue.py 的排程，為避免重複執行，本次不寫入。")
        print("若要修改，請在終端機輸入 `crontab -e` 手動調整。")
    else:
        with open("mycron.tmp", "a") as f:
            f.write(f"\n# 自動更新台股 VCP 營收資料 (每月 11 日凌晨 1 點)\n")
            f.write(f"{cron_command}\n")
            
        os.system("crontab mycron.tmp")
        print("✅ 成功！已將自動更新排程加入到您的 Mac 系統中。")
        print("下一次自動喚醒時間為：下個月的 11 日凌晨 1:00")
        print(f"執行日誌將會輸出到：{log_path}")
        
    if os.path.exists("mycron.tmp"):
        os.remove("mycron.tmp")

if __name__ == "__main__":
    setup_mac_cron()
