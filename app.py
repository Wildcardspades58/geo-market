from flask import Flask, render_template, jsonify, request, make_response, send_from_directory
import yfinance as yf
import pandas as pd
import statistics
import datetime
import feedparser
import io
import csv
import time
import json
import os
import concurrent.futures

app = Flask(__name__)

# --- Configuration ---
# In production (cloud), we cannot rely on a persistent local file if the server restarts.
# However, for a simple cache, a local file is fine for now, or we rely on memory.
DB_FILE = 'geo_market_data.json'
CACHE_DURATION = 3600  # 1 Hour

# --- Watchlist Configuration ---
WATCHLIST = [
    # Earth Observation
    {"ticker": "PL", "sector": "Earth Observation", "name": "Planet Labs PBC"},
    {"ticker": "BKSY", "sector": "Earth Observation", "name": "BlackSky Tech"},
    {"ticker": "SPIR", "sector": "Earth Observation", "name": "Spire Global"},
    {"ticker": "SATL", "sector": "Earth Observation", "name": "Satellogic"},
    
    # Defense Primes & Integrators
    {"ticker": "LMT", "sector": "Defense Prime", "name": "Lockheed Martin"},
    {"ticker": "NOC", "sector": "Defense Prime", "name": "Northrop Grumman"},
    {"ticker": "GD", "sector": "Defense Prime", "name": "General Dynamics"},
    {"ticker": "RTX", "sector": "Defense Prime", "name": "Raytheon (RTX)"},
    {"ticker": "BA", "sector": "Defense Prime", "name": "Boeing"},
    {"ticker": "BAESY", "sector": "Defense Prime", "name": "BAE Systems"},
    {"ticker": "EADSY", "sector": "Defense Prime", "name": "Airbus SE"},
    {"ticker": "THLLY", "sector": "Defense Prime", "name": "Thales Group"},
    {"ticker": "FINMY", "sector": "Defense Prime", "name": "Leonardo S.p.A."},
    {"ticker": "SAFRY", "sector": "Defense Prime", "name": "Safran SA"},
    {"ticker": "TXT", "sector": "Defense Prime", "name": "Textron Inc"},

    # Intel & Analytics Services
    {"ticker": "PLTR", "sector": "Intel Services", "name": "Palantir Tech"},
    {"ticker": "LH", "sector": "Intel Services", "name": "L3Harris Tech"},
    {"ticker": "LDOS", "sector": "Intel Services", "name": "Leidos Holdings"},
    {"ticker": "CACI", "sector": "Intel Services", "name": "CACI International"},
    {"ticker": "SAIC", "sector": "Intel Services", "name": "SAIC"},
    {"ticker": "PSN", "sector": "Intel Services", "name": "Parsons Corp"},
    {"ticker": "BBAI", "sector": "Intel Services", "name": "BigBear.ai"},
    {"ticker": "TTEK", "sector": "Intel Services", "name": "Tetra Tech"},

    # Space Infrastructure & Components
    {"ticker": "RKLB", "sector": "Space Infra", "name": "Rocket Lab USA"},
    {"ticker": "RDW", "sector": "Space Infra", "name": "Redwire Corp"},
    {"ticker": "LUNR", "sector": "Space Infra", "name": "Intuitive Machines"},
    {"ticker": "MOG-A", "sector": "Space Components", "name": "Moog Inc."},
    {"ticker": "CW", "sector": "Space Components", "name": "Curtiss-Wright"},
    {"ticker": "HON", "sector": "Space Components", "name": "Honeywell"},
    {"ticker": "APH", "sector": "Space Components", "name": "Amphenol"},

    # Drones & UAVs
    {"ticker": "AVAV", "sector": "UAV/Drones", "name": "AeroVironment"},
    {"ticker": "KTOS", "sector": "UAV/Drones", "name": "Kratos Defense"},
    {"ticker": "ACHR", "sector": "Air Mobility", "name": "Archer Aviation"},
    {"ticker": "JOBY", "sector": "Air Mobility", "name": "Joby Aviation"},

    # RF, SatCom & Testing
    {"ticker": "IRDM", "sector": "RF/SatCom", "name": "Iridium Comm"},
    {"ticker": "GSAT", "sector": "RF/SatCom", "name": "Globalstar"},
    {"ticker": "VSAT", "sector": "RF/SatCom", "name": "Viasat Inc."},
    {"ticker": "ASTS", "sector": "RF/SatCom", "name": "AST SpaceMobile"},
    {"ticker": "SATS", "sector": "RF/SatCom", "name": "EchoStar"},
    {"ticker": "CMTL", "sector": "RF/SatCom", "name": "Comtech Telecom"},
    {"ticker": "GILT", "sector": "RF/SatCom", "name": "Gilat Satellite"},
    {"ticker": "TSAT", "sector": "RF/SatCom", "name": "Telesat"},
    {"ticker": "KEYS", "sector": "RF/SatCom", "name": "Keysight Tech"},
    {"ticker": "CLNFF", "sector": "RF/SatCom", "name": "Calian Group"},

    # Survey, Sensors & Geospatial
    {"ticker": "TRMB", "sector": "Survey/GNSS", "name": "Trimble Inc."},
    {"ticker": "TDY", "sector": "Survey/Sensors", "name": "Teledyne Tech"},
    {"ticker": "HXGBY", "sector": "Survey/Sensors", "name": "Hexagon AB"},
    {"ticker": "BSY", "sector": "Survey/Software", "name": "Bentley Systems"},
    {"ticker": "TOPCF", "sector": "Survey/GNSS", "name": "Topcon Corp"},
    {"ticker": "SEKEY", "sector": "Survey/Sensors", "name": "Seiko Epson"},
    {"ticker": "BWMN", "sector": "Survey/Eng", "name": "Bowman Consulting"},
    {"ticker": "SPXC", "sector": "Survey/Sensors", "name": "SPX Technologies"},

    # Tech Enablers
    {"ticker": "NVDA", "sector": "Tech Enabler", "name": "NVIDIA"},
    {"ticker": "ORCL", "sector": "Tech Enabler", "name": "Oracle Corp"},
    {"ticker": "GOOGL", "sector": "Tech Enabler", "name": "Alphabet Inc"},
    {"ticker": "AMZN", "sector": "Tech Enabler", "name": "Amazon"},
    {"ticker": "MSFT", "sector": "Tech Enabler", "name": "Microsoft"},
    {"ticker": "SNOW", "sector": "Tech Enabler", "name": "Snowflake"},
    {"ticker": "PANW", "sector": "Tech Enabler", "name": "Palo Alto Networks"},
    {"ticker": "ZS", "sector": "Tech Enabler", "name": "Zscaler"},
    {"ticker": "AMD", "sector": "Tech Enabler", "name": "AMD"},
    {"ticker": "AVGO", "sector": "Tech Enabler", "name": "Broadcom"}
]

