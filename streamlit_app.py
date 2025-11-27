import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import os
import json
import time
import concurrent.futures

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Geospatial Intelligence Market",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CUSTOM CSS FOR "CYBERPUNK" LOOK ---
st.markdown("""
<style>
    .stApp { background-color: #0f172a; color: #e2e8f0; }
    div[data-testid="stMetricValue"] { font-family: 'Courier New', monospace; color: #22d3ee; }
    h1, h2, h3 { color: #f8fafc; font-family: 'Helvetica', sans-serif; font-weight: 800; letter-spacing: 1px; }
    .stDataFrame { border: 1px solid #334155; }
    div[data-testid="stExpander"] { background-color: #1e293b; border: 1px solid #334155; }
    .css-1d391kg { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)

# --- WATCHLIST ---
WATCHLIST = [
    {"ticker": "PL", "sector": "Earth Obs", "name": "Planet Labs"},
    {"ticker": "BKSY", "sector": "Earth Obs", "name": "BlackSky"},
    {"ticker": "SPIR", "sector": "Earth Obs", "name": "Spire Global"},
    {"ticker": "SATL", "sector": "Earth Obs", "name": "Satellogic"},
    {"ticker": "RKLB", "sector": "Launch/Space", "name": "Rocket Lab"},
    {"ticker": "LUNR", "sector": "Launch/Space", "name": "Intuitive Machines"},
    {"ticker": "RDW", "sector": "Space Infra", "name": "Redwire"},
    {"ticker": "ASTS", "sector": "SatCom", "name": "AST SpaceMobile"},
    {"ticker": "IRDM", "sector": "SatCom", "name": "Iridium"},
    {"ticker": "GSAT", "sector": "SatCom", "name": "Globalstar"},
    {"ticker": "VSAT", "sector": "SatCom", "name": "Viasat"},
    {"ticker": "PLTR", "sector": "Intel/AI", "name": "Palantir"},
    {"ticker": "LMT", "sector": "Prime", "name": "Lockheed Martin"},
    {"ticker": "NOC", "sector": "Prime", "name": "Northrop Grumman"},
    {"ticker": "RTX", "sector": "Prime", "name": "Raytheon"},
    {"ticker": "GD", "sector": "Prime", "name": "General Dynamics"},
    {"ticker": "BA", "sector": "Prime", "name": "Boeing"},
    {"ticker": "TRMB", "sector": "Geospatial", "name": "Trimble"},
    {"ticker": "AVAV", "sector": "Drones", "name": "AeroVironment"},
    {"ticker": "KTOS", "sector": "Defense", "name": "Kratos"},
    {"ticker": "JOBY", "sector": "eVTOL", "name": "Joby Aviation"},
    {"ticker": "ACHR", "sector": "eVTOL", "name": "Archer Aviation"}
]

# --- CACHING & DATA LOGIC ---
DATA_FILE = "geo_market_cache.json"

def get_ttm_sum(df, key):
    """ Calculate Trailing 12 Months sum safely """
    if df is None or df.empty or key not in df.index: return 0.0
    # Sort columns (dates) descending
    cols = sorted(df.columns, reverse=True)
    recent = [df.loc[key, c] for c in cols[:4] if pd.notnull(df.loc[key, c])]
    if not recent: return 0.0
    # Annualize if less than 4 quarters
    if len(recent) < 4: return (sum(recent) / len(recent)) * 4
    return sum(recent)

def safe_get(df, key):
    """ Get latest value from DataFrame """
    if df is None or df.empty or key not in df.index: return 0
    cols = sorted(df.columns, reverse=True)
    val = df.loc[key, cols[0]]
    return val if pd.notnull(val) else 0

def fetch_single_stock(item):
    """ Worker function to fetch one stock's deep data """
    ticker = item['ticker']
    try:
        stock = yf.Ticker(ticker)
        
        # Fetch Data (with error handling)
        try: info = stock.info 
        except: info = {}
        
        # We need quarterly financials for Z-Score/Runway
        # This is the slow part
        try: fins_q = stock.quarterly_financials
        except: fins_q = None
        try: bs_q = stock.quarterly_balance_sheet
        except: bs_q = None
        try: cf_q = stock.quarterly_cashflow
        except: cf_q = None

        # --- Calculations ---
        # 1. Price & Market Cap
        price = info.get('currentPrice', info.get('regularMarketPrice', 0))
        if price == 0: price = stock.fast_info.last_price
        
        mcap = info.get('marketCap', 0)
        if mcap == 0: mcap = 1e9 # Default to prevent division errors

        # 2. Key Metrics
        total_debt = safe_get(bs_q, 'Total Debt')
        cash = safe_get(bs_q, 'Cash And Cash Equivalents')
        if cash == 0: cash = safe_get(bs_q, 'Cash Cash Equivalents And Short Term Investments')
        
        # 3. Z-Score Components (TTM)
        total_assets = safe_get(bs_q, 'Total Assets')
        total_liab = safe_get(bs_q, 'Total Liabilities Net Minority Interest')
        curr_assets = safe_get(bs_q, 'Current Assets')
        curr_liab = safe_get(bs_q, 'Current Liabilities')
        retained_earnings = safe_get(bs_q, 'Retained Earnings')
        ebit_ttm = get_ttm_sum(fins_q, 'EBIT')
        rev_ttm = get_ttm_sum(fins_q, 'Total Revenue')
        
        z_score = 0.0
        if total_assets > 0 and total_liab > 0:
            A = (curr_assets - curr_liab) / total_assets
            B = retained_earnings / total_assets
            C = ebit_ttm / total_assets
            D = mcap / total_liab
            E = rev_ttm / total_assets
            z_score = round((1.2*A) + (1.4*B) + (3.3*C) + (0.6*D) + (1.0*E), 2)

        # 4. Runway
        net_income_q = safe_get(fins_q, 'Net Income')
        runway = 999.0
        if net_income_q < 0:
            monthly_burn = abs(net_income_q) / 3
            if monthly_burn > 0:
                runway = round(cash / monthly_burn, 1)
            else: runway = 0.0

        # 5. FCF Yield
        ocf_ttm = get_ttm_sum(cf_q, 'Operating Cash Flow')
        capex_ttm = abs(get_ttm_sum(cf_q, 'Capital Expenditure'))
        fcf_yield = round(((ocf_ttm - capex_ttm) / mcap) * 100, 2)

        # 6. Composite Score
        score = 100
        if z_score < 1.8: score -= 20
        elif z_score < 3.0: score -= 5
        if runway < 12: score -= 25
        if fcf_yield < 0: score -= 10
        if total_debt > 2 * (total_assets - total_liab): score -= 15 # High Debt/Equity
        score = max(0, min(100, score))

        return {
            "Ticker": ticker,
            "Name": item['name'],
            "Sector": item['sector'],
            "Price": round(price, 2),
            "Z_Score": z_score,
            "Runway": runway,
            "FCF_Yield": fcf_yield,
            "Score": int(score),
            "Updated": datetime.datetime.now().strftime("%H:%M")
        }

    except Exception as e:
        print(f"Failed {ticker}: {e}")
        return None

def load_data():
    """ Load data from JSON cache or return None """
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return pd.DataFrame(json.load(f))
        except: return None
    return None

# --- UI LAYOUT ---

st.title("🛰️ Geospatial Market Intelligence")
st.caption(f"Tracking {len(WATCHLIST)} Key Assets across Earth Observation, Space Infra, and Defense.")

# 1. Action Bar
col1, col2 = st.columns([3, 1])
with col1:
    st.info("System optimized for accuracy using Quarterly Financials (TTM).")
with col2:
    if st.button("🔄 FORCE UPDATE DATA", type="primary"):
        progress_text = "Connecting to Satellite Uplink..."
        my_bar = st.progress(0, text=progress_text)
        
        results = []
        # Run parallel fetching
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_single_stock, item): item for item in WATCHLIST}
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res: results.append(res)
                completed += 1
                my_bar.progress(completed / len(WATCHLIST), text=f"Scanning {futures[future]['ticker']}...")
        
        my_bar.empty()
        
        if results:
            df = pd.DataFrame(results)
            # Save to Cache
            with open(DATA_FILE, 'w') as f:
                json.dump(results, f)
            st.success("✅ Data Uplink Complete")
            st.rerun()
        else:
            st.error("Failed to fetch data.")

