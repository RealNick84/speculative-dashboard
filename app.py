import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import pycoingecko as cg
import pandas_ta as ta
import requests
from datetime import datetime
import time
from typing import Dict

st.set_page_config(page_title="Speculative Alpha", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .main-header { font-size: 2.5rem; font-weight: 700; color: #00ff9d; }
    .metric-card { background-color: #1a1f2e; border-radius: 12px; padding: 16px; }
</style>
""", unsafe_allow_html=True)

# Assets
ASSETS = {
    "stocks": ["IOVA", "NVTS", "SMCI", "BBAI", "RGTI", "QUBT", "ASST"],
    "crypto": ["XRP", "ONDO", "WLFI", "FIL", "ZORA", "DOGE", "SOL"]
}

COINGECKO_IDS = {
    "XRP": "xrp", "ONDO": "ondo-finance", "WLFI": "world-liberty-financial",
    "FIL": "filecoin", "ZORA": "zora", "DOGE": "dogecoin", "SOL": "solana"
}

def get_asset_info(ticker, is_crypto=False):
    if is_crypto:
        try:
            coin = cg.CoinGeckoAPI()
            data = coin.get_coin_by_id(COINGECKO_IDS.get(ticker, ticker.lower()))
            return {"name": data.get("name", ticker), "symbol": ticker, "is_crypto": True}
        except:
            return {"name": ticker, "symbol": ticker, "is_crypto": True}
    else:
        try:
            info = yf.Ticker(ticker).info
            return {"name": info.get("longName", ticker), "symbol": ticker, "is_crypto": False}
        except:
            return {"name": ticker, "symbol": ticker, "is_crypto": False}

# Main App
def main():
    st.title("🚀 Speculative Alpha Dashboard")
    st.caption("High-growth assets • Real-time • May 2026")

    ticker = st.selectbox("Select Asset", ASSETS["stocks"] + ASSETS["crypto"])
    
    is_crypto = ticker in ASSETS["crypto"]
    info = get_asset_info(ticker, is_crypto)
    
    st.subheader(f"{ticker} - {info['name']}")
    st.success("App is running! Add more features from the original code as needed.")

if __name__ == "__main__":
    main()