# --- Database Logic ---

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return None
    return None

def save_db(data):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except:
        pass # In cloud environments with ephemeral file systems, this might fail, which is acceptable for now.

def get_ttm_sum(df, key):
    if df is None or df.empty or key not in df.index:
        return 0.0
    row = df.loc[key]
    sorted_cols = sorted(df.columns, reverse=True)
    recent_quarters = [row[col] for col in sorted_cols[:4] if pd.notnull(row[col])]
    if not recent_quarters: return 0.0
    if len(recent_quarters) < 4:
        avg_val = sum(recent_quarters) / len(recent_quarters)
        return avg_val * 4
    return sum(recent_quarters)

def safe_get_latest(df, key, default=0):
    if df is not None and not df.empty:
        if key in df.index:
            sorted_cols = sorted(df.columns, reverse=True)
            val = df.loc[key, sorted_cols[0]]
            return val if pd.notnull(val) else default
    return default

def calculate_metrics_robust(info, bs, cf, fins, quarterly_fins):
    metrics = {
        "z_score": 0.0, "fcf_yield": 0.0, "runway": 99.0, 
        "de_ratio": 0.0, "score": 50, "raw_debt": 0, "raw_cash": 0
    }
    
    try:
        market_cap = info.get('marketCap', 0)
        if market_cap == 0 and info.get('previousClose') and info.get('sharesOutstanding'):
            market_cap = info['previousClose'] * info['sharesOutstanding']
        if market_cap == 0: market_cap = 1000000 
        
        total_debt = safe_get_latest(bs, 'Total Debt')
        if total_debt == 0: total_debt = info.get('totalDebt', 0)

        cash = safe_get_latest(bs, 'Cash And Cash Equivalents')
        if cash == 0: 
            cash = safe_get_latest(bs, 'Cash Cash Equivalents And Short Term Investments')
        if cash == 0: cash = info.get('totalCash', 0)

        total_assets = safe_get_latest(bs, 'Total Assets')
        total_liab = safe_get_latest(bs, 'Total Liabilities Net Minority Interest')
        curr_assets = safe_get_latest(bs, 'Current Assets')
        curr_liab = safe_get_latest(bs, 'Current Liabilities')
        retained_earnings = safe_get_latest(bs, 'Retained Earnings')
        
        ebit_ttm = get_ttm_sum(quarterly_fins, 'EBIT')
        revenue_ttm = get_ttm_sum(quarterly_fins, 'Total Revenue')
        net_income_ttm = get_ttm_sum(quarterly_fins, 'Net Income')
        net_income_mrq = safe_get_latest(quarterly_fins, 'Net Income')
        
        op_cash_flow_ttm = get_ttm_sum(cf, 'Operating Cash Flow')
        capex_ttm = abs(get_ttm_sum(cf, 'Capital Expenditure'))

        total_equity = total_assets - total_liab
        if total_equity > 0:
            metrics['de_ratio'] = round(total_debt / total_equity, 2)
        elif total_debt > 0:
            metrics['de_ratio'] = 99.0 
        else:
            metrics['de_ratio'] = 0.0

        fcf_ttm = op_cash_flow_ttm - capex_ttm
        metrics['fcf_yield'] = round((fcf_ttm / market_cap) * 100, 2)

        if net_income_mrq < 0:
            monthly_burn = abs(net_income_mrq) / 3
            if monthly_burn > 0:
                metrics['runway'] = round(cash / monthly_burn, 1)
            else:
                metrics['runway'] = 0.0
        else:
            metrics['runway'] = 999.0

        if total_assets > 0 and total_liab > 0:
            A = (curr_assets - curr_liab) / total_assets
            B = retained_earnings / total_assets
            C = ebit_ttm / total_assets
            D = market_cap / total_liab
            E = revenue_ttm / total_assets
            metrics['z_score'] = round((1.2*A) + (1.4*B) + (3.3*C) + (0.6*D) + (1.0*E), 2)
        
        score = 100
        if metrics['de_ratio'] > 2.0: score -= 20
        if metrics['z_score'] < 1.8: score -= 20 
        elif metrics['z_score'] < 3.0: score -= 5
        if metrics['runway'] < 12: score -= 25
        if market_cap < 1000000000: score -= 10
        if metrics['fcf_yield'] > 0: score += 5 
        if cash > total_debt: score += 10
        if revenue_ttm == 0: score -= 10

        metrics['score'] = max(0, min(100, score))
        metrics['raw_debt'] = total_debt
        metrics['raw_cash'] = cash
        return metrics

    except Exception as e:
        return metrics

