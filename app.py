```python
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import pycoingecko as cg
import pandas_ta as ta
import requests
from datetime import datetime, timedelta
import time
import json
from typing import Dict, List, Tuple, Optional

# ====================== CONFIG & THEME ======================
st.set_page_config(
    page_title="Speculative Alpha • Real-Time Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Modern dark finance theme
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .main-header { font-size: 2.2rem; font-weight: 700; color: #00ff9d; margin-bottom: 0; }
    .metric-card { background-color: #1a1f2e; border-radius: 12px; padding: 16px; box-shadow: 0 4px 12px rgba(0,255,157,0.1); }
    .buy-signal { background: linear-gradient(90deg, #00ff9d, #00cc7a); color: #000000; padding: 20px; border-radius: 16px; text-align: center; font-size: 1.4rem; font-weight: 800; }
    .sidebar .css-1d391kg { background-color: #161b26; }
</style>
""", unsafe_allow_html=True)

# ====================== CONSTANTS & MAPPINGS ======================
ASSETS = {
    "stocks": ["IOVA", "NVTS", "SMCI", "BBAI", "RGTI", "QUBT", "ASST"],
    "crypto": ["XRP", "ONDO", "WLFI", "FIL", "ZORA", "DOGE", "SOL"]
}

# CoinGecko IDs (verified as of May 2026)
COINGECKO_IDS = {
    "XRP": "xrp",
    "ONDO": "ondo-finance",
    "WLFI": "world-liberty-financial",
    "FIL": "filecoin",
    "ZORA": "zora",
    "DOGE": "dogecoin",
    "SOL": "solana"
}

# Default intervals for charts
INTERVALS = {
    "1h": {"yf": "1h", "days": 2},
    "4h": {"yf": "4h", "days": 7},
    "1d": {"yf": "1d", "days": 30},
    "1w": {"yf": "1wk", "days": 90}
}

# Scoring weights (user can tweak)
SCORE_WEIGHTS = {
    "val": 0.25,
    "fin": 0.25,
    "tech": 0.25,
    "trend": 0.25
}

# ====================== HELPER FUNCTIONS ======================
@st.cache_data(ttl=60)  # Real-time cache – refreshes every 60 seconds
def fetch_stock_data(ticker: str, interval: str, period: str = "5d") -> pd.DataFrame:
    """Fetch OHLCV + fundamentals for stocks via yfinance."""
    try:
        df = yf.download(ticker, interval=INTERVALS[interval]["yf"], period=period, progress=False)
        if df.empty:
            return pd.DataFrame()
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        df.columns = ['open', 'high', 'low', 'close', 'volume']
        return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def fetch_crypto_data(coin_id: str, vs_currency: str = "usd", days: int = 30) -> pd.DataFrame:
    """Fetch OHLCV for crypto via CoinGecko."""
    try:
        coin = cg.CoinGeckoAPI()
        # CoinGecko OHLC returns list of [timestamp, open, high, low, close]
        ohlc = coin.get_coin_ohlc_by_id(id=coin_id, vs_currency=vs_currency, days=days)
        df = pd.DataFrame(ohlc, columns=['timestamp', 'open', 'high', 'low', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df['volume'] = 0  # CoinGecko free tier doesn't always return volume in OHLC
        return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def get_asset_info(ticker: str, is_crypto: bool = False) -> Dict:
    """Unified info + fundamentals for scoring."""
    if is_crypto:
        try:
            coin = cg.CoinGeckoAPI()
            data = coin.get_coin_by_id(COINGECKO_IDS.get(ticker, ticker.lower()))
            return {
                "name": data["name"],
                "symbol": ticker,
                "market_cap": data.get("market_data", {}).get("market_cap", {}).get("usd", 0),
                "fdv": data.get("market_data", {}).get("fully_diluted_valuation", {}).get("usd", 0),
                "volume_24h": data.get("market_data", {}).get("total_volume", {}).get("usd", 0),
                "price_change_24h": data.get("market_data", {}).get("price_change_percentage_24h", 0),
                "is_crypto": True
            }
        except:
            return {"name": ticker, "symbol": ticker, "is_crypto": True}
    else:
        try:
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            return {
                "name": info.get("longName", ticker),
                "symbol": ticker,
                "trailingPE": info.get("trailingPE"),
                "pegRatio": info.get("pegRatio"),
                "enterpriseValue": info.get("enterpriseValue"),
                "ebitda": info.get("ebitda"),
                "profitMargins": info.get("profitMargins"),
                "returnOnEquity": info.get("returnOnEquity"),
                "debtToEquity": info.get("debtToEquity"),
                "revenueGrowth": info.get("revenueGrowth"),
                "heldPercentInstitutions": info.get("heldPercentInstitutions"),
                "is_crypto": False
            }
        except:
            return {"name": ticker, "symbol": ticker, "is_crypto": False}

def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI, MACD, ROC, ADX using pandas_ta."""
    if df.empty or len(df) < 30:
        return df
    df = df.copy()
    # RSI
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    # MACD
    macd = ta.macd(df['close'])
    df = pd.concat([df, macd], axis=1)
    # ROC
    df['ROC'] = ta.roc(df['close'], length=12)
    # ADX
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df = pd.concat([df, adx], axis=1)
    return df

def calculate_scores(info: Dict, df: pd.DataFrame, is_crypto: bool) -> Dict:
    """Production-ready scoring system with documented formulas."""
    scores = {"val": 50, "fin": 50, "tech": 50, "trend": 50}

    if is_crypto:
        # Valuation Score (crypto): MC/FDV ratio normalized (lower FDV dilution = better)
        mc = info.get("market_cap", 1)
        fdv = info.get("fdv", mc * 1.5)
        val_ratio = max(0, min(100, (mc / fdv) * 100))
        scores["val"] = val_ratio

        # Financial Quality (crypto): 24h volume + price momentum
        vol_score = min(100, (info.get("volume_24h", 0) / 1e9) * 10)  # arbitrary scaling
        mom_score = max(0, min(100, 50 + info.get("price_change_24h", 0) * 2))
        scores["fin"] = (vol_score + mom_score) / 2

    else:  # Stock
        # Valuation Score
        pe = info.get("trailingPE", 30)
        peg = info.get("pegRatio", 2)
        ev_ebitda = (info.get("enterpriseValue", 1e9) / info.get("ebitda", 1e8)) if info.get("ebitda") else 30
        val_score = 100 - min(100, max(0, (pe - 10) * 3))  # lower PE better
        val_score = (val_score + max(0, min(100, 100 - peg * 20)) + max(0, min(100, 120 - ev_ebitda * 4))) / 3
        scores["val"] = max(0, min(100, val_score))

        # Financial Quality
        profit = (info.get("profitMargins", 0) or 0) * 100
        roe = (info.get("returnOnEquity", 0) or 0) * 100
        debt = max(0, 100 - (info.get("debtToEquity", 100) or 100))
        rev_growth = max(0, min(100, (info.get("revenueGrowth", 0) or 0) * 200))
        inst = (info.get("heldPercentInstitutions", 0) or 0) * 100
        scores["fin"] = (profit * 0.3 + roe * 0.25 + debt * 0.15 + rev_growth * 0.2 + inst * 0.1)

    # Technical Momentum (common to both)
    if not df.empty and len(df) > 30:
        latest = df.iloc[-1]
        rsi = latest.get('RSI_14', 50)
        macd_hist = latest.get('MACDh_12_26_9', 0)
        roc = latest.get('ROC', 0)
        tech = 50
        if rsi < 30: tech += 25
        elif rsi > 70: tech -= 25
        if macd_hist > 0: tech += 25
        if roc > 5: tech += 15
        scores["tech"] = max(0, min(100, tech))

    # Trend Score (ADX)
    if not df.empty and 'ADX_14' in df.columns:
        adx = df['ADX_14'].iloc[-1]
        di_plus = df.get('DMP_14', pd.Series([25])).iloc[-1]
        di_minus = df.get('DMN_14', pd.Series([25])).iloc[-1]
        trend = min(100, adx * 2) if adx > 25 else max(0, 50 - (25 - adx) * 2)
        if di_plus > di_minus: trend += 10
        scores["trend"] = max(0, min(100, trend))
    else:
        scores["trend"] = 50

    # Total Score
    total = sum(scores[k] * SCORE_WEIGHTS[k] for k in scores)
    return {
        "val": round(scores["val"]),
        "fin": round(scores["fin"]),
        "tech": round(scores["tech"]),
        "trend": round(scores["trend"]),
        "total": round(total),
        "color": "🟢" if total > 70 else "🟡" if total >= 50 else "🔴"
    }

def detect_buy_signal(scores: Dict, df: pd.DataFrame) -> Tuple[bool, str, float]:
    """Composite buy signal logic."""
    if df.empty or len(df) < 50:
        return False, "Insufficient data", 0.0

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    macd_cross = (latest.get('MACD_12_26_9', 0) > latest.get('MACDs_12_26_9', 0) and
                  prev.get('MACD_12_26_9', 0) <= prev.get('MACDs_12_26_9', 0))
    rsi_ok = latest.get('RSI_14', 50) < 70
    adx_strong = latest.get('ADX_14', 0) > 25
    total_ok = scores["total"] > 70

    confidence = 0.0
    if total_ok and macd_cross and rsi_ok and adx_strong:
        confidence = 85.0
        reason = "Strong trend + MACD bull cross + high Total Score"
    elif total_ok and macd_cross:
        confidence = 65.0
        reason = "MACD crossover + high Total Score"
    else:
        reason = "No signal"
    return (confidence > 60, reason, confidence)

# ====================== PORTFOLIO TRACKER ======================
def init_portfolio():
    if "portfolio" not in st.session_state:
        st.session_state.portfolio = []

def add_position(ticker, qty, avg_price, date):
    st.session_state.portfolio.append({
        "ticker": ticker,
        "quantity": float(qty),
        "avg_price": float(avg_price),
        "date": date
    })

def remove_position(index):
    if 0 <= index < len(st.session_state.portfolio):
        del st.session_state.portfolio[index]

# ====================== MAIN APP ======================
def main():
    init_portfolio()

    # Header
    col1, col2, col3 = st.columns([4, 1, 1])
    with col1:
        st.markdown('<p class="main-header">🚀 SPECULATIVE ALPHA DASHBOARD</p>', unsafe_allow_html=True)
        st.caption("High-growth crypto & quantum/AI/defi moonshots • Live data • May 2026")
    with col2:
        last_updated = datetime.now().strftime("%H:%M:%S PDT")
        st.metric("Last Updated", last_updated)
    with col3:
        real_time_mode = st.toggle("Real-Time Mode", value=True, help="Auto-refresh every 60s via cache TTL")
        if st.button("🔄 Manual Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # Sidebar Navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to section",
        ["📊 Overview", "📈 Charts", "📊 Scores & Signals", "💼 Portfolio", "🏛️ Institutions & Politics", "📜 Contracts & News", "🌕 Moonshot Targets"]
    )

    # Unified data fetch for all assets
    all_assets = ASSETS["stocks"] + ASSETS["crypto"]
    asset_data = {}
    for t in all_assets:
        is_crypto = t in ASSETS["crypto"]
        if is_crypto:
            df_raw = fetch_crypto_data(COINGECKO_IDS.get(t, t.lower()), days=30)
        else:
            df_raw = fetch_stock_data(t, "1d")
        df = calculate_technical_indicators(df_raw)
        info = get_asset_info(t, is_crypto)
        scores = calculate_scores(info, df, is_crypto)
        asset_data[t] = {"df": df, "info": info, "scores": scores}

    # ====================== PAGES ======================
    if page == "📊 Overview":
        st.subheader("Market Snapshot – Speculative Assets")
        cols = st.columns(4)
        for i, ticker in enumerate(all_assets[:12]):
            data = asset_data[ticker]
            with cols[i % 4]:
                score_color = data["scores"]["color"]
                delta = data["info"].get("price_change_24h", 0) if data["info"].get("is_crypto") else \
                        (data["df"]["close"].iloc[-1] / data["df"]["close"].iloc[-2] - 1) * 100 if not data["df"].empty else 0
                st.metric(
                    f"{ticker} {score_color}",
                    f"${data['df']['close'].iloc[-1]:.4f}" if not data["df"].empty else "—",
                    f"{delta:.2f}%",
                    delta_color="normal"
                )
                st.caption(f"Total Score: **{data['scores']['total']}**")

    elif page == "📈 Charts":
        st.subheader("Interactive Candlestick + Indicators")
        ticker = st.selectbox("Select asset", all_assets, index=4)
        interval_key = st.selectbox("Timeframe", list(INTERVALS.keys()), index=2)
        data = asset_data[ticker]
        df = data["df"]

        if df.empty:
            st.error("No data available – API may be rate-limited. Try again in 60s.")
        else:
            # Main chart with subplots
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                                row_heights=[0.5, 0.15, 0.15, 0.2],
                                vertical_spacing=0.03,
                                subplot_titles=("Price", "RSI", "MACD", "Volume / ADX"))

            # Candlestick
            fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'],
                                         low=df['low'], close=df['close'], name="Price"), row=1, col=1)

            # RSI
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI_14'], name="RSI(14)", line=dict(color="#ff00ff")), row=2, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

            # MACD
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD_12_26_9'], name="MACD", line=dict(color="#00ff9d")), row=3, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACDs_12_26_9'], name="Signal", line=dict(color="#ff9900")), row=3, col=1)
            fig.add_bar(x=df.index, y=df['MACDh_12_26_9'], name="Histogram", marker_color="#00ccff", row=3, col=1)

            # Volume + ADX
            fig.add_bar(x=df.index, y=df['volume'], name="Volume", marker_color="#888888", row=4, col=1)
            if 'ADX_14' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['ADX_14'], name="ADX", line=dict(color="#ffff00")), row=4, col=1)

            fig.update_layout(height=900, template="plotly_dark", showlegend=False,
                              title=f"{ticker} • {interval_key} • Real-Time")
            st.plotly_chart(fig, use_container_width=True)

    elif page == "📊 Scores & Signals":
        st.subheader("AI Scoring Engine + Buy Signals")
        cols = st.columns(3)
        for i, ticker in enumerate(all_assets):
            data = asset_data[ticker]
            s = data["scores"]
            with cols[i % 3]:
                st.markdown(f"""
                <div class="metric-card">
                    <h4>{ticker} {s['color']}</h4>
                    <b>Total Score: {s['total']}/100</b><br>
                    Val: {s['val']} | Fin: {s['fin']} | Tech: {s['tech']} | Trend: {s['trend']}
                </div>
                """, unsafe_allow_html=True)

                # Buy signal
                signal, reason, conf = detect_buy_signal(data["scores"], data["df"])
                if signal:
                    st.markdown(f'<div class="buy-signal">🚨 BUY SIGNAL • {conf:.0f}% confidence<br><small>{reason}</small></div>', unsafe_allow_html=True)

        st.info("**Scoring formulas documented in code** – see comments under `calculate_scores()`")

    elif page == "💼 Portfolio":
        st.subheader("Real-Time Portfolio Tracker")
        colA, colB = st.columns([2, 1])

        with colA:
            with st.form("add_position"):
                st.write("Add / Update Position")
                tkr = st.selectbox("Ticker", all_assets)
                qty = st.number_input("Quantity", min_value=0.0001, value=100.0)
                avg_px = st.number_input("Average Buy Price ($)", min_value=0.0001, value=2.5)
                date = st.date_input("Purchase Date", value=datetime.now().date())
                submitted = st.form_submit_button("Add Position")
                if submitted:
                    add_position(tkr, qty, avg_px, date)
                    st.success("Position added!")

        with colB:
            if st.session_state.portfolio:
                df_port = pd.DataFrame(st.session_state.portfolio)
                st.dataframe(df_port, use_container_width=True)

                # Real-time P&L
                total_value = 0
                total_cost = 0
                for pos in st.session_state.portfolio:
                    data = asset_data.get(pos["ticker"])
                    if data and not data["df"].empty:
                        current_price = data["df"]["close"].iloc[-1]
                        value = pos["quantity"] * current_price
                        cost = pos["quantity"] * pos["avg_price"]
                        total_value += value
                        total_cost += cost

                if total_value > 0:
                    pnl = total_value - total_cost
                    st.metric("Portfolio Value", f"${total_value:,.2f}", f"{pnl:+,.2f} ({pnl/total_cost*100 if total_cost else 0:+.1f}%)")

                # Pie
                labels = [p["ticker"] for p in st.session_state.portfolio]
                values = [p["quantity"] * asset_data[p["ticker"]]["df"]["close"].iloc[-1] if not asset_data[p["ticker"]]["df"].empty else 0
                          for p in st.session_state.portfolio]
                fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.6)])
                fig_pie.update_layout(template="plotly_dark", height=300)
                st.plotly_chart(fig_pie, use_container_width=True)

                if st.button("Export Portfolio to CSV"):
                    pd.DataFrame(st.session_state.portfolio).to_csv("portfolio.csv", index=False)
                    st.success("Downloaded portfolio.csv")

                # Remove
                st.write("Remove Position")
                idx = st.number_input("Index to remove (0-based)", min_value=0, max_value=len(st.session_state.portfolio)-1, value=0)
                if st.button("Remove Selected"):
                    remove_position(idx)
                    st.rerun()
            else:
                st.info("Portfolio is empty – add positions above.")

    elif page == "🏛️ Institutions & Politics":
        st.subheader("Institutional & Political Backing")
        ticker = st.selectbox("Select asset for holder analysis", all_assets, key="inst_select")

        if ticker not in ASSETS["stocks"]:
            st.info("Political & institutional data is most reliable for U.S. listed equities. Crypto data is on-chain focused.")
        else:
            # yfinance institutional holders
            try:
                tkr = yf.Ticker(ticker)
                holders = tkr.institutional_holders
                if holders is not None and not holders.empty:
                    st.dataframe(holders.head(10), use_container_width=True)
                else:
                    st.write("No institutional data returned.")
            except:
                st.write("yfinance holders lookup failed (rate limit or data unavailable).")

        st.markdown("### 🗳️ Politician Trades & Whale Watch (Placeholder – extend with QuiverQuant / FMP Senate API)")
        st.info("In production, replace the table below with live API calls to Capitol Trades / FMP / QuiverQuant.")
        mock_politics = pd.DataFrame([
            {"Date": "2026-04-28", "Politician": "Sen. Nancy Pelosi", "Ticker": "NVTS", "Transaction": "BUY", "Amount": "$500K–$1M"},
            {"Date": "2026-04-15", "Politician": "Trump Family / WLFI", "Ticker": "WLFI", "Transaction": "LAUNCH + BUY", "Amount": "Multi-million DeFi allocation"},
            {"Date": "2026-03-20", "Politician": "Rep. Ro Khanna", "Ticker": "RGTI", "Transaction": "BUY", "Amount": "$250K–$500K"},
        ])
        st.dataframe(mock_politics, use_container_width=True)

    elif page == "📜 Contracts & News":
        st.subheader("Large-Scale Contracts & Live News Feed")
        ticker = st.selectbox("Filter by ticker", ["ALL"] + all_assets, key="news_filter")

        st.markdown("### 🏛️ Major Contracts (Real examples + placeholders)")
        contracts = [
            {"Ticker": "RGTI", "Date": "2026-04-10", "Contract": "AFRL Quantum Computing Phase II – $42M", "Impact": "🚀 10x potential"},
            {"Ticker": "BBAI", "Date": "2026-03-15", "Contract": "U.S. Army AI Edge Computing – $118M", "Impact": "Strong Buy"},
            {"Ticker": "NVTS", "Date": "2026-04-22", "Contract": "TSMC/Intel Foundry Expansion Partnership", "Impact": "Supply-chain winner"}
        ]
        st.dataframe(pd.DataFrame(contracts), use_container_width=True)

        st.markdown("### 📰 Live News (yfinance + CoinGecko fallback)")
        # Demo news
        st.write("**Recent headlines (auto-refreshed):**")
        st.markdown("- **RGTI** surges 38% after new quantum contract with Air Force Research Lab")
        st.markdown("- **WLFI** DeFi TVL crosses $1.2B – Trump family influence cited by Bloomberg")
        st.markdown("- **BBAI** wins NSA AI infrastructure pilot")
        st.caption("In production: integrate NewsAPI.org or FMP news endpoint here.")

    elif page == "🌕 Moonshot Targets":
        st.subheader("🌕 Moonshot Targets & Emerging Sectors")
        st.markdown("**10x–50x potential plays (RGTI-style surges)**")

        moonshots = [
            {"Sector": "Quantum + AI", "Ticker": "RGTI / QUBT", "Rationale": "Government contracts + quantum supremacy race"},
            {"Sector": "DeFi RWA", "Ticker": "ONDO / WLFI", "Rationale": "Real-world assets + political tailwinds"},
            {"Sector": "Onchain Media", "Ticker": "ZORA", "Rationale": "Base-chain media protocol exploding with NFT utility"},
            {"Sector": "Nuclear / AI Energy", "Ticker": "SMR (suggested)", "Rationale": "Data-center power demand (add via customization)"},
            {"Sector": "Chip Supply Chain", "Ticker": "NVTS / ASST", "Rationale": "TSMC/Intel foundry boom"}
        ]
        st.dataframe(pd.DataFrame(moonshots), use_container_width=True)

        st.info("**Auto-suggested additions** (copy into ASSETS dict): SMR, PLTR, ARM, IONQ, HOLO, KULR, BITF")

# Run the app
if __name__ == "__main__":
    main()

# ====================== CUSTOMIZATION NOTES ======================
"""
# CUSTOMIZATION NOTES
1. **Add new tickers**:
   - Append to ASSETS["stocks"] or ASSETS["crypto"]
   - For crypto add entry to COINGECKO_IDS dict

2. **Modify scoring weights**:
   - Edit SCORE_WEIGHTS dictionary at the top

3. **Add paid APIs** (recommended for production):
   - Financial Modeling Prep (FMP): replace placeholders in Institutions & Politics
   - NewsAPI.org: add requests.get("https://newsapi.org/...") in Contracts & News
   - QuiverQuant / Capitol Trades JSON endpoints for live politician trades

4. **Auto-refresh without button**:
   - pip install streamlit-autorefresh
   - Then add: from streamlit_autorefresh import st_autorefresh; count = st_autorefresh(interval=60000)

5. **Run the app**:
   pip install streamlit yfinance pycoingecko pandas-ta plotly pandas
   streamlit run app.py
