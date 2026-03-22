# 🚀 Taiwan Stock VCP Scanner (台股全市場波動收縮掃描器)

這是一個基於 **Mark Minervini** 的傳奇選股策略 —— **VCP (Volatility Contraction Pattern)** 所開發的自動化掃描系統。本工具旨在從台股全市場中，精選出具備強勢趨勢、籌碼安定且即將爆發的潛力標的。

## 🌟 核心特色

- **全市場掃描**：自動抓取證交所與櫃買中心清單，涵蓋超過 2,200 檔個股與 ETF。
- **VCP 波動收縮辨識**：精確計算價格波動率（Volatility %），尋找臨界點（Pivot Point）。
- **進階 RS Rating (相對強度)**：
  - 採用 1 年期加權計算，並將個股與 **加權指數 (^TWII)** 進行 3M/6M/12M 績效對照。
  - 確保標的具備戰勝大盤的「Alpha」超額報酬。
- **基本面 + 籌碼面雙重過濾**：整合 FinMind API，篩選營收 YoY > 20%、EPS 成長且法人淨買超的標的。
- **TradingView 整合**：掃描完成後自動生成 `TradingView_VCP_Watchlist.txt`，一鍵匯入觀察清單。

## 🛠️ 選股邏輯 (Scanner Logic)

本系統採漏斗式篩選：
1. **大盤環境判定**：僅在加權指數高於 200MA 且均線多頭排列時執行。
2. **趨勢模板 (Trend Template)**：篩選股價站上均線、距離年高點 25% 以內的趨勢股。
3. **流動性優化**：要求長期成交金額 > 3,000 萬，同時允許突破前的「量縮窒息 (VDU)」特徵。
4. **VDU (Volume Dry-Up)**：核心收縮區間量能需萎縮至 40% 以下，代表賣壓竭盡。
5. **綜合評分**：根據 RS 分數 (40%) + EPS 成長 (30%) + VCP 緊縮度 (30%) 進行排序。

## 🚀 快速開始

### 環境需求
- Python 3.10+
- 必要的函式庫：`pandas`, `yfinance`, `requests`, `numpy`

### 執行方式
1. 將專案複製 (Clone) 到本地端。
2. 執行主程式：
   ```bash
   python 全市場掃描器.py