def fetch_single_ticker(item):
    try:
        sym = item['ticker']
        stock = yf.Ticker(sym)
        try: info = stock.info
        except: info = {}
        try: bs_q = stock.quarterly_balance_sheet
        except: bs_q = None
        try: cf_q = stock.quarterly_cashflow
        except: cf_q = None
        try: fins_q = stock.quarterly_financials
        except: fins_q = None
        
        metrics = calculate_metrics_robust(info, bs_q, cf_q, fins_q, fins_q)
        price = 0
        if info:
             price = info.get('currentPrice', info.get('regularMarketPrice', 0))
        if price == 0:
             try: price = stock.fast_info['last_price']
             except: pass

        return {
            **item, "price": round(price, 2), "de_ratio": metrics['de_ratio'],
            "z_score": metrics['z_score'], "fcf_yield": metrics['fcf_yield'],
            "runway": metrics['runway'], "score": metrics['score'],
            "raw_debt": metrics['raw_debt'], "raw_cash": metrics['raw_cash']
        }
    except Exception as e:
        print(f"Failed to fetch {item['ticker']}: {e}")
        return None

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

# This is new: Serves the Manifest file so Android treats it as an App
@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Geospatial Market",
        "short_name": "GeoMarket",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
        "icons": [
            {
                "src": "https://cdn-icons-png.flaticon.com/512/4742/4742749.png", 
                "sizes": "192x192",
                "type": "image/png"
            }
        ]
    })

