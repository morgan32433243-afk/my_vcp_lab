import customtkinter as ctk
from tkinter import filedialog
import threading
import sys
import time
import os
import queue
import tkinter.messagebox

# 引入您已經完成的 batch_vcp_scanner 與其函式
from batch_vcp_scanner import batch_scan_vcp, get_stock_list

# 設定外觀與顏色主題
ctk.set_appearance_mode("System")  
ctk.set_default_color_theme("blue")  

# 自訂一個類別來攔截 sys.stdout (也就是 print 的輸出)
class TextRedirector(object):
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, str):
        # 因為會在不同的 Thread 呼叫，CTkTextbox 原生支援多執行緒安全插入，但為防萬一我們直接 insert
        self.widget.configure(state="normal")
        self.widget.insert("end", str)
        self.widget.see("end")
        self.widget.configure(state="disabled")

    def flush(self):
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 設定視窗
        self.title("VCP 掃描分析工具 (全市場自動版)")
        self.geometry("650x650")
        
        # 標題標籤
        self.title_label = ctk.CTkLabel(self, text="📊 VCP 批次掃描程式", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.pack(pady=(20, 10))
        
        # 設定區塊
        self.settings_frame = ctk.CTkFrame(self)
        self.settings_frame.pack(pady=10, padx=20, fill="x")

        # 股票代碼輸入框 (留空代表全市場)
        self.ticker_label = ctk.CTkLabel(self.settings_frame, text="指定股票代碼 (選填，逗號分隔，留空則掃描全市場):")
        self.ticker_label.pack(anchor="w", padx=10, pady=(10, 0))
        self.ticker_entry = ctk.CTkEntry(self.settings_frame, placeholder_text="例如: 2330.TW, 2603.TW")
        self.ticker_entry.pack(fill="x", padx=10, pady=(5, 10))

        # 營收過濾開關
        self.revenue_switch_var = ctk.BooleanVar(value=False)
        self.revenue_switch = ctk.CTkSwitch(self.settings_frame, text="✅ 開啟營收年增濾網 (>10%)", variable=self.revenue_switch_var)
        self.revenue_switch.pack(anchor="w", padx=10, pady=(0, 10))
        
        # 輸出資料夾選取區塊
        self.dir_frame = ctk.CTkFrame(self)
        # 取得使用者「下載」資料夾路徑作為預設，避免 Mac .app 在根目錄執行造成的 Read-only 錯誤
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        default_dir = os.path.join(downloads_dir, "vcp_plots_batch")
        self.dir_path_var = ctk.StringVar(value=default_dir)
        
        self.dir_label = ctk.CTkLabel(self.dir_frame, text="圖片儲存資料夾:", width=120, anchor="w")
        self.dir_label.pack(side="left", padx=(10, 0), pady=10)

        self.dir_path_display = ctk.CTkLabel(self.dir_frame, textvariable=self.dir_path_var, width=280, anchor="w", text_color="gray")
        self.dir_path_display.pack(side="left", padx=(5, 10), pady=10)
        
        self.browse_btn = ctk.CTkButton(self.dir_frame, text="更改路徑", command=self.browse_directory, width=80)
        self.browse_btn.pack(side="right", padx=(0, 10), pady=10)
        
        # 執行按鈕
        self.run_btn = ctk.CTkButton(self, text="▶ 開始自動掃描", command=self.start_core_logic, font=ctk.CTkFont(size=15, weight="bold"), height=45)
        self.run_btn.pack(pady=15)
        
        # 狀態顯示 TextBox (唯讀)
        self.status_textbox = ctk.CTkTextbox(self, state="disabled", wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.status_textbox.pack(pady=(5, 20), padx=20, fill="both", expand=True)

        # 導向標準輸出至 TextBox
        sys.stdout = TextRedirector(self.status_textbox)

    def browse_directory(self):
        # 讓使用者可以手動選取資料夾
        dir_name = filedialog.askdirectory(title="請選擇儲存 VCP 圖片的資料夾")
        if dir_name:
            self.dir_path_var.set(dir_name)
            self.dir_path_display.configure(text_color="white")
            print(f"已更改儲存路徑：{dir_name}\n")

    def core_logic_thread(self, tickers_text, enable_rev, output_dir):
        """將分析過程放進背景執行緒，以免畫面卡死"""
        self.run_btn.configure(state="disabled", text="掃描進行中...")
        self.browse_btn.configure(state="disabled")
        
        try:
            print("====================================")
            print("🚀 自動掃描任務開始")
            print("====================================")

            # 解析股票代碼
            if tickers_text.strip():
                # 使用者有輸入特定代碼
                tickers = [t.strip().upper() for t in tickers_text.split(",") if t.strip()]
                print(f"模式：掃描指定標的共 {len(tickers)} 檔")
            else:
                # 留空則自動下載全市場清單
                print("模式：全市場自動掃描，正在下載股票清單...")
                tickers = get_stock_list()
                print(f"全市場清單下載完成，共 {len(tickers)} 檔")

            # 確保資料夾存在
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            # 準備線程安全的回調函數，供背景攔截詢問
            def gui_ask_callback(prompt_text, count):
                q = queue.Queue()
                def ask_main_thread():
                    # 呼叫原生的 tkinter messagebox (確保在主執行緒彈出)
                    res = tkinter.messagebox.askyesno("查看清單", f"是否想在文字區塊印出【{prompt_text}】共 {count} 檔的詳細清單？")
                    q.put(res)
                
                # 委託給主執行緒執行彈窗
                self.after(0, ask_main_thread)
                # 阻塞背景執行緒直到使用者點擊 Yes/No
                return q.get()

            # 呼叫核心邏輯
            # 這裡 batch_scan_vcp 會自動把進度透過 print 印出，我們已經攔截 print 到 GUI 的文字框了
            batch_scan_vcp(tickers_to_scan=tickers, 
                           enable_revenue_filter=enable_rev, 
                           output_dir=output_dir,
                           interactive=True,
                           ask_callback=gui_ask_callback)
            
            print("\n✅ 所有批次掃描已完成！")
            print(f"圖片已儲存至：{output_dir}")

        except Exception as e:
            print(f"\n❌ 發生未預期錯誤: {e}")
        finally:
            self.run_btn.configure(state="normal", text="▶ 開始自動掃描")
            self.browse_btn.configure(state="normal")

    def start_core_logic(self):
        # 取得設定值
        tickers_text = self.ticker_entry.get()
        enable_rev = self.revenue_switch_var.get()
        output_dir = self.dir_path_var.get()
            
        # 使用 Thread 避免卡死 GUI 介面
        thread = threading.Thread(target=self.core_logic_thread, args=(tickers_text, enable_rev, output_dir))
        thread.daemon = True
        thread.start()

if __name__ == "__main__":
    app = App()
    app.mainloop()
