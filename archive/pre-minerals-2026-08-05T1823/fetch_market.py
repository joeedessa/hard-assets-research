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
from datetime import datetime, date, timedelta, timezone
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

# ── Yahoo symbol mapping ───────────────────────────────────────────────────────
# Our ticker convention is not Yahoo's. This mapping is the single source of
# truth and is MIRRORED EXACTLY in the app JS (yahooSymbol) — links built from
# the raw ticker are dead for most non-US listings.
SPECIAL = {}

SUFFIX_MAP = {
    ".JP": ".T",     # Tokyo — we write .JP, Yahoo uses .T
    ".SH": ".SS",    # Shanghai incl. STAR
    ".TWO": ".TWO",  # Taipei OTC
    ".TW": ".TW",    # Taiwan
    ".T":  ".T",
    ".AX": ".AX",    # ASX
    ".TO": ".TO",    # Toronto
    ".V":  ".V",     # TSX Venture
    ".L":  ".L",     # LSE
    ".JO": ".JO",    # Johannesburg
    ".SW": ".SW",    # SIX Swiss
    ".MI": ".MI",    # Borsa Italiana
    ".PA": ".PA",    # Euronext Paris
    ".DE": ".DE",    # Xetra
    ".AS": ".AS",    # Euronext Amsterdam
    ".BR": ".BR",    # Euronext Brussels
    ".OL": ".OL",    # Oslo
    ".ST": ".ST",    # Stockholm
    ".HE": ".HE",    # Helsinki
    ".CO": ".CO",    # Copenhagen
    ".HK": ".HK",    # Hong Kong — numeric part padded to 4 digits below
}


def yahoo_symbol(tk):
    """Map our ticker convention to Yahoo's. Mirrored in the app as yahooSymbol()."""
    if tk in SPECIAL:
        return SPECIAL[tk]
    for src in sorted(SUFFIX_MAP, key=len, reverse=True):
        if tk.endswith(src):
            base, dst = tk[:-len(src)], SUFFIX_MAP[src]
            if dst == ".HK" and base.isdigit():
                base = base.zfill(4)        # Hong Kong needs 4 digits
            return base + dst
    return tk


