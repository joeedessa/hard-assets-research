#!/usr/bin/env python3
"""Regenerate widgets/widget_combined.html from index.html.

There are two copies of this app. index.html is served by GitHub Pages from the
repo root and loads data from 'data/'; the widget copy sits one directory down
and loads from '../data/'. Nothing else differs between them — verified byte for
byte at the time this script was written.

Keeping them aligned by hand is a defect waiting to happen: an edit applied to
one and not the other produces two dashboards that disagree, and nothing in the
page tells you which one you are looking at. So index.html is the SOURCE and the
widget copy is GENERATED. Do not hand-edit widgets/widget_combined.html.

  python3 scripts/sync_widget.py           regenerate the widget copy
  python3 scripts/sync_widget.py --check   exit 1 if it is out of date (CI)
"""
import pathlib
import sys

SRC = pathlib.Path("index.html")
DST = pathlib.Path("widgets/widget_combined.html")

# Only quoted data/ paths are rewritten. Matching the bare string 'data/' would
# also hit prose and attribute names.
REWRITES = [("'data/", "'../data/"), ('"data/', '"../data/'), ("`data/", "`../data/")]

BANNER = (
    "<!-- GENERATED FILE — do not edit. Source: index.html. "
    "Regenerate with: python3 scripts/sync_widget.py -->\n"
)


def render() -> str:
    out = SRC.read_text()
    for old, new in REWRITES:
        out = out.replace(old, new)
    return BANNER + out


def main() -> int:
    if not SRC.exists():
        print(f"missing source: {SRC}", file=sys.stderr)
        return 1

    want = render()
    check = "--check" in sys.argv

    if check:
        have = DST.read_text() if DST.exists() else ""
        if have == want:
            print(f"in sync: {DST}")
            return 0
        print(
            f"OUT OF SYNC: {DST} does not match index.html.\n"
            "index.html is the source of truth; the widget copy is generated.\n"
            "Fix with: python3 scripts/sync_widget.py",
            file=sys.stderr,
        )
        return 1

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(want)
    n = sum(want.count(new) for _, new in REWRITES)
    print(f"wrote {DST} ({len(want):,} bytes, {n} data paths rewritten)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
