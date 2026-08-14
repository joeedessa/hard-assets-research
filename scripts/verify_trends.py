#!/usr/bin/env python3
"""Independent recomputation of trends.json from raw price series.

THE POINT OF THIS FILE, AND ITS ONE TRAP
A reimplementation that shares an assumption with the original proves nothing.
In the work this method comes from, a Python replay reproduced the page's state
counts exactly — because the replay had reimplemented the same wrong settled-close
rule. So this script deliberately does NOT import trends.py. It recomputes with
pandas rolling/ewm (a different code path from the hand-rolled loops), and for the
judgement calls it prints the RAW EVIDENCE — actual dated bars around a level test,
actual session timestamps — so the answer is checked against the inputs rather than
against a second copy of our own logic.

    python3 scripts/verify_trends.py            # sample of names
    python3 scripts/verify_trends.py MP FCX     # specific names
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_market import SESSIONS, yahoo_symbol          # data inputs, not logic

ROOT = Path(__file__).resolve().parent.parent
TOL = 0.05          # percentage points; both sides round to 2dp
fails, checks = [], 0


def chk(name, tk, mine, theirs, tol=TOL):
    global checks
    checks += 1
    if mine is None and theirs is None:
        return
    if mine is None or theirs is None:
        fails.append(f"{tk} {name}: page={mine} recomputed={theirs} (one is null)")
        return
    if abs(mine - theirs) > tol:
        fails.append(f"{tk} {name}: page={mine} recomputed={theirs} "
                     f"(diff {abs(mine - theirs):.4f})")


def main(argv):
    global checks
    doc = json.load(open(ROOT / "data" / "trends.json"))
    names = doc["names"]
    picks = [a for a in argv if a in names] or sorted(names)[:: max(1, len(names) // 12)][:12]
    print(f"Verifying {len(picks)} of {len(names)} names against raw series\n")

    for tk in picks:
        rec = names[tk]
        y = yahoo_symbol(tk)
        h = yf.Ticker(y).history(period="3y", auto_adjust=True)
        h = h[h["Close"].notna()]
        if h.empty:
            fails.append(f"{tk}: no raw history")
            continue

        # ── Settled-close gate, checked against the ACTUAL session clock ──────
        tzname, sh, eh = SESSIONS.get(
            next((s for s in sorted(SESSIONS, key=len, reverse=True)
                  if s and tk.endswith(s)), ""), SESSIONS[""])
        tz = ZoneInfo(tzname)
        now = datetime.now(tz)
        last_raw = h.index[-1].date()
        ses_start = now.replace(hour=int(sh), minute=int((sh % 1) * 60), second=0, microsecond=0)
        ses_end = now.replace(hour=int(eh), minute=int((eh % 1) * 60), second=0, microsecond=0)
        forming = (last_raw >= now.date()) and (ses_start <= now < ses_end)
        expect_asof = h.index[-2].date() if forming else last_raw
        if rec["asof"] != expect_asof.isoformat():
            fails.append(f"{tk} asof: page={rec['asof']} raw={expect_asof} "
                         f"(last raw bar {last_raw}, local now {now:%Y-%m-%d %H:%M} {tzname}, "
                         f"session {sh}-{eh}, forming={forming})")
        if forming:
            h = h.iloc[:-1]

        c = h["Close"]
        px = float(c.iloc[-1])
        nb = len(c)
        # Mirror the warm-up gate: below 5x the period a recursive indicator is
        # seed-dependent, so the page withholds it and there is nothing to check.
        warm21, warm14 = nb >= 105, nb >= 70

        # ── Distances, via pandas rolling/ewm rather than our loops ───────────
        # adjust=False matches a recursive EMA; the seed differs from ours by a
        # negligible amount this far into a 750-bar series.
        if warm21:
            chk("d21", tk, rec["d"]["d21"],
                round((px / float(c.ewm(span=21, adjust=False).mean().iloc[-1]) - 1) * 100, 2), 0.30)
        elif rec["d"]["d21"] is not None:
            fails.append(f"{tk} d21: reported on {nb} bars, below the 105-bar EMA21 warm-up")
        for n, key in ((50, "d50"), (150, "d150"), (200, "d200")):
            if len(c) >= n:
                chk(key, tk, rec["d"][key],
                    round((px / float(c.rolling(n).mean().iloc[-1]) - 1) * 100, 2))

        # ── Move, ATR, RSI ────────────────────────────────────────────────────
        chk("d1", tk, rec["move"]["d1"], round((px / float(c.iloc[-2]) - 1) * 100, 2))

        tr = pd.concat([h["High"] - h["Low"],
                        (h["High"] - c.shift()).abs(),
                        (h["Low"] - c.shift()).abs()], axis=1).max(axis=1).iloc[1:]
        atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
        if not warm14:
            if rec["move"]["atr_pct"] is not None:
                fails.append(f"{tk} atr: reported on {nb} bars, below the 70-bar warm-up")
        elif atr <= px / 2:
            chk("atr_pct", tk, rec["move"]["atr_pct"], round(atr / px * 100, 2), 0.35)
        elif rec["move"]["atr_x"] is not None:
            fails.append(f"{tk} atr: page reported a multiple but raw ATR {atr:.2f} "
                         f"exceeds half of price {px:.2f} — should have been rejected")

        d = c.diff()
        g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
        l = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
        if warm14:
            chk("rsi", tk, rec["range"]["rsi"],
                round(100 - 100 / (1 + g / l), 1) if l else 100.0, 1.5)
        elif rec["range"]["rsi"] is not None:
            fails.append(f"{tk} rsi: reported on {nb} bars, below the 70-bar warm-up")

        # ── Range ─────────────────────────────────────────────────────────────
        w = c.iloc[-252:] if len(c) >= 60 else c
        chk("off52h", tk, rec["range"]["off52h"], round((px / float(w.max()) - 1) * 100, 2))
        chk("off52l", tk, rec["range"]["off52l"], round((px / float(w.min()) - 1) * 100, 2))

        # ── Level tests: print the RAW BARS, do not re-derive the verdict ─────
        for key, n in (("test150", 150), ("test200", 200)):
            t = rec["d"].get(key)
            if not t or len(c) < n:
                continue
            lvl = c.rolling(n).mean()
            i = len(c) - 1 - t["ago"]
            if i < 1:
                fails.append(f"{tk} {key}: ago={t['ago']} points outside the series")
                continue
            bar_c, bar_l = float(c.iloc[i]), float(h["Low"].iloc[i])
            bar_h, lv = float(h["High"].iloc[i]), float(lvl.iloc[i])
            probe = bar_l if bar_c >= lv else bar_h
            gap = abs(probe - lv) / lv * 100
            was_above, now_above = bar_c >= lv, px >= float(lvl.iloc[-1])
            expect = ("held" if (was_above and now_above) else
                      "rejected" if (not was_above and not now_above) else
                      "reclaimed" if (not was_above and now_above) else "lost")
            print(f"  {tk} {key}: page says {t['state']} ({t['ago']} bars ago, gap {t['gap']}%)")
            print(f"      raw bar {h.index[i].date()}  close {bar_c:.2f}  low {bar_l:.2f}  "
                  f"high {bar_h:.2f}  SMA{n} {lv:.2f}")
            print(f"      probe {probe:.2f} → gap {gap:.2f}%  |  above at test {was_above}, "
                  f"above now {now_above}  → {expect}")
            if expect != t["state"]:
                fails.append(f"{tk} {key} state: page={t['state']} raw={expect}")
            chk(f"{key} gap", tk, t["gap"], round(gap, 2), 0.35)

        # ── Ladder state, from the raw series ─────────────────────────────────
        e5 = c.ewm(span=5, adjust=False).mean()
        e21 = c.ewm(span=21, adjust=False).mean()
        s50 = c.rolling(50).mean()
        s200 = c.rolling(200).mean()
        # None means "the page is expected to withhold this". Any rung that
        # depends on the EMA21 is withheld below its warm-up, because the state
        # would otherwise flip on the seeding convention rather than on price.
        raw_state = {
            "ema5x21": ("bull" if e5.iloc[-1] > e21.iloc[-1] else "bear") if warm21 else None,
            "pxX50": None if nb < 50 else ("bull" if px > s50.iloc[-1] else "bear"),
            "ema21x50": (None if (nb < 50 or not warm21)
                         else ("bull" if e21.iloc[-1] > s50.iloc[-1] else "bear")),
            "pxX200": None if nb < 200 else ("bull" if px > s200.iloc[-1] else "bear"),
            "sma50x200": None if nb < 200 else ("bull" if s50.iloc[-1] > s200.iloc[-1] else "bear"),
        }
        for sig, want in raw_state.items():
            checks += 1
            got = rec["d"]["cross"][sig]["state"]
            if want is None:
                # Assert it really is withheld — a value here would be the bug.
                if got is not None:
                    fails.append(f"{tk} ladder {sig}: page reported {got} on {nb} bars, "
                                 f"where the raw series cannot support a state")
            elif got != want:
                fails.append(f"{tk} ladder {sig}: page={got} raw={want}")

    print(f"\n{checks} checks across {len(picks)} names")
    if fails:
        print(f"\n{len(fails)} MISMATCH(ES):")
        for f in fails:
            print("  ✗", f)
        return 1
    print("all agree with the raw series")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