@app.route('/api/dashboard-data')
def get_dashboard_data():
    now = time.time()
    db = load_db()
    
    needs_update = False
    if not db or (now - db.get('timestamp', 0) > CACHE_DURATION):
        needs_update = True
    else:
        db_tickers = {c['ticker'] for c in db.get('companies', [])}
        config_tickers = {c['ticker'] for c in WATCHLIST}
        if not config_tickers.issubset(db_tickers):
            needs_update = True

    if not needs_update:
        return jsonify(db)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_single_ticker, WATCHLIST))
    
    company_data = [r for r in results if r is not None]

    sector_stats = {}
    for c in company_data:
        sec = c['sector']
        if sec not in sector_stats: sector_stats[sec] = []
        sector_stats[sec].append(c['score'])

    sector_averages = {k: round(statistics.mean(v)) for k,v in sector_stats.items() if v}
    last_updated = datetime.datetime.now().strftime("%H:%M:%S")
    
    new_db = {
        "companies": company_data, 
        "sectors": sector_averages,
        "last_updated": last_updated,
        "timestamp": now,
        "source": "Live API"
    }
    
    save_db(new_db)
    return jsonify(new_db)

@app.route('/api/market-chart')
def get_market_chart():
    period = request.args.get('period', '3mo')
    tickers = [x['ticker'] for x in WATCHLIST]
    tickers.append("SPY")
    try:
        data = yf.download(tickers, period=period, interval="1d", auto_adjust=True, progress=False)['Close']
        if data.empty: return jsonify({"dates":[], "geo_index":[], "spy_index":[]})
        
        normalized = data.ffill().apply(lambda x: (x / x.iloc[0]) - 1) * 100
        geo_tickers = [t for t in tickers if t != 'SPY' and t in normalized.columns]
        
        if geo_tickers:
            geo_index = normalized[geo_tickers].mean(axis=1).fillna(0).tolist()
            dates = normalized.index.strftime('%Y-%m-%d').tolist()
            spy_data = normalized['SPY'].fillna(0).tolist() if 'SPY' in normalized.columns else []
            return jsonify({"dates": dates, "geo_index": geo_index, "spy_index": spy_data})
        return jsonify({"dates":[], "geo_index":[], "spy_index":[]})
    except: return jsonify({"dates":[], "geo_index":[], "spy_index":[]})

@app.route('/api/news')
def get_news():
    proxies = ["RKLB", "LMT", "PLTR"]
    news_feed = []
    seen = set()
    try:
        for symbol in proxies:
            stock = yf.Ticker(symbol)
            stories = stock.news
            if not stories: continue
            for story in stories[:2]:
                title = story.get('title', '')
                if title not in seen:
                    ts = story.get('providerPublishTime', 0)
                    news_feed.append({
                        "title": title, "publisher": story.get('publisher'),
                        "link": story.get('link'),
                        "time": datetime.datetime.fromtimestamp(ts).strftime('%d %b'),
                        "related": symbol, "type": "General"
                    })
                    seen.add(title)
    except: pass
    
    if len(news_feed) < 5:
        try:
            feed = feedparser.parse("https://spacenews.com/feed/")
            for entry in feed.entries[:5]:
                if entry.title not in seen:
                    news_feed.append({
                        "title": entry.title, "publisher": "SpaceNews",
                        "link": entry.link, "time": "Latest",
                        "related": "SECTOR", "type": "General"
                    })
                    seen.add(entry.title)
        except: pass
    return jsonify({"items": news_feed[:10], "updated": datetime.datetime.now().strftime("%d %b %H:%M")})

