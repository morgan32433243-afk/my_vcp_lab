import yfinance as yf
import pandas as pd

tkr = yf.Ticker("2330.TW")

try:
    print("--- 2330.TW Financials ---")
    print(tkr.financials)
    print("\n--- 2330.TW Quarterly Financials ---")
    print(tkr.quarterly_financials)
except Exception as e:
    print(f"Error: {e}")
