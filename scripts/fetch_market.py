#!/usr/bin/env python3
"""
Hard Assets Research — nightly market data fetch.
Outputs: data/quotes.json, data/indices.json, data/news.json, data/alerts.json, data/performance.json
Zero cost: yfinance (unofficial Yahoo Finance) + feedparser (Google News RSS).
"""

import json
import os
import sys
import time
import re
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed — run: pip install yfinance feedparser", file=sys.stderr)
    sys.exit(1)

try:
    import feedparser
except ImportError:
    feedparser = None
    print("feedparser not installed — news will be skipped", file=sys.stderr)

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

# ── Ticker universe ────────────────────────────────────────────────────────────
# Per-equity tickers — load from companies.json to stay in sync
def load_companies():
    p = DATA / "companies.json"
    if not p.exists():
        return []
    with open(p) as f:
        d = json.load(f)
    return d.get("companies", [])

# Map non-standard Yahoo suffixes
SUFFIX_MAP = {
    ".AX": ".AX",   # Australian Stock Exchange — fine as-is
    ".HK": ".HK",   # Hong Kong — pad to 4 digits below
    ".JP": ".T",    # Tokyo (some tickers in our DB use .JP; map to .T)
    ".TW": ".TW",   # Taiwan
    ".T":  ".T",    # Already correct
}

def normalize_ticker(tk):
    """Ensure Yahoo Finance can understand the ticker."""
    for src, dst in SUFFIX_MAP.items():
        if tk.endswith(src):
            base = tk[:-len(src)]
            # HK tickers must be 4 digits
            if dst == ".HK" and base.isdigit() and len(base) < 4:
                base = base.zfill(4)
            return base + dst
    return tk

# ── Commodity & macro indices ──────────────────────────────────────────────────
COMMODITY_INDICES = {
    # Energy
    "WTI":    "CL=F",
    "Brent":  "BZ=F",
    "NatGas": "NG=F",
    # Metals
    "Gold":   "GC=F",
    "Silver": "SI=F",
    "Copper": "HG=F",
    "Platinum": "PL=F",
    "Palladium": "PA=F",
    # Proxies (no direct futures on yfinance for uranium/lithium/REE)
    "Uranium": "SPUT",      # Sprott Physical Uranium Trust — price tracks spot
    "Lithium": "LIT",       # Global X Lithium ETF proxy
    "REE":    "MP",         # MP Materials as REE price proxy
    "CopperETF": "COPX",    # Global X Copper Miners ETF
}

MACRO_INDICES = {
    "DXY":    "DX-Y.NYB",  # US Dollar Index
    "10Y":    "^TNX",       # US 10-Year Treasury Yield
    "SPX":    "^GSPC",
    "VIX":    "^VIX",
}

# Performance basket benchmarks
BENCHMARK_TICKERS = {
    "GSG":  "GSG",    # iShares S&P GSCI Commodity ETF
    "XLE":  "XLE",    # Energy Select Sector SPDR
    "COPX": "COPX",   # Global X Copper Miners
    "URA":  "URA",    # Sprott Uranium Miners ETF
    "SPY":  "SPY",    # S&P 500 (risk benchmark)
}

# ── News RSS feeds ─────────────────────────────────────────────────────────────
NEWS_QUERIES = [
    ("uranium supply chain", ["SPUT", "CCO", "LEU", "NXE"]),
    ("copper supply shortage", ["FCX", "SCCO", "FNV", "WPM"]),
    ("rare earth China export controls", ["MP", "LYC.AX", "UUUU"]),
    ("LNG export terminal", ["LNG", "VGAS", "KMI"]),
    ("lithium battery supply", ["ALB", "SQM", "FLNC"]),
    ("critical minerals security", ["MP", "PPTA", "MTRN"]),
    ("nuclear energy AI data center", ["CEG", "CCO", "LEU"]),
    ("electricity grid infrastructure", ["PWR", "ETN", "GEV", "EME"]),
    ("antimony export ban", ["PPTA"]),
    ("gold silver streaming royalty", ["FNV", "WPM", "RGLD"]),
    ("SiC silicon carbide power", ["WOLF", "COHR"]),
    ("desalination water scarcity", ["ERII", "VWTR"]),
]

VOICE_FEEDS = [
    # Doomberg (flagship long-form commodity/energy)
    ("https://doomberg.substack.com/feed", "Doomberg"),
    # Additional credible commodity/mining/energy voices
    ("https://grahamescott.substack.com/feed", "Graham Scott Mining"),
    ("https://www.mining.com/feed/", "Mining.com"),
    ("https://www.spglobal.com/commodityinsights/en/rss-feed.xml", "S&P Commodity Insights"),
]

