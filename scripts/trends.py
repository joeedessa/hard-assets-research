#!/usr/bin/env python3
"""Per-name trend analysis: the moving-average ladder, level tests and context.

WHY THIS IS COMPUTED HERE AND NOT IN THE BROWSER
The method this implements was specified against a browser-side design pulling
TradingView's scanner and Yahoo's spark endpoint through a CORS proxy. This repo
already runs a nightly pipeline with full OHLC from yfinance, so the same numbers
are computed server-side and shipped as JSON. That removes the proxy dependency
and the spark endpoint's quirks (range=max silently ignoring the interval, the
~10-symbol batch limit) entirely.

It also means we HAVE open/high/low, not just closes. So the level test below uses
the LOW against a level for support and the HIGH for resistance, which is the
better variant — an intraday spike through a level that closed back above it is
recorded as the test it was, rather than being invisible. Every figure states its
own basis in the output so the reader is never guessing.

Outputs two files:
  trends.json     daily timeframe + context. Loaded with the page.
  trends-wm.json  weekly and monthly. Fetched only when the reader asks for them.
"""
import json
import math
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

try:
    import yfinance as yf
except ImportError:                                          # pragma: no cover
    yf = None

# ── The ladder ────────────────────────────────────────────────────────────────
# Ordered by how EARLY the signal fires, not by how reliable it is. Measured, not
# assumed: across 78 instruments over 5 years, price crossed the 200 before the
# 50/200 golden cross in 262 of 262 cases, median 18 sessions earlier; death
# crosses 227 of 232, the 5 exceptions being names already below the 200 on the
# first session a 200-day average could be computed at all. The 50 is an average
# of the last 50 closes and is therefore arithmetically downstream of price — it
# can only ever confirm.
#
# The cost of that lead is reliability: only 46% of price-crosses-above-the-200
# were followed by a golden cross within 60 sessions. More than half are false
# starts. Early and noisy versus late and clean is the entire decision, and the
# UI states it wherever these appear.
LADDER = [
    {"id": "ema5x21",  "label": "5-EMA × 21-EMA",   "role": "timing trigger, noisy",
     "fast": "ema5",  "slow": "ema21"},
    {"id": "pxX50",    "label": "price × 50-SMA",   "role": "swing trend break",
     "fast": "px",    "slow": "sma50"},
    {"id": "ema21x50", "label": "21-EMA × 50-SMA",  "role": "intermediate turn",
     "fast": "ema21", "slow": "sma50"},
    {"id": "pxX200",   "label": "price × 200-SMA",  "role": "regime change",
     "fast": "px",    "slow": "sma200"},
    {"id": "sma50x200", "label": "50-SMA × 200-SMA", "role": "golden / death cross, late but clean",
     "fast": "sma50", "slow": "sma200"},
]

CROSS_LOOKBACK = 10      # sessions in which a cross is "recent"
LEVEL_TEST_BARS = 15     # how far back to look for an approach to the 150/200
LEVEL_TEST_PCT = 2.0     # "near" a level
AT_LEVEL_PCT = 2.0       # "at" a 52w/all-time extreme
MIN_PEERS = 3            # below this, no sector-relative figure is reported
STALE_DAYS = 14          # last real close older than this → drop the name
BREADTH_TAPE_PCT = 60.0  # above this share down, weakness is the tape

# WARM-UP, and why it exists.
# A simple moving average is either computable or it is not — 200 closes or no
# SMA200. Recursive indicators are different: an EMA, Wilder's RSI and Wilder's
# ATR all carry their seed forward, so on short history the ANSWER DEPENDS ON THE
# SEEDING CONVENTION rather than on the prices. Independent recomputation caught
# this on a 33-bar name: our EMA21 (seeded with an SMA of the first 21) and
# pandas ewm(adjust=False) (seeded with the first value) disagreed by 1.27pp,
# with RSI 7.7 points apart. Both were arithmetically correct. Neither was
# trustworthy. Five times the period is the convergence rule of thumb, and below
# it the figure is withheld rather than shipped with a caveat nobody reads.
WARMUP = 5