# Back-compat alias — the pipeline previously called this normalize_ticker
normalize_ticker = yahoo_symbol


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
    # Producer-country FX. A move here changes miner margins and, for the
    # commodity itself, changes who is a forced seller.
    "AUDUSD": "AUDUSD=X",   # Australia — iron ore, lithium, REE
    "USDCLP": "USDCLP=X",   # Chile — copper, lithium
    "USDZAR": "USDZAR=X",   # South Africa — PGM, gold
    "USDCAD": "USDCAD=X",   # Canada — uranium, copper, potash
    "USDBRL": "USDBRL=X",   # Brazil — iron ore, niobium
}
# Currency -> what it prices, for the breaking-signal wording
FX_PRODUCERS = {
    "AUDUSD": "Australian supply (iron ore, lithium, REE)",
    "USDCLP": "Chilean supply (copper, lithium)",
    "USDZAR": "South African supply (PGM, gold)",
    "USDCAD": "Canadian supply (uranium, copper, potash)",
    "USDBRL": "Brazilian supply (iron ore, niobium)",
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

            # 12-month return — needed to tell a cheap name apart from one that
            # merely gave back part of a large run (see entry-window guard).
            r1y = pct(price, safe_float(closes.iloc[0])) if len(closes) >= 200 else None

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
                "r1y": r1y,
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
    #
    # Drawdown-from-52w-high alone is not an entry signal. A name that ran 28x
    # and gave back half is still far above where it started — AXTI was flagged
    # at -57% while up 2,805% on the year. Require the 12-month return to be
    # modest too, so "entry window" means cheap, not merely off its peak.
    MAX_1Y_FOR_ENTRY = 60.0   # % — above this the drawdown is profit-taking
    for tk, q in quotes.items():
        dd = q.get("dd")
        froth = froth_map.get(tk, 2)
        r1y = q.get("r1y")
        if dd is not None and dd <= DRAWDOWN_THRESHOLD and froth == 1:
            if r1y is not None and r1y > MAX_1Y_FOR_ENTRY:
                continue   # still well up on the year — not a value entry
            alerts.append({
                "type": "entry-window",
                "tk":   tk,
                "label": f"{tk} {dd:.1f}% below 52w high — entry window (insulated)",
                "dd":   dd,
                "r1y":  r1y,
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


# ── ACT NOW: breaking-signal detection ────────────────────────────────────────
# The design problem is the BAR, not the gathering. This must be silent on an
# ordinary day, and its empty state must list the checks that ran so silence
# reads as evidence rather than absence.

HEADLINE_CATS = [
    ("deleveraging", "critical", [
        "default", "bankrupt", "chapter 11", "insolven", "credit default", "cds ",
        "debt spiral", "margin call", "liquidat", "covenant breach", "going concern"]),
    ("macro", "critical", [
        "rate cut", "rate hike", "emergency meeting", "intervention", "circuit breaker",
        "recession", "yield curve", "dollar surge", "currency crisis", "capital controls"]),
    ("policy-shock", "high", [
        "export ban", "export control", "export licens", "tariff", "sanction",
        "nationalis", "nationaliz", "expropriat", "windfall tax", "royalty hike",
        "permit denied", "licence revoked", "license revoked", "quota"]),
    ("catastrophe", "high", [
        "mine collapse", "tailings", "dam failure", "explosion", "fire at",
        "refinery fire", "earthquake", "strike action", "workers strike", "blockade",
        "force majeure", "shut down", "shutdown", "derailment", "flooding"]),
    ("company-critical", "high", [
        "guidance cut", "cuts guidance", "slashes", "profit warning", "ceo steps down",
        "ceo resign", "cfo resign", "fraud", "investigation", "halts production",
        "suspends production", "writedown", "write-down", "impairment",
        "reserve downgrade", "cuts reserves", "resource downgrade", "mine life"]),
    # Substitution is the real tail risk for a scarcity thesis — if the material
    # can be designed out, the chokepoint stops being one.
    ("substitution-threat", "high", [
        "sodium-ion", "sodium ion", "rare-earth free", "rare earth free", "magnet-free",
        "thrifting", "substitute for", "replaces copper", "replaces lithium",
        "cobalt-free", "recycling breakthrough", "designed out", "alternative to"]),
    ("breakthrough", "medium", [
        "breakthrough", "first ever", "world first", "record grade", "new discovery",
        "commercial scale", "doubles capacity"]),
]
# Categories that keep mattering past 72 hours
SLOW_BURN = {"deleveraging", "macro", "catastrophe"}


def _stance_for(tickers, comp_map):
    """Derive a mechanical stance from our own conviction/froth tags."""
    if not tickers:
        return "MONITOR", "No holding is directly affected — context only."
    recs = [comp_map[t] for t in tickers if t in comp_map]
    if not recs:
        return "MONITOR", "Named companies sit outside the investable universe."
    hi_conv = [r for r in recs if r.get("conviction") == 3]
    frothy = [r for r in recs if r.get("froth") == 3]
    insulated = [r for r in recs if r.get("froth") == 1]
    if frothy and not insulated:
        return "STOP ADDING", ("High-froth names are involved (" +
            ", ".join(r["ticker"] for r in frothy) + "). Entry windows close in a squeeze; do not chase.")
    if insulated and not frothy:
        return "BUY THE DISLOCATION", ("Insulated names are involved (" +
            ", ".join(r["ticker"] for r in insulated) + "). Weakness here is opportunity, not information.")
    if hi_conv:
        return "THESIS AT RISK", ("Top-conviction holdings are named (" +
            ", ".join(r["ticker"] for r in hi_conv) + "). Confirm the story before changing anything.")
    return "MONITOR", "Affected names are lower-conviction; watch rather than act."


def compute_breaking(quotes, indices, news, companies):
    """Only events that would change an allocation decision today."""
    print("Scanning for breaking signals...")
    today = date.today().isoformat()
    comp_map = {c["ticker"]: c for c in companies}
    sigs, checks = [], []

    moves = {t: q["d1"] for t, q in quotes.items() if q.get("d1") is not None}
    n = len(moves) or 1
    med = sorted(moves.values())[n // 2] if moves else 0.0
    C = indices.get("commodities", {}) or {}
    M = indices.get("macro", {}) or {}
    # Sector proxy: the broad commodity index if present, else the universe median
    sector = (C.get("CopperETF") or {}).get("d1")
    sector = sector if sector is not None else med

    # 1. Deleveraging signature — everything falls together
    down5 = [t for t, d in moves.items() if d <= -5]
    checks.append(f"Deleveraging signature (≥25% of universe −5%+ while the sector is −3%+): "
                  f"{len(down5)}/{n} down 5%, sector {sector:+.1f}%")
    if len(down5) >= 0.25 * n and sector is not None and sector <= -3:
        st, act = "STAGE", ("Broad, correlated selling is a liquidity event, not a re-rating of the thesis. "
                            "Do not catch the knife — publish and work the staged-entry list instead.")
        sigs.append({"sev": "critical", "cat": "deleveraging", "measured": True,
            "t": f"Correlated drawdown: {len(down5)} of {n} holdings down 5%+ with the sector {sector:+.1f}%",
            "ev": f"Computed from today's closes. Universe median {med:+.1f}%.",
            "stance": st, "action": act, "tk": sorted(down5)[:12], "date": today})

    # 2. Reflex melt-up — the mirror image
    up5 = [t for t, d in moves.items() if d >= 5]
    checks.append(f"Reflex melt-up (≥25% of universe +5%+ while the sector is +4%+): "
                  f"{len(up5)}/{n} up 5%, sector {sector:+.1f}%")
    if len(up5) >= 0.25 * n and sector is not None and sector >= 4:
        sigs.append({"sev": "high", "cat": "melt-up", "measured": True,
            "t": f"Reflex melt-up: {len(up5)} of {n} holdings up 5%+ with the sector {sector:+.1f}%",
            "ev": f"Computed from today's closes. Universe median {med:+.1f}%.",
            "stance": "STOP ADDING",
            "action": "Entry windows are closing. Anything bought into this tape is bought on momentum, not on the structural case.",
            "tk": sorted(up5)[:12], "date": today})

    # 3. Single-name collapse
    collapse = [t for t, d in moves.items() if d <= -12]
    checks.append(f"Single-name collapse (any holding −12%+ in a session): {len(collapse)} found")
    for t in collapse:
        st, act = _stance_for([t], comp_map)
        r = comp_map.get(t, {})
        sigs.append({"sev": "critical", "cat": "company-critical", "measured": True,
            "t": f"{t} {moves[t]:+.1f}% in a single session",
            "ev": f"Computed from today's close. Conviction {r.get('conviction','?')}, froth {r.get('froth','?')}.",
            "stance": "REVIEW", "action": act, "tk": [t], "date": today})

    # 4. Conviction-tier divergence — versus the MEDIAN, not absolute.
    #    On a +6% tape an 8% move is beta, not news.
    div = [(t, d) for t, d in moves.items()
           if comp_map.get(t, {}).get("conviction") == 3 and abs(d - med) >= 8]
    checks.append(f"Conviction-3 divergence (±8%+ versus the {med:+.1f}% universe median): {len(div)} found")
    for t, d in div:
        st, act = _stance_for([t], comp_map)
        sigs.append({"sev": "high", "cat": "divergence", "measured": True,
            "t": f"{t} {d:+.1f}% against a {med:+.1f}% universe median",
            "ev": "Divergence is measured against the median so a broad tape does not masquerade as news.",
            "stance": st, "action": act, "tk": [t], "date": today})

    # 5. COMMODITY-SPECIFIC — where this diverges from the semis sibling
    big_c = [(k, v["d1"]) for k, v in C.items() if v.get("d1") is not None and abs(v["d1"]) >= 5]
    checks.append(f"Tracked commodity ±5%+ in a session: {len(big_c)} of {len(C)} moved")
    for k, d in big_c:
        sigs.append({"sev": "high", "cat": "commodity", "measured": True,
            "t": f"{k} {d:+.1f}% in a session",
            "ev": "Spot/futures move computed from today's close.",
            "stance": "MONITOR" if abs(d) < 8 else "REVIEW",
            "action": (f"The underlying moved {d:+.1f}% while the equities did their own thing. "
                       "Check whether the equity complex has followed — divergence is the signal, not the move."),
            "tk": [], "date": today})

    # Spot vs equity divergence — equities ignoring the underlying
    PAIRS = {"Copper": "cu", "Uranium": "nu", "Gold": "pg", "Lithium": "li", "WTI": "oil", "NatGas": "ng"}
    for cname, vert in PAIRS.items():
        cd = (C.get(cname) or {}).get("d1")
        eq = [moves[c["ticker"]] for c in companies
              if c.get("vertical") == vert and c["ticker"] in moves]
        if cd is None or len(eq) < 2:
            continue
        eqm = sorted(eq)[len(eq) // 2]
        gap = eqm - cd
        if abs(gap) >= 4:
            sigs.append({"sev": "medium", "cat": "spot-equity-divergence", "measured": True,
                "t": f"{cname} {cd:+.1f}% but its equities {eqm:+.1f}% — a {gap:+.1f}pt gap",
                "ev": f"Median of {len(eq)} {vert} holdings against the underlying.",
                "stance": "MONITOR",
                "action": ("Equities and the underlying have decoupled. Either the equity market is "
                           "pricing something the spot is not, or it is wrong — worth knowing which."),
                "tk": [c["ticker"] for c in companies if c.get("vertical") == vert][:8], "date": today})
    checks.append(f"Spot-versus-equity divergence (>4pt gap on {len(PAIRS)} pairs): "
                  f"{sum(1 for s in sigs if s['cat']=='spot-equity-divergence')} found")

    # USD — the macro driver for the whole complex
    dxy = (M.get("DXY") or {}).get("d1")
    checks.append(f"USD (DXY) ±1%+ in a session: {dxy:+.2f}%" if dxy is not None else "USD (DXY): unavailable")
    if dxy is not None and abs(dxy) >= 1:
        sigs.append({"sev": "high", "cat": "macro", "measured": True,
            "t": f"Dollar {dxy:+.2f}% — the macro driver for the whole complex",
            "ev": "DXY session move. Commodities are priced in USD, so this moves everything at once.",
            "stance": "MONITOR",
            "action": ("A dollar move of this size mechanically repositions every commodity price. "
                       "Read today's moves net of it before drawing conclusions."),
            "tk": [], "date": today})

    # Curve flip into backwardation — spot above forward means physical scarcity now
    flips=[]
    for cname, fut in (("WTI", "Brent"),):
        a=(C.get(cname) or {}).get("p"); b=(C.get(fut) or {}).get("p")
        if a and b and a > b:
            flips.append((cname, fut, a, b))
    checks.append(f"Curve flip into backwardation (front above deferred): "
                  f"{len(flips)} of 1 pair flipped")
    for cname, fut, a, b in flips:
        sigs.append({"sev": "high", "cat": "curve-flip", "measured": True,
            "t": f"{cname} ${a:.2f} above {fut} ${b:.2f} — front-month premium",
            "ev": "Front trading above the deferred contract. Backwardation signals physical tightness now, not later.",
            "stance": "REVIEW",
            "action": ("The curve is paying for immediate delivery. That is a physical-scarcity signal "
                       "and usually leads the equities rather than following them."),
            "tk": [], "date": today})

    # Producer-country FX — changes miner margins and who is a forced seller
    fxmoves = [(k, (M.get(k) or {}).get("d1")) for k in FX_PRODUCERS]
    fxmoves = [(k, d) for k, d in fxmoves if d is not None and abs(d) >= 1.5]
    checks.append(f"Producer-country FX ±1.5%+ ({len(FX_PRODUCERS)} pairs tracked): {len(fxmoves)} moved")
    for k, d in fxmoves:
        sigs.append({"sev": "medium", "cat": "producer-fx", "measured": True,
            "t": f"{k} {d:+.2f}% — {FX_PRODUCERS[k]}",
            "ev": "Producer-currency move computed from today's close.",
            "stance": "MONITOR",
            "action": (f"A {d:+.2f}% move in {k} changes local-currency margins for producers there. "
                       "A weaker producer currency cuts their costs in USD terms and makes them "
                       "more willing sellers, which is bearish for the commodity at the margin."),
            "tk": [], "date": today})

    # 6. Headline classification — recency-gated, must touch a holding or be systemic
    scanned = 0
    for a in (news or []):
        title = (a.get("t") or "").lower()
        if not title:
            continue
        scanned += 1
        for cat, sev, kws in HEADLINE_CATS:
            if not any(k in title for k in kws):
                continue
            window = 8 if cat in SLOW_BURN else 3
            d = a.get("d") or ""
            if d:
                try:
                    if (date.today() - date.fromisoformat(d[:10])).days > window:
                        break
                except Exception:
                    pass
            hit = [t for t in comp_map if re.search(r"\b" + re.escape(t) + r"\b", a.get("t") or "")]
            systemic = cat in ("macro", "deleveraging")
            if not hit and not (systemic and sev == "critical"):
                break
            st, act = _stance_for(hit, comp_map)
            sigs.append({"sev": sev, "cat": cat, "measured": False,
                "t": a.get("t"),
                "ev": f"Headline from {a.get('s','unknown source')}, {d or 'undated'}. Parsed text — not independently verified.",
                "stance": st,
                "action": act + " This is a parsed headline, not a datapoint — confirm before acting.",
                "tk": hit, "src": {"u": a.get("u"), "s": a.get("s")}, "date": today})
            break
    checks.append(f"Headline scan across {len(HEADLINE_CATS)} severity categories "
                  f"(3-day window, 8 for solvency/macro/catastrophe): {scanned} read")

    order = {"critical": 0, "high": 1, "medium": 2}
    sigs.sort(key=lambda s: (order.get(s["sev"], 3), not s.get("measured", False)))
    state = "clear" if not sigs else ("critical" if any(s["sev"] == "critical" for s in sigs) else "elevated")
    return {
        "_meta": {
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bar": ("Only events likely to change an allocation decision today. Market-structure signals are "
                    "computed from prices and are facts; headline-derived signals are parsed text and are marked "
                    "unverified. Most days this page should be empty — that is the design."),
            "checks": checks,
        },
        "state": state,
        "signals": sigs[:24],
    }


def compute_performance(companies):
    """Inception-dated tracks. A judgment can only be scored from the date it was MADE.

    Trailing returns of a basket chosen today describe COMPOSITION, not skill —
    the tags did not exist for most of that window. The trailing table is kept
    but demoted and labelled retrospective; only the since-inception tracks
    actually test the framework.
    """
    print("Computing performance...")

    # Real dates the judgment layers were written, taken from git history.
    TRACKS = [
        {"name": "Conviction ranking", "inception": "2026-04-30",
         "note": ("Conviction scores have existed since the initial build on 2026-04-30 and were "
                  "revised on 2026-08-04/05. Names added in the 2026-08-05 expansion are excluded "
                  "below — they have no forward record yet."),
         "select": lambda c: c.get("conviction") == 3 and c.get("last_touched", "") < "2026-08-05",
         "label": "Conviction-3 holdings"},
        {"name": "Froth lens", "inception": "2026-08-04",
         "note": ("Froth tags were written on 2026-08-04. This window is far too short to judge them; "
                  "it is published so the record accumulates in the open rather than being claimed later."),
         "select": lambda c: c.get("froth") == 1 and c.get("last_touched", "") < "2026-08-05",
         "label": "Insulated (froth 1)"},
        {"name": "Froth lens", "inception": "2026-08-04", "same_group": True,
         "select": lambda c: c.get("froth") == 3 and c.get("last_touched", "") < "2026-08-05",
         "label": "High froth (froth 3)"},
    ]

    basket_tickers = [yahoo_symbol(c["ticker"]) for c in companies]
    bench_tickers = list(BENCHMARK_TICKERS.values())
    all_tickers = sorted(set(basket_tickers + bench_tickers))
    try:
        hist = yf.download(all_tickers, period="2y", auto_adjust=True,
                           progress=False, group_by="ticker", threads=True)
    except Exception as e:
        print(f"  Performance download failed: {e}", file=sys.stderr)
        return {"tracks": [], "retrospective": {}, "as_of": date.today().isoformat()}

    def closes_for(sym):
        try:
            if len(all_tickers) == 1:
                return hist["Close"].dropna()
            if sym not in hist.columns.get_level_values(0):
                return None
            return hist[sym]["Close"].dropna()
        except Exception:
            return None

    def since(sym, start):
        c = closes_for(sym)
        if c is None or c.empty:
            return None
        try:
            w = c[c.index.date >= date.fromisoformat(start)]
        except Exception:
            return None
        if len(w) < 2:
            return None
        return pct(w.iloc[-1], w.iloc[0])

    # ── Since-inception tracks (the honest record) ──
    groups = {}
    for spec in TRACKS:
        members = [yahoo_symbol(c["ticker"]) for c in companies if spec["select"](c)]
        rets = [r for r in (since(m, spec["inception"]) for m in members) if r is not None]
        row = {"label": spec["label"], "n": len(rets),
               "si": round(sum(rets) / len(rets), 1) if rets else None}
        g = groups.setdefault(spec["name"], {"name": spec["name"], "inception": spec["inception"],
                                             "note": spec.get("note", ""), "rows": []})
        if spec.get("note") and not g["note"]:
            g["note"] = spec["note"]
        g["rows"].append(row)

    for g in groups.values():
        for bname, bsym in BENCHMARK_TICKERS.items():
            r = since(bsym, g["inception"])
            if r is not None:
                g["rows"].append({"label": f"{bname} — benchmark", "n": 1, "si": r, "bench": True})

    # ── Retrospective trailing table (composition, not skill) ──
    periods = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}

    def trailing(sym, n_days):
        c = closes_for(sym)
        if c is None or len(c) < n_days:
            return None
        return pct(c.iloc[-1], c.iloc[-n_days])

    def median(xs):
        s2 = sorted(xs); n = len(s2)
        return None if not n else (s2[n // 2] if n % 2 else (s2[n // 2 - 1] + s2[n // 2]) / 2)

    retro_mean, retro_med, top = {}, {}, {}
    for period, nd in periods.items():
        pairs = [(t, trailing(t, nd)) for t in basket_tickers]
        pairs = [(t, r) for t, r in pairs if r is not None]
        rets = [r for _, r in pairs]
        retro_mean[period] = round(sum(rets) / len(rets), 1) if rets else None
        retro_med[period] = round(median(rets), 1) if rets else None
        if pairs:
            t, r = max(pairs, key=lambda x: x[1])
            top[period] = {"ticker": t, "ret": round(r, 1),
                           "contribution_pp": round(r / len(rets), 1)}

    retro_bench = {name: {p: trailing(sym, nd) for p, nd in periods.items()}
                   for name, sym in BENCHMARK_TICKERS.items()}

    return {
        "_meta": {
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "Equal-weight, price-only, local currency. No rebalancing, dividends or FX conversion.",
            "retrospective_warning": (
                "The trailing table measures how TODAY'S universe performed in the past. It describes "
                "COMPOSITION, not forecasting skill, because the conviction and froth tags did not exist "
                "for most of that window and 21 of the 71 names were added on 2026-08-05. Only the "
                "since-inception tracks test the framework."),
        },
        "tracks": list(groups.values()),
        "retrospective": {
            "label": "Retrospective composition — NOT a track record",
            "mean": retro_mean, "median": retro_med,
            "top_contributor": top, "benchmarks": retro_bench,
        },
        "as_of": date.today().isoformat(),
    }


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
                "fields": "p=price, d1=1-day%, m1=1-month%, r1y=12-month%, dd=drawdown-from-52w-high%, a50=50DMA, a200=200DMA, mc=market-cap-USD, fpe=fwd-P/E"
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

    breaking = compute_breaking(quotes, indices, news, companies)
    safe_write(DATA / "breaking.json", breaking)
    print(f"  breaking: {breaking['state']} — {len(breaking['signals'])} signal(s)")

    print(f"\nDone. {today}")


if __name__ == "__main__":
    main()