MAX_NEWS_PER_QUERY = 4
MAX_NEWS_TOTAL = 80
MAX_VOICE_PER_FEED = 3

# ── Froth alert thresholds ─────────────────────────────────────────────────────
DRAWDOWN_THRESHOLD = -15.0        # % from 52w high → entry window flag
COMMODITY_MOVE_THRESHOLD = 5.0   # 1-day % move in commodity index → alert
SINGLE_DAY_MOVE_THRESHOLD = 8.0  # 1-day % in equity → alert

# ── Utilities ──────────────────────────────────────────────────────────────────
def pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1) * 100, 1)

def safe_float(v, digits=2):
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None

def mc_usd(info):
    """Market cap in USD, handling foreign-listed stocks with FX approximation."""
    mc = info.get("marketCap")
    if mc is None:
        return None
    currency = info.get("currency", "USD")
    # Rough FX to USD (as of 2026-08 approximate)
    fx = {"AUD": 0.64, "CAD": 0.73, "HKD": 0.128, "JPY": 0.0066, "TWD": 0.031}
    return int(mc * fx.get(currency, 1.0))

# ── Main fetch functions ───────────────────────────────────────────────────────
def fetch_quotes(tickers):
    """Download per-equity market data using yfinance batch download."""
    print(f"Fetching {len(tickers)} equity tickers...")
    yahoo_tickers = [normalize_ticker(t) for t in tickers]

    quotes = {}

    # Batch download — 1y of history to compute drawdown and MAs
    try:
        hist = yf.download(
            yahoo_tickers,
            period="1y",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception as e:
        print(f"  Batch download failed: {e}", file=sys.stderr)
        return quotes

    as_of = date.today().isoformat()

    for orig_tk, yf_tk in zip(tickers, yahoo_tickers):
        try:
            # Single vs multi-ticker history shape differs
            if len(yahoo_tickers) == 1:
                h = hist
            else:
                if yf_tk not in hist.columns.get_level_values(0):
                    continue
                h = hist[yf_tk]

            if h.empty or "Close" not in h.columns:
                continue

            closes = h["Close"].dropna()
            if len(closes) < 2:
                continue

            price = safe_float(closes.iloc[-1])
            prev_close = safe_float(closes.iloc[-2])
            d1 = pct(price, prev_close)

            # 1-month return (~21 trading days)
            if len(closes) >= 21:
                m1_base = safe_float(closes.iloc[-21])
                m1 = pct(price, m1_base)
            else:
                m1 = None

            # 52-week high drawdown
            high_52w = safe_float(closes.max())
            dd = pct(price, high_52w)  # will be <= 0

            # 50/200 DMA
            a50  = safe_float(closes.tail(50).mean())  if len(closes) >= 50  else None
            a200 = safe_float(closes.tail(200).mean()) if len(closes) >= 200 else None

            # Info for market cap and fwd P/E (separate per-ticker call)
            info = {}
            try:
                tick = yf.Ticker(yf_tk)
                info = tick.info or {}
            except Exception:
                pass

            fpe = safe_float(info.get("forwardPE"), 1) if info.get("forwardPE") else None
            mc  = mc_usd(info)

            quotes[orig_tk] = {
                "p":   price,
                "d1":  d1,
                "m1":  m1,
                "dd":  dd,
                "a50": a50,
                "a200":a200,
                "fpe": fpe,
                "mc":  mc,
            }
        except Exception as e:
            print(f"  {orig_tk}: {e}", file=sys.stderr)

    return quotes, as_of


def fetch_indices():
    """Download commodity spot prices and macro indices."""
    print("Fetching commodity and macro indices...")
    result = {"commodities": {}, "macro": {}}
    as_of = date.today().isoformat()

    all_symbols = list(COMMODITY_INDICES.values()) + list(MACRO_INDICES.values())

    for label, sym in {**COMMODITY_INDICES, **MACRO_INDICES}.items():
        try:
            tk = yf.Ticker(sym)
            h = tk.history(period="5d", auto_adjust=True)
            if h.empty:
                continue
            closes = h["Close"].dropna()
            if len(closes) < 1:
                continue
            price = safe_float(closes.iloc[-1])
            d1 = pct(price, safe_float(closes.iloc[-2])) if len(closes) >= 2 else None
            bucket = "commodities" if sym in COMMODITY_INDICES.values() else "macro"
            result[bucket][label] = {"p": price, "d1": d1}
        except Exception as e:
            print(f"  Index {label} ({sym}): {e}", file=sys.stderr)
        time.sleep(0.2)

    result["as_of"] = as_of
    return result


def fetch_news():
    """Fetch Google News RSS per query + curated voice feeds."""
    if feedparser is None:
        return []

    print("Fetching news RSS...")
    articles = []
    seen_urls = set()

    def add_article(title, url, source, pub_date, tickers):
        if url in seen_urls:
            return
        seen_urls.add(url)
        articles.append({
            "t": title[:180],
            "u": url,
            "s": source,
            "d": pub_date,
            "tk": tickers,
        })

    # Google News RSS per query
    for query, tickers in NEWS_QUERIES:
        q_enc = query.replace(" ", "+")
        rss_url = f"https://news.google.com/rss/search?q={q_enc}&hl=en-US&gl=US&ceid=US:en"
        try:
            feed = feedparser.parse(rss_url)
            count = 0
            for entry in feed.entries:
                if count >= MAX_NEWS_PER_QUERY:
                    break
                title = getattr(entry, "title", "")
                url   = getattr(entry, "link", "")
                pub   = getattr(entry, "published", "")[:10] if hasattr(entry, "published") else ""
                src   = getattr(entry, "source", {})
                src_name = src.get("title", "Google News") if isinstance(src, dict) else "Google News"
                if title and url:
                    add_article(title, url, src_name, pub, tickers)
                    count += 1
        except Exception as e:
            print(f"  News query '{query}': {e}", file=sys.stderr)
        time.sleep(0.1)

    # Curated voice feeds
    for feed_url, feed_name in VOICE_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries:
                if count >= MAX_VOICE_PER_FEED:
                    break
                title = getattr(entry, "title", "")
                url   = getattr(entry, "link", "")
                pub   = getattr(entry, "published", "")[:10] if hasattr(entry, "published") else ""
                if title and url:
                    add_article(title, url, feed_name, pub, [])
                    count += 1
        except Exception as e:
            print(f"  Voice feed '{feed_name}': {e}", file=sys.stderr)

    return articles[:MAX_NEWS_TOTAL]


def compute_alerts(quotes, indices):
    """Generate nightly alert signals."""
    alerts = []
    today = date.today().isoformat()

    # Load companies for froth metadata
    companies = load_companies()
    froth_map = {c["ticker"]: c.get("froth", 2) for c in companies}

    # 1. Commodity ±5% moves
    for label, data in indices.get("commodities", {}).items():
        d1 = data.get("d1")
        if d1 is not None and abs(d1) >= COMMODITY_MOVE_THRESHOLD:
            direction = "up" if d1 > 0 else "down"
            alerts.append({
                "type": "commodity-move",
                "tk":   None,
                "label": f"{label} {direction} {abs(d1):.1f}% today",
                "d1":   d1,
                "date": today,
            })

    # 2. Equity/commodity divergence — skip without enough data

    # 3. Large single-day equity moves
    for tk, q in quotes.items():
        d1 = q.get("d1")
        if d1 is not None and abs(d1) >= SINGLE_DAY_MOVE_THRESHOLD:
            direction = "▲" if d1 > 0 else "▼"
            alerts.append({
                "type": "equity-move",
                "tk":   tk,
                "label": f"{tk} {direction} {abs(d1):.1f}%",
                "d1":   d1,
                "date": today,
            })

    # 4. Insulated names past drawdown threshold (entry window)
    for tk, q in quotes.items():
        dd = q.get("dd")
        froth = froth_map.get(tk, 2)
        if dd is not None and dd <= DRAWDOWN_THRESHOLD and froth == 1:
            alerts.append({
                "type": "entry-window",
                "tk":   tk,
                "label": f"{tk} {dd:.1f}% below 52w high — entry window (insulated)",
                "dd":   dd,
                "date": today,
            })

    # 5. High-froth names near 52w high (caution)
    for tk, q in quotes.items():
        dd = q.get("dd")
        froth = froth_map.get(tk, 2)
        if dd is not None and dd >= -5.0 and froth == 3:
            alerts.append({
                "type": "froth-high",
                "tk":   tk,
                "label": f"{tk} within 5% of 52w high — high froth, caution",
                "dd":   dd,
                "date": today,
            })

    return {"alerts": alerts, "as_of": today}


def compute_performance(companies):
    """Compute equal-weight basket returns vs benchmarks over 1m/3m/6m/1y."""
    print("Computing performance...")
    periods = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}
    basket_tickers = [normalize_ticker(c["ticker"]) for c in companies
                      if c.get("conviction", 0) >= 2]  # conviction 2+ in basket
    bench_tickers  = list(BENCHMARK_TICKERS.values())

    all_tickers = list(set(basket_tickers + bench_tickers))
    try:
        # 2y window: a calendar year yields only ~250 trading rows, so a "1y"
        # download can never satisfy the 252-day lookback below.
        hist = yf.download(all_tickers, period="2y", auto_adjust=True,
                           progress=False, group_by="ticker", threads=True)
    except Exception as e:
        print(f"  Performance download failed: {e}", file=sys.stderr)
        return {"basket": {}, "benchmarks": {}, "as_of": date.today().isoformat()}

    def period_return(tk, n_days):
        try:
            if len(all_tickers) == 1:
                closes = hist["Close"].dropna()
            else:
                if tk not in hist.columns.get_level_values(0):
                    return None
                closes = hist[tk]["Close"].dropna()
            if len(closes) < n_days:
                return None
            return pct(closes.iloc[-1], closes.iloc[-n_days])
        except Exception:
            return None

    def median(xs):
        s = sorted(xs)
        n = len(s)
        if not n:
            return None
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    basket_returns = {}
    basket_median = {}
    top_contrib = {}
    for period, n_days in periods.items():
        pairs = [(tk, period_return(tk, n_days)) for tk in basket_tickers]
        pairs = [(tk, r) for tk, r in pairs if r is not None]
        rets = [r for _, r in pairs]
        # Mean = the return of an actually-held equal-weight basket.
        # Median = the typical constituent, unaffected by a single extreme name.
        basket_returns[period] = round(sum(rets) / len(rets), 1) if rets else None
        basket_median[period] = round(median(rets), 1) if rets else None
        if pairs:
            tk, r = max(pairs, key=lambda x: x[1])
            # How much of the mean comes from this one name
            share = (r / len(rets)) if rets else 0
            top_contrib[period] = {"ticker": tk, "ret": round(r, 1),
                                   "contribution_pp": round(share, 1)}

    bench_returns = {}
    for name, tk in BENCHMARK_TICKERS.items():
        bench_returns[name] = {}
        for period, n_days in periods.items():
            bench_returns[name][period] = period_return(tk, n_days)

    return {"basket": basket_returns,
            "basket_median": basket_median,
            "top_contributor": top_contrib,
            "n_constituents": len([t for t in basket_tickers
                                   if period_return(t, 21) is not None]),
            "benchmarks": bench_returns,
            "as_of": date.today().isoformat()}