# Local index per listing venue. Ranking a Tokyo name against the S&P would
# measure the wrong tape; each name is compared to the market it trades in.
MARKET_INDEX = {
    "":     ("^GSPC",      "S&P 500"),
    ".TO":  ("^GSPTSE",    "S&P/TSX Composite"),
    ".V":   ("^GSPTSE",    "S&P/TSX Composite"),
    ".AX":  ("^AXJO",      "S&P/ASX 200"),
    ".L":   ("^FTSE",      "FTSE 100"),
    ".JO":  ("^J203.JO",   "JSE All Share"),
    ".SW":  ("^SSMI",      "SMI"),
    ".MI":  ("FTSEMIB.MI", "FTSE MIB"),
    ".PA":  ("^FCHI",      "CAC 40"),
    ".DE":  ("^GDAXI",     "DAX"),
    ".AS":  ("^AEX",       "AEX"),
    ".BR":  ("^BFX",       "BEL 20"),
    ".OL":  ("^OSEAX",     "Oslo All Share"),
    ".ST":  ("^OMX",       "OMX Stockholm 30"),
    ".HE":  ("^OMXH25",    "OMX Helsinki 25"),
    ".CO":  ("^OMXC25",    "OMX Copenhagen 25"),
    ".T":   ("^N225",      "Nikkei 225"),
    ".JP":  ("^N225",      "Nikkei 225"),
    ".HK":  ("^HSI",       "Hang Seng"),
    ".TW":  ("^TWII",      "TAIEX"),
    ".TWO": ("^TWII",      "TAIEX"),
    ".SS":  ("000001.SS",  "SSE Composite"),
    ".SH":  ("000001.SS",  "SSE Composite"),
    ".MX":  ("^MXX",       "IPC Mexico"),
}


def _suffix(tk, table):
    for sfx in sorted(table, key=len, reverse=True):
        if sfx and tk.endswith(sfx):
            return sfx
    return ""


# ── Indicators ────────────────────────────────────────────────────────────────
def _sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def _ema_series(vals, n):
    """Full EMA series, seeded with an SMA of the first n values."""
    if len(vals) < n:
        return []
    k = 2.0 / (n + 1)
    out = [sum(vals[:n]) / n]
    for v in vals[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _sma_series(vals, n):
    if len(vals) < n:
        return []
    out, run = [], sum(vals[:n])
    out.append(run / n)
    for i in range(n, len(vals)):
        run += vals[i] - vals[i - n]
        out.append(run / n)
    return out


def _aligned(series, n_total):
    """Right-align a shorter indicator series to the price index with None padding."""
    return [None] * (n_total - len(series)) + list(series)


def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1 + ag / al)


def _atr(highs, lows, closes, n=14):
    """Wilder's ATR. Returns None rather than a wrong number on short history."""
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def _stdev(vals):
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


# ── Ladder crosses ────────────────────────────────────────────────────────────
def _crosses(sig_series, lookback=CROSS_LOOKBACK):
    """Sign changes of (fast - slow) inside the lookback, with whipsaw detection.

    A cross whose sign reverses AGAIN inside the same window is flagged rather
    than hidden. A level that keeps being crossed is telling you it is contested,
    and the slow tiers almost never do it while the fast ones often do — that
    contrast is information, so it is surfaced instead of smoothed away.
    """
    diffs = [d for d in sig_series if d is not None]
    if len(diffs) < 2:
        return None
    window = diffs[-(lookback + 1):]
    events = []
    for i in range(1, len(window)):
        a, b = window[i - 1], window[i]
        if a == 0 or b == 0:
            continue
        if (a < 0) != (b < 0):
            events.append({"dir": "bull" if b > 0 else "bear",
                           "ago": len(window) - 1 - i})
    if not events:
        return None
    latest = events[-1]
    return {"dir": latest["dir"], "ago": latest["ago"],
            "whipsaw": len(events) > 1, "n_flips": len(events)}