@app.route('/api/company-details/<ticker>')
def get_company_details(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info
        try: full_info = stock.info
        except: full_info = {}
        hist = stock.history(period="1y")
        
        insider_data = []
        try:
            insider = stock.insider_transactions
            if insider is not None and not insider.empty:
                insider = insider.sort_index(ascending=False).head(5)
                for index, row in insider.iterrows():
                    date_val = index
                    if hasattr(date_val, 'strftime'): date_str = date_val.strftime('%Y-%m-%d')
                    else: date_str = str(date_val).split(' ')[0]
                    insider_data.append({
                        "date": date_str, "insider": row.get('Insider', 'Unknown'),
                        "shares": int(row.get('Shares', 0)), "type": "Sell" if "Sale" in str(row.get('Transaction', '')) else "Buy"
                    })
        except: pass 

        earnings_msg = "Unknown"
        try:
            cal = stock.calendar
            if cal is not None and not cal.empty:
                if 'Earnings Date' in cal: val = cal['Earnings Date'][0]
                elif 0 in cal: val = cal[0][0]
                else: val = cal.iloc[0][0]
                if hasattr(val, 'date'):
                    days_diff = (val.date() - datetime.datetime.now().date()).days
                    earnings_msg = f"In {days_diff} Days ({val.strftime('%d %b')})"
        except: pass

        de_dates, de_values = [], []
        try:
            financials = stock.quarterly_balance_sheet
            if financials is not None and not financials.empty:
                debt_key = next((k for k in financials.index if 'Total Debt' in k), None)
                equity_key = next((k for k in financials.index if 'Stockholders Equity' in k), None)
                if not equity_key: equity_key = next((k for k in financials.index if 'Total Equity' in k), None)
                if debt_key and equity_key:
                    dates = sorted(financials.columns) 
                    for date in dates:
                        try:
                            d = financials.loc[debt_key, date]
                            e = financials.loc[equity_key, date]
                            if pd.notna(d) and pd.notna(e) and e != 0:
                                de_dates.append(date.strftime('%Y-%m'))
                                de_values.append(round(d/e, 2))
                        except: continue
        except: pass
        if not de_values: de_dates, de_values = ["No Data"], [0]

        z_components = {}
        try:
            bs = stock.quarterly_balance_sheet
            ta = safe_get_latest(bs, 'Total Assets')
            tl = safe_get_latest(bs, 'Total Liabilities Net Minority Interest')
            mc = info.market_cap if info.market_cap else 0
            if ta > 0:
                z_components['Total Assets'] = f"${ta/1e9:.2f}B"
                z_components['Total Liab'] = f"${tl/1e9:.2f}B"
                z_components['Market Cap'] = f"${mc/1e9:.2f}B"
        except: pass

        return jsonify({
            "description": full_info.get('longBusinessSummary', 'No description available.'),
            "employees": full_info.get('fullTimeEmployees', 'N/A'),
            "city": full_info.get('city', 'N/A'),
            "website": full_info.get('website', '#'),
            "revenue_growth": full_info.get('revenueGrowth', 0),
            "gross_margins": full_info.get('grossMargins', 0),
            "earnings_next": earnings_msg,
            "insider_trades": insider_data,
            "dates": hist.index.strftime('%Y-%m-%d').tolist(),
            "prices": hist['Close'].tolist(),
            "de_dates": de_dates, "de_values": de_values, "z_components": z_components 
        })
    except Exception as e: return jsonify({"error": "Failed to fetch details"})

@app.route('/api/export-csv')
def export_csv():
    db = load_db()
    if not db: return "No data available.", 404
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Ticker", "Company", "Sector", "Price", "Score", "D/E", "Z-Score", "FCF Yield", "Runway"])
    for c in db['companies']:
        cw.writerow([c['ticker'], c['name'], c['sector'], c['price'], c['score'], c['de_ratio'], c['z_score'], c['fcf_yield'], c['runway']])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=GeoIntel_Report.csv"
    output.headers["Content-type"] = "text/csv"
    return output

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)