def safe_write(path, data):
    """Write JSON only if the fetch produced valid non-empty data."""
    if data is None:
        print(f"  Skipping write to {path.name} — no data", file=sys.stderr)
        return
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)
    print(f"  ✓ {path.name} written ({path.stat().st_size // 1024}kB)")


def main():
    today = date.today().isoformat()
    companies = load_companies()
    tickers = [c["ticker"] for c in companies]

    # 1. Per-equity quotes
    quotes_result = fetch_quotes(tickers)
    if quotes_result:
        quotes, as_of = quotes_result
        quotes_doc = {
            "_meta": {
                "description": "Per-equity market data. Generated by scripts/fetch_market.py.",
                "as_of": as_of,
                "currency_note": "Local currency. Non-USD prices not converted.",
                "fields": "p=price, d1=1-day%, m1=1-month%, dd=drawdown-from-52w-high%, a50=50DMA, a200=200DMA, mc=market-cap-USD, fpe=fwd-P/E"
            },
            **quotes
        }
        safe_write(DATA / "quotes.json", quotes_doc)
    else:
        quotes = {}

    # 2. Macro + commodity indices
    indices = fetch_indices()
    safe_write(DATA / "indices.json", indices)

    # 3. News
    news = fetch_news()
    if news:
        safe_write(DATA / "news.json", news)

    # 4. Alerts
    alerts = compute_alerts(quotes, indices)
    safe_write(DATA / "alerts.json", alerts)

    # 5. Performance
    perf = compute_performance(companies)
    safe_write(DATA / "performance.json", perf)

    print(f"\nDone. {today}")


if __name__ == "__main__":
    main()