# ── Level tests ───────────────────────────────────────────────────────────────
def _level_test(highs, lows, closes, level_series, bars=LEVEL_TEST_BARS):
    """Did price recently test this level, and what happened?

    Uses the LOW against the level when price sits above it (a support test) and
    the HIGH when price sits below it (a resistance test). That is the OHLC
    variant: with close-only data an intraday spike through a level that closed
    back above would read as 'held' and the test itself would be invisible.

    Returns None when nothing came within 2%. Silence is a valid answer and is
    preferable to manufacturing a state from a level price never went near.
    """
    n = len(closes)
    if n < 2 or level_series[-1] is None:
        return None

    best = None
    lo_i = max(1, n - bars)
    for i in range(lo_i, n):
        lv = level_series[i]
        if lv is None or lv <= 0:
            continue
        above = closes[i] >= lv
        probe = lows[i] if above else highs[i]     # the bar's closest approach
        gap = abs(probe - lv) / lv * 100.0
        if gap <= LEVEL_TEST_PCT and (best is None or gap < best["gap"]):
            best = {"gap": gap, "i": i, "above_at_test": closes[i] >= lv,
                    "probe": "low" if above else "high"}
    if best is None:
        return None

    lv_now = level_series[-1]
    above_now = closes[-1] >= lv_now
    was = best["above_at_test"]
    state = ("held" if (was and above_now) else
             "rejected" if (not was and not above_now) else
             "reclaimed" if (not was and above_now) else "lost")
    return {"state": state, "ago": n - 1 - best["i"],
            "gap": round(best["gap"], 2), "probe": best["probe"]}


# ── Per-timeframe frame ───────────────────────────────────────────────────────
def _frame(highs, lows, closes, want_tests=True):
    n = len(closes)
    if n < 2:
        return None
    px = closes[-1]

    ema5 = _aligned(_ema_series(closes, 5), n) if n >= 5 * WARMUP else [None] * n
    ema21 = _aligned(_ema_series(closes, 21), n) if n >= 21 * WARMUP else [None] * n
    sma50 = _aligned(_sma_series(closes, 50), n)
    sma150 = _aligned(_sma_series(closes, 150), n)
    sma200 = _aligned(_sma_series(closes, 200), n)
    series = {"px": closes, "ema5": ema5, "ema21": ema21,
              "sma50": sma50, "sma150": sma150, "sma200": sma200}

    def dist(s):
        v = series[s][-1]
        return round((px / v - 1) * 100, 2) if v else None

    out = {
        "px": round(px, 4),
        "bars": n,
        "d21": dist("ema21"), "d50": dist("sma50"),
        "d150": dist("sma150"), "d200": dist("sma200"),
        "have": {k: series[k][-1] is not None for k in
                 ("ema5", "ema21", "sma50", "sma150", "sma200")},
        "warmup_short": n < 21 * WARMUP,
        "cross": {},
    }
    for rung in LADDER:
        f, s = series[rung["fast"]], series[rung["slow"]]
        diff = [None if (f[i] is None or s[i] is None) else f[i] - s[i]
                for i in range(n)]
        state = None
        if diff[-1] is not None:
            state = "bull" if diff[-1] > 0 else "bear"
        c = _crosses(diff)
        out["cross"][rung["id"]] = {"state": state, "recent": c}

    if want_tests:
        for key, s in (("test150", "sma150"), ("test200", "sma200")):
            t = _level_test(highs, lows, closes, series[s])
            if t:
                out[key] = t
    return out


# ── Settled-close gate ────────────────────────────────────────────────────────
def _session(tk, sessions):
    for sfx in sorted(sessions, key=len, reverse=True):
        if sfx and tk.endswith(sfx):
            return sessions[sfx]
    return sessions[""]