# 2. Main Data Display
df = load_data()

if df is None:
    st.warning("⚠️ Local Data Cache Empty. Please click 'FORCE UPDATE DATA' above to initialize.")
else:
    # --- KPI Metrics ---
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    avg_score = df['Score'].mean()
    safe_picks = df[df['Score'] > 80]
    risk_picks = df[df['Score'] < 40]
    
    kpi1.metric("Market Health", f"{int(avg_score)}/100", delta="Sector Avg")
    kpi2.metric("Safe Assets", len(safe_picks), delta="Strong Balance Sheets")
    kpi3.metric("Distressed", len(risk_picks), delta_color="inverse", delta="< 12mo Runway")
    kpi4.metric("Assets Tracked", len(df))

    # --- Filtering ---
    st.markdown("### 📊 Asset Matrix")
    
    # Sort/Filter
    filter_sector = st.multiselect("Filter Sector", df['Sector'].unique())
    if filter_sector:
        df_view = df[df['Sector'].isin(filter_sector)]
    else:
        df_view = df

    # Styling the DataFrame
    def style_dataframe(row):
        return ['background-color: #1e293b'] * len(row)

    # Color conditional formatting
    def highlight_z(val):
        color = '#ef4444' if val < 1.8 else ('#eab308' if val < 3.0 else '#10b981')
        return f'color: {color}; font-weight: bold'
    
    def highlight_runway(val):
        if val == 999: return 'color: #10b981'
        return f'color: {"#ef4444" if val < 12 else "#eab308"}'

    # Display Table
    st.dataframe(
        df_view.style.applymap(highlight_z, subset=['Z_Score'])
               .applymap(highlight_runway, subset=['Runway']),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticker": "Symbol",
            "Z_Score": st.column_config.NumberColumn("Z-Score", help="Altman Z-Score (<1.8 Distress)"),
            "Runway": st.column_config.NumberColumn("Runway (Mo)", format="%.1f mo"),
            "FCF_Yield": st.column_config.NumberColumn("FCF Yield", format="%.2f%%"),
            "Score": st.column_config.ProgressColumn("Stability Score", min_value=0, max_value=100, format="%d")
        }
    )

    # --- Download ---
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Report CSV", data=csv, file_name="GeoIntel_Report.csv", mime="text/csv")

# --- Footer ---
st.markdown("---")
st.caption("Project Geospatial • End of Year Intelligence Report • Data Source: Yahoo Finance TTM")
