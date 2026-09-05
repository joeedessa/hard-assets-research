#!/usr/bin/env python3
"""Independent recomputation of breaking.json — the Act Now front door.

Deliberately does NOT import fetch_market.py. Every rule is re-derived here from
the same inputs (quotes.json, indices.json, news.json, companies.json) with its
own, simpler code, and for the headline signals the RAW EVIDENCE is printed: the
headline, its parsed date and age, and the exact substring that justifies each
ticker attribution. A verifier that shares the pipeline's helper functions would
have shared its bugs — the recency gate was silently off for months and a ticker
was being matched as an English word, and both would have "verified" clean.

    python3 scripts/verify_breaking.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
fails, checks = [], 0


def load(n):
    return json.load(open(D / n))


def fail(msg):
    fails.append(msg)


def main():
    global checks
    q = {k: v for k, v in load("quotes.json").items() if not k.startswith("_")}
    idx = load("indices.json")
    news = load("news.json")
    comps = {c["ticker"]: c for c in load("companies.json")["companies"]}
    b = load("breaking.json")
    sigs = b.get("signals", [])
    by_cat = {}
    for s in sigs:
        by_cat.setdefault(s["cat"], []).append(s)
    # Age headlines against the moment breaking.json was BUILT, not against the
    # wall clock. The question is "was this signal within its window when it was
    # emitted?" — using date.today() would make a correct snapshot fail in CI
    # three days later, and a check that fails on the calendar gets switched off.
    as_of = (b.get("_meta") or {}).get("as_of") or ""
    try:
        today = date.fromisoformat(as_of[:10])
    except Exception:
        today = date.today()
        print(f"warning: breaking.json has no parseable as_of; ageing against {today}\n")
    print(f"Ageing headline signals against build date {today}\n")

    # ── Measured rules, re-derived from quotes/indices ─────────────────────
    moves = {t: v["d1"] for t, v in q.items() if v.get("d1") is not None}
    n = len(moves)
    vals = sorted(moves.values())
    med = vals[n // 2] if n else 0.0
    C = idx.get("commodities", {}) or {}
    M = idx.get("macro", {}) or {}
    sector = (C.get("CopperETF") or {}).get("d1")
    sector = sector if sector is not None else med

    def expect(cat, cond, evidence):
        global checks
        checks += 1
        present = cat in by_cat
        if cond and not present:
            fail(f"{cat}: condition holds ({evidence}) but no signal was emitted")
        if present and not cond:
            fail(f"{cat}: signal emitted but condition does not hold ({evidence})")

    down5 = sum(1 for d in moves.values() if d <= -5)
    up5 = sum(1 for d in moves.values() if d >= 5)
    expect("deleveraging", down5 >= 0.25 * n and sector <= -3, f"{down5}/{n} down 5%, sector {sector:+.1f}")
    expect("melt-up", up5 >= 0.25 * n and sector >= 4, f"{up5}/{n} up 5%, sector {sector:+.1f}")

    collapse = sorted(t for t, d in moves.items() if d <= -12)
    got = sorted(t for s in by_cat.get("company-critical", []) if s.get("measured") for t in s.get("tk", []))
    checks += 1
    if collapse != got:
        fail(f"single-name collapse: raw {collapse} vs emitted measured {got}")

    div = sorted(t for t, d in moves.items() if comps.get(t, {}).get("conviction") == 3 and abs(d - med) >= 8)
    got = sorted(t for s in by_cat.get("divergence", []) for t in s.get("tk", []))
    checks += 1
    if div != got:
        fail(f"conviction-3 divergence: raw {div} vs emitted {got}")

    bigc = sorted(k for k, v in C.items() if v.get("d1") is not None and abs(v["d1"]) >= 5)
    expect("commodity", bool(bigc), f"commodities ±5%: {bigc}")

    dxy = (M.get("DXY") or {}).get("d1")
    expect("macro", dxy is not None and abs(dxy) >= 1, f"DXY {dxy}")

    fx = sorted(k for k in ("AUDUSD", "USDCLP", "USDZAR", "USDCAD", "USDBRL")
                if (M.get(k) or {}).get("d1") is not None and abs(M[k]["d1"]) >= 1.5)
    expect("producer-fx", bool(fx), f"FX ±1.5%: {fx}")

    # ── Headline signals: dates, windows, and every attribution justified ──
    by_url = {a.get("u"): a for a in news}
    undated = [a for a in news if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(a.get("d") or ""))]
    checks += 1
    if undated:
        fail(f"news.json: {len(undated)} of {len(news)} items have a non-ISO date, e.g. {undated[0].get('d')!r}")

    SLOW = {"deleveraging", "macro", "catastrophe"}
    print("Headline signals — raw evidence:\n")
    for s in sigs:
        if s.get("measured"):
            continue
        a = by_url.get((s.get("src") or {}).get("u"))
        title = s.get("t") or ""
        d = (a or {}).get("d") or ""
        checks += 1
        try:
            age = (today - date.fromisoformat(d[:10])).days
        except Exception:
            fail(f"headline signal has no parseable date: {title[:80]!r} d={d!r}")
            continue
        window = 8 if s["cat"] in SLOW else 3
        print(f"  [{s['cat']}] {title[:100]}")
        print(f"      dated {d}, age {age}d, window {window}d, attributed to {s.get('tk')}")
        if age > window:
            fail(f"headline signal outside its window: age {age}d > {window}d — {title[:70]!r}")
        # Each attributed ticker must be justified by the COMPANY NAME appearing
        # in the headline, or by an explicit ticker form. This is a different,
        # cruder rule than the pipeline's on purpose.
        for tk in s.get("tk", []):
            checks += 1
            name = (comps.get(tk) or {}).get("name", "")
            first = name.split()[0] if name else ""
            just = None
            if name and name.lower() in title.lower():
                just = f"full name {name!r}"
            elif len(first) >= 5 and re.search(r"\b" + re.escape(first) + r"\b", title, re.I):
                just = f"name word {first!r}"
            elif re.search(r"[\($]" + re.escape(tk.split('.')[0]) + r"\b|(?:NYSE|NASDAQ):\s*" + re.escape(tk.split('.')[0]), title):
                just = "explicit ticker form"
            elif len(tk.split(".")[0]) >= 4 and re.search(r"\b" + re.escape(tk) + r"\b", title):
                just = "4+ letter ticker as word"
            if just:
                print(f"      ✓ {tk}: {just}")
            else:
                fail(f"attribution not justified by headline text: {tk} <- {title[:70]!r}")
                print(f"      ✗ {tk}: nothing in the headline names {name or tk}")

    # Every measured signal must say so, and every headline one must not.
    for s in sigs:
        checks += 1
        if s.get("measured") and "Headline" in (s.get("ev") or ""):
            fail(f"signal marked measured but evidence is a headline: {s.get('t')}")

    print(f"\n{checks} checks across {len(sigs)} signal(s), {len(news)} news items, {n} priced names")
    if fails:
        print(f"\n{len(fails)} MISMATCH(ES):")
        for f in fails:
            print("  ✗", f)
        return 1
    print("breaking.json agrees with its inputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