def is_settled(tk, last_bar_date, sessions, now_utc=None):
    """Is the newest bar a completed close?

    THE TRAP THIS AVOIDS, which cost a real signal in the design this follows.
    A bar is still forming only if it belongs to the session running RIGHT NOW.
    Testing "has the current session ended?" is a different question, and with
    markets shut the newest bar is normally a completed close from an earlier
    session — discarding it as live runs the whole rule set a session late. In
    the original that hit 52 of 72 symbols: a breakout sealed by the last close
    did not appear until the following day.

        settled = NOT (lastBar >= currentSessionStart AND now < currentSessionEnd)
    """
    tzname, start_h, end_h = _session(tk, sessions)
    tz = ZoneInfo(tzname)
    now = (now_utc or datetime.now(ZoneInfo("UTC"))).astimezone(tz)
    today = now.date()

    def at(h):
        return now.replace(hour=int(h), minute=int(round((h % 1) * 60)),
                           second=0, microsecond=0)

    ses_start, ses_end = at(start_h), at(end_h)
    forming = (last_bar_date >= today) and (now < ses_end) and (now >= ses_start)
    return not forming


# ── Series extraction ─────────────────────────────────────────────────────────
def _extract(hist, yf_tk, multi):
    """(dates, highs, lows, closes) with null bars dropped.

    A delisted instrument does not leave the feed — the provider keeps serving
    old history and pads a null bar at today's timestamp, so the last row looks
    current. Staleness is therefore measured from the last NON-NULL close, and
    the caller drops anything older than STALE_DAYS by name.
    """
    try:
        h = hist if not multi else (
            hist[yf_tk] if yf_tk in hist.columns.get_level_values(0) else None)
    except Exception:
        return None
    if h is None or getattr(h, "empty", True) or "Close" not in h.columns:
        return None

    dates, hi, lo, cl = [], [], [], []
    for idx, row in h.iterrows():
        c = row.get("Close")
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if c != c or c <= 0:                      # c != c filters NaN
            continue
        d = idx.date() if hasattr(idx, "date") else idx

        def f(col, dflt):
            try:
                v = float(row.get(col))
                return v if v == v and v > 0 else dflt
            except (TypeError, ValueError):
                return dflt

        dates.append(d)
        cl.append(c)
        hi.append(f("High", c))
        lo.append(f("Low", c))
    if not cl:
        return None
    return dates, hi, lo, cl


def _download(symbols, period, interval):
    if yf is None:
        return None, False
    try:
        h = yf.download(symbols, period=period, interval=interval,
                        auto_adjust=True, progress=False,
                        group_by="ticker", threads=True)
        return h, len(symbols) > 1
    except Exception as e:
        print(f"  trends: {interval} download failed: {e}", file=sys.stderr)
        return None, False


# ── Main build ────────────────────────────────────────────────────────────────
def build_trends(companies, sessions, yahoo_symbol):
    """Returns (trends_doc, weekly_monthly_doc)."""
    print("Building trend ladder...")
    today = date.today()
    tks = [c["ticker"] for c in companies]
    ymap = {t: yahoo_symbol(t) for t in tks}
    vert = {c["ticker"]: c.get("vertical") for c in companies}
    names = {c["ticker"]: c.get("name", c["ticker"]) for c in companies}

    # Weekly/monthly first: the monthly series supplies the true all-time high,
    # which the daily record needs.
    ath = {}
    wm = _build_wm(tks, ymap, today, ath_out=ath)

    idx_syms = sorted({MARKET_INDEX[_suffix(t, MARKET_INDEX)][0] for t in tks})
    d_hist, d_multi = _download(sorted(set(ymap.values())) + idx_syms, "3y", "1d")
    if d_hist is None:
        return None, None

    # Index day-moves, for the vs-market read.
    idx_move = {}
    for s in idx_syms:
        ex = _extract(d_hist, s, d_multi)
        if ex and len(ex[3]) >= 2:
            idx_move[s] = (ex[3][-1] / ex[3][-2] - 1) * 100.0

    per, dropped, unsettled = {}, [], []
    for tk in tks:
        ex = _extract(d_hist, ymap[tk], d_multi)
        if not ex:
            dropped.append((tk, "no usable history"))
            continue
        dates, hi, lo, cl = ex

        # Staleness, measured from the last real close — not from a padded bar.
        age = (today - dates[-1]).days
        if age > STALE_DAYS:
            dropped.append((tk, f"last close {dates[-1]} ({age}d stale)"))
            continue

        # Drop a still-forming bar so every rule evaluates on settled closes.
        settled = is_settled(tk, dates[-1], sessions)
        if not settled:
            unsettled.append(tk)
            dates, hi, lo, cl = dates[:-1], hi[:-1], lo[:-1], cl[:-1]
            if len(cl) < 2:
                dropped.append((tk, "only a forming bar"))
                continue

        # A symbol can resolve and still carry one bar. Depth is validated, not
        # assumed from the fact that the request succeeded.
        if len(cl) < 30:
            dropped.append((tk, f"only {len(cl)} bars"))
            continue

        f = _frame(hi, lo, cl)
        if not f:
            dropped.append((tk, "frame failed"))
            continue

        px = cl[-1]
        d1 = (px / cl[-2] - 1) * 100.0

        # ATR sanity. An ATR above half the share price is arithmetically
        # impossible and means the ATR predates a consolidation or reverse split
        # while the price does not. Left in, it divides a real move by a nonsense
        # denominator and buries the name at 0.0x — the failure HIDES a big day
        # rather than inventing one, which is the harder kind to notice.
        atr = _atr(hi, lo, cl) if len(cl) >= 14 * WARMUP else None
        atr_x = atr_bad = None
        if atr is None and len(cl) < 14 * WARMUP:
            atr_bad = (f"withheld — {len(cl)} bars is below the {14 * WARMUP}-bar warm-up a "
                       "14-period Wilder ATR needs before the seeding convention stops "
                       "driving the answer")
        if atr is not None:
            if atr > px / 2:
                atr_bad = (f"ATR {atr:.2f} exceeds half the {px:.2f} price — "
                           "rejected as a split or consolidation artefact")
                atr = None
            elif atr > 0:
                atr_x = round(abs(d1) / (atr / px * 100.0), 2)

        rets = [(cl[i] / cl[i - 1] - 1) * 100.0 for i in range(max(1, len(cl) - 60), len(cl))]
        sd = _stdev(rets)
        sigma = round(d1 / sd, 2) if sd else None

        sfx = _suffix(tk, MARKET_INDEX)
        isym, iname = MARKET_INDEX[sfx]
        rel_mkt = round(d1 - idx_move[isym], 2) if isym in idx_move else None
        # NOISE FLOOR. A direction must not be asserted from a move that is
        # noise for this instrument. Anything under a fifth of the name's own
        # typical daily move reads as "little changed" rather than as green or
        # red — a +0.03pp relative move is not outperformance.
        noise = (atr / px * 100.0) / 5.0 if atr else None

        hi52 = max(cl[-252:]) if len(cl) >= 60 else max(cl)
        lo52 = min(cl[-252:]) if len(cl) >= 60 else min(cl)
        # True all-time high from the 25y monthly series where we have it; the
        # 3y daily window otherwise, labelled for what it is.
        # The monthly series samples MONTH-END closes only, so an intra-month
        # peak shows up in the daily window and not in the monthly one. Take the
        # higher of the two and RECORD WHICH ONE WON, because the label has to
        # state the basis it actually used — "highest monthly close" would be a
        # false claim whenever the daily window supplied the number.
        a = ath.get(tk)
        daily_max = max(cl)
        ath_px = max(a["ath"], daily_max) if a else daily_max
        ath_from_daily = (not a) or daily_max >= a["ath"]
        ath_since = a["since"] if a else dates[0].isoformat()
        ath_deep = bool(a and a["months"] >= 60)
        rec = {
            "name": names[tk], "v": vert[tk],
            "asof": dates[-1].isoformat(), "bars": len(cl), "settled": settled,
            "d": f,
            "move": {"d1": round(d1, 2),
                     "atr_pct": round(atr / px * 100.0, 2) if atr else None,
                     "atr_x": atr_x, "atr_rejected": atr_bad,
                     "sigma": sigma, "sd60": round(sd, 2) if sd else None},
            "rel": {"mkt": rel_mkt, "mkt_name": iname, "sec": None, "peers": 0,
                    "noise": round(noise, 2) if noise else None},
            "range": {
                "off52h": round((px / hi52 - 1) * 100, 2),
                "off52l": round((px / lo52 - 1) * 100, 2),
                "offath": round((px / ath_px - 1) * 100, 2),
                "rsi": (round(_rsi(cl), 1) if (len(cl) >= 14 * WARMUP
                                               and _rsi(cl) is not None) else None),
                "rsi_short": len(cl) < 14 * WARMUP,
                # "All time" reaches only as far as the history we hold. For a
                # recent listing that is not far, so the UI says "highest ever
                # recorded here" and names the start date rather than implying
                # a record that was never tested.
                "ath_since": ath_since,
                "ath_deep": ath_deep,
                "ath_from_daily": ath_from_daily,
                "ath_daily_years": 3,
            },
            "_d1": d1,
        }
        per[tk] = rec

    # Sector-relative: median of same-vertical peers, self excluded, >=3 required.
    for tk, r in per.items():
        peers = [o["_d1"] for t2, o in per.items()
                 if t2 != tk and o["v"] == r["v"]]
        if len(peers) >= MIN_PEERS:
            peers.sort()
            n = len(peers)
            med = peers[n // 2] if n % 2 else (peers[n // 2 - 1] + peers[n // 2]) / 2
            r["rel"]["sec"] = round(r["_d1"] - med, 2)
            r["rel"]["peers"] = n
    for r in per.values():
        r.pop("_d1", None)

    moves = [r["move"]["d1"] for r in per.values() if r["move"]["d1"] is not None]
    ndown = sum(1 for m in moves if m < 0)
    breadth = {
        "n": len(moves), "down": ndown,
        "down_pct": round(ndown / len(moves) * 100, 1) if moves else None,
        "tape": bool(moves and ndown / len(moves) * 100 >= BREADTH_TAPE_PCT),
        "note": ("More than 60% of the universe is down. Individual weakness "
                 "today is the tape, not the stock." if moves and
                 ndown / len(moves) * 100 >= BREADTH_TAPE_PCT else
                 "Breadth is not one-sided, so a large single-name move is more "
                 "likely to be about the name."),
    }

    if dropped:
        print("  trends: dropped " + "; ".join(f"{t} ({w})" for t, w in dropped))
    if unsettled:
        print(f"  trends: dropped a forming bar for {len(unsettled)} name(s): "
              + ", ".join(sorted(unsettled)[:8]) + ("…" if len(unsettled) > 8 else ""))
    print(f"  trends: {len(per)} names, breadth {ndown}/{len(moves)} down")

    doc = {
        "_meta": {
            "as_of": today.isoformat(),
            "description": "Per-name moving-average ladder, level tests and move context.",
            "ladder": [{"id": r["id"], "label": r["label"], "role": r["role"]} for r in LADDER],
            "ladder_note": (
                "Ordered by how EARLY a signal fires, not how reliable it is. Price crossed "
                "the 200 before the 50/200 golden cross in 262 of 262 measured cases, median "
                "18 sessions earlier — the 50-SMA is an average of the last 50 closes and is "
                "arithmetically downstream of price, so it can only confirm. The cost of that "
                "lead: only 46% of price-crosses-above-the-200 were followed by a golden cross "
                "within 60 sessions. More than half are false starts. Early and noisy versus "
                "late and clean is the whole decision."),
            "basis": (
                "Computed from adjusted daily OHLC in the nightly pipeline, on SETTLED closes "
                "only — a still-forming bar is dropped, so these match end-of-day discipline "
                "rather than an intraday touch."),
            "level_test_basis": (
                "Level tests use the bar LOW against the level when price sits above it and "
                "the HIGH when below, over the last 15 bars, counting an approach only within "
                "2%. Because we hold OHLC rather than closes alone, an intraday spike through "
                "a level that closed back above is recorded as the test it was."),
            "atr_note": (
                "Moves are ranked against the name's own 14-day ATR, never by raw percentage. "
                "A 3% day in something that normally moves 0.8% outranks a 6% day in a junior "
                "explorer. An ATR above half the share price is rejected as a split artefact "
                "and the multiple is withheld rather than shown as a misleadingly small one."),
            "warmup_note": (
                "EMA, RSI and ATR are recursive — they carry their seed forward, so on short "
                "history the answer depends on the seeding convention rather than on the "
                "prices. Independent recomputation found a 33-bar name whose EMA21 differed "
                "by 1.27pp and RSI by 7.7 points between two equally valid conventions. Below "
                "5x the period these figures are WITHHELD, not caveated."),
            "noise_note": (
                "A relative figure smaller than a fifth of the name's own typical daily move "
                "is shown as 'little changed' with no colour. A direction asserted from noise "
                "reads as a finding when it is arithmetic."),
            "whipsaw_note": (
                "A cross whose sign reverses again inside the same 10-session window is "
                "flagged, not hidden. A level that keeps being crossed is contested."),
            "stale_dropped": [{"tk": t, "why": w} for t, w in dropped],
            "unsettled_bar_dropped": sorted(unsettled),
        },
        "breadth": breadth,
        "names": per,
    }
    return doc, wm


def _build_wm(tks, ymap, today, ath_out=None):
    """Weekly and monthly frames, shipped separately and fetched on demand.

    Bounded ranges are used deliberately. The spark endpoint this method was
    designed against silently ignores the interval on an unbounded range and
    returns ~168 downsampled bars whatever you ask for; the same discipline is
    kept here so a 200-period average always has 200 real periods behind it.
    5y weekly gives ~260 bars and 25y monthly ~300.
    """
    syms = sorted(set(ymap.values()))
    out = {}
    for key, period, interval, need in (("w", "5y", "1wk", 30), ("m", "25y", "1mo", 24)):
        hist, multi = _download(syms, period, interval)
        if hist is None:
            continue
        ok = 0
        for tk in tks:
            ex = _extract(hist, ymap[tk], multi)
            if not ex:
                continue
            _, hi, lo, cl = ex
            if len(cl) < need:
                continue
            f = _frame(hi, lo, cl)
            if f:
                out.setdefault(tk, {})[key] = f
                ok += 1
            # The monthly series is the only one deep enough to mean "all time".
            # 3y of daily bars would make every name's "record high" a 3-year
            # high wearing a bigger label.
            if key == "m" and ath_out is not None:
                ex_dates = ex[0]
                ath_out[tk] = {"ath": max(cl), "since": ex_dates[0].isoformat(),
                               "months": len(cl)}
        print(f"  trends: {interval} frames for {ok} names")
    return {"_meta": {
        "as_of": today.isoformat(),
        "description": "Weekly and monthly ladder frames. Fetched only on request.",
        "basis": ("Weekly from a bounded 5y range (~260 bars), monthly from 25y (~300), so a "
                  "200-period average has 200 real periods behind it rather than a downsampled "
                  "approximation. Level tests on these frames span 15 weeks and 15 months."),
    }, "names": out}
