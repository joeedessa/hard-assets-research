# QA log — defects, root causes, and the checks that would have caught them

A running record of every real bug found in this dashboard, organised by **failure
class** rather than by date, because the same classes keep recurring and the point
of this file is to stop them recurring again.

Each entry answers four questions:

- **What broke** — the observable defect.
- **Why it survived** — this matters more than the fix. Almost none of these were
  caught by reading the code; nearly all looked correct on screen.
- **Fix** — what was changed.
- **Standing check** — the test, assertion or habit that catches the whole class,
  not just the instance.

> **The single most important pattern in this file:** a wrong number looks wrong,
> but **a wrong sentence reads as authority**. The most damaging defects here were
> not crashes. They were confidently phrased, correctly rendered, arithmetically
> valid statements that were false. Several inverted an investment conclusion.

**How to use this file.** Before shipping a change, run the [pre-flight
checklist](#pre-flight-checklist). After finding a bug, add it to the matching
class using the [template](#append-template) at the bottom. If it fits no existing
class, open a new one — a new class is a genuine finding.

Last updated: 2026-09-05. 54 entries across 9 failure classes.

---

## Tooling

Three of the checks below are automated. Run them; do not re-do them by hand.

| Command | Catches | In CI? |
|---|---|---|
| `python3 scripts/sync_widget.py --check` | the two HTML copies drifting apart (5.3) | **yes** |
| `python3 scripts/audit_schema.py` | data fields the renderer never reads (3.1, 3.2, 3.7) | no — needs a human to say which fields are intentionally internal |
| `python3 scripts/audit_schema.py --symbols` | dead tickers still priced as live (1.8, 3.5) | no — needs network |
| `python3 scripts/verify_trends.py [TICKERS]` | trend maths, recomputed from raw series by a different code path (Class 6) | no — needs network |
| `scripts/dom_field_sweep.js` (paste in browser console) | fields whose VALUES never reach the rendered page — catches nested fields and per-file misses the static sweep cannot (3.9) | no — needs the running page |
| `python3 scripts/verify_breaking.py` | the Act Now signals — measured rules re-derived from quotes/indices, every headline signal's age and ticker attribution justified from the raw record (6.5, 7.3) | no network needed — **candidate for CI** |

---

## Pre-flight checklist

Distilled from everything below. Ordered by how often it has actually caught something.

**Claims and wording**
- [ ] Every label containing **"since", "over", "vs", "all-time", "record"** is a
      claim. Verify the number was computed on the basis the label states.
- [ ] Any figure asserting a **direction** must clear a noise floor — compare it to
      the series' own typical move, not to zero.
- [ ] Any **status word** (`active`, `investigating`, `pending`, `upcoming`) is a
      claim about the present. Re-check it against a primary source, not a memory.
- [ ] A **percentage with a near-zero denominator** is arithmetic, not information.
      Withhold it and keep the absolute figure.
- [ ] Distinguish **measured** from **inferred** in the text itself.
- [ ] A hedge ("not confirmed", "spot-checked only") is a **to-do with a date**, not
      a resting state. Two of these sat for weeks and both hid material changes.
- [ ] After correcting any fact, **grep its old wording across every data file and
      `index.html`**. The same sentence is repeated across tabs by design (Class 9).
- [ ] Every share percentage names its **basis**: country vs company, attributable vs
      operated, production vs reserves vs capacity.
- [ ] Any sentence describing **the page's own behaviour** ("sorted by…", "ranked
      by…", "excludes…") is a testable assertion. Test it against the rendered DOM.

**Data**
- [ ] Run `python3 scripts/audit_schema.py --symbols`. A delisted instrument **does
      not leave the feed** — it keeps serving old history with a null bar padded at
      today's timestamp, so the last row looks current.
- [ ] Validate **history depth**, not just that the symbol resolved.
- [ ] Recursive indicators (EMA/RSI/ATR) need **5× their period** before the seeding
      convention stops driving the answer. Below that, withhold.
- [ ] Run `python3 scripts/audit_schema.py`. A new field in a data file is invisible
      until the renderer is updated, and this has never happened as a single instance
      — four separate cases so far.

**Code and pipeline**
- [ ] After editing either HTML copy, run `python3 scripts/sync_widget.py`.
- [ ] Check JS brace balance after every scripted edit to `index.html`.
- [ ] Confirm `TAB_IDS` order still matches the `.tab` span markup order.
- [ ] If the pipeline writes a new file, add it to what the nightly workflow commits.
- [ ] After editing a ticker in `companies.json`, **run a full pass** — generated
      files keep the old symbol until they are rebuilt.
- [ ] Reload the page and read the console before claiming anything works.

**Verification**
- [ ] Recompute from **raw inputs** with a different code path. A reimplementation
      that shares an assumption with the original proves nothing.
- [ ] When a verifier and the page disagree, **establish which is wrong** before
      changing either.
- [ ] For any `try/except` that continues, ask what the output looks like if it
      fires on **every** record. If "normal", the guard fails open (6.5).

---

## Class 1 — Claims that were true once

The largest and most damaging class. A fact is written correctly, the world moves,
and nothing in the system notices. Everything here rendered perfectly.

### 1.1 Section 232 copper: "investigating" a year after the tariffs landed — and the mechanism was backwards
- **What broke** — The card carried `status: investigating` and asked what would
  happen *"if tariffs imposed"*. They were imposed 2025-08-01 and modified
  2026-04-06. Worse, the stated benefit ("FCX and SCCO gain a domestic price
  premium") was written for a tariff on **refined copper**, which was never enacted.
  The actual proclamation **exempts ores, concentrates, cathodes and scrap** — the
  duty lands on fabricated product. The miners' primary output isn't tariffed.
- **Why it survived** — Written once from a plausible model of what a copper tariff
  would look like, then never re-read against the enacted text. It was internally
  coherent, which is exactly what makes this class hard to spot.
- **Fix** — Rewrote with the enacted scope; recorded that the earlier conclusion was
  wrong rather than silently replacing it.
- **Standing check** — Any regime with a non-terminal status is a live claim. Re-verify
  status words on every audit pass.

### 1.2 I marked a resolved lever "PAST WITH NO OUTCOME"
- **What broke** — Same session, same file: I annotated the copper lever as a window
  that had passed with no announced outcome. The outcome had happened **twice**.
- **Why it survived** — I inferred silence from *our* sourcing rather than checking
  the world. Absence of a record in this repo is not absence of an event.
- **Standing check** — Never write "no outcome" without a search. Absence claims
  require the same evidence as presence claims. See also 4.1.

### 1.3 China REE "50% rule" — wrong threshold and wrong status
- **What broke** — Described an extraterritorial **"50% rule"** as in force. The
  threshold is **0.1%**, and the rule is **suspended until 2026-11-10**. The 50%
  figure is the US BIS Affiliates Rule ownership test — a different instrument on
  the other side of the same standoff.
- **Why it survived** — Two adjacent regimes, two numbers, conflated once and never
  re-read. A reader would have priced a binding global constraint that does not exist.
- **Standing check** — When two instruments sit in the same dispute, cite each
  separately and name which side issued it.

### 1.4 Antimony overstated by a full escalation rung
- **What broke** — "China banned antimony exports (effective October 2024)" was
  wrong three ways: the worldwide measure was **licensing** (announced 2024-08-15,
  effective 2024-09-15); the **ban** was 2024-12-03 and **US-specific**; and that ban
  has been **suspended since 2025-11**.
- **Why it survived** — Two distinct measures collapsed into one sentence.
- **Standing check** — Licensing ≠ ban ≠ suspension. Record instrument, scope,
  effective date and current status as separate fields.

### 1.5 45X phase-down: right direction, wrong decade
- **What broke** — "Credits scale down after 2029". Under the IRA as enacted,
  critical minerals had **no** phase-out; OBBBA introduced 2031/2032/2033. The 2029
  date belongs to **metallurgical coal**, newly added and irrelevant to this universe.
- **Standing check** — When a statute is amended, re-derive the schedule from the
  amending act; do not patch the old sentence.

### 1.6 Critical-minerals map built on a superseded list
- **What broke** — The map measured coverage against the **USGS 2022 list of 50**,
  describing it as "the last one finalised". The 2025 revision was finalised
  **2025-11-07** at **60 commodities**. Copper, potash, phosphate, silver, silicon
  and uranium — six core verticals — rendered as *not* US-designated.
- **Why it survived** — The file recorded the 2025 revision as a draft and nothing
  ever re-checked. Coverage was measured against the wrong denominator for 9 months.
- **Standing check** — Any cited list version is a dated claim. Store the version and
  publication date, and re-check on each audit.

### 1.7 Fiscal programs: all three understated, in the same direction
- **What broke** — DoD "$500M+" against **>$1.2B**, and the largest fact was missing
  entirely: **DoD is MP Materials' largest shareholder at ~15%**. DOE HALEU tracked a
  $110M extension that expired 2026-06-30 while a **$900M task order** signed
  2026-07-01 went unrecorded. EU "€100M+" against **€22.5B** — a 225× error.
- **Why it survived** — No citation field existed anywhere in `policy.json`, so
  nothing invited re-checking.
- **Standing check** — Every quantitative claim carries a `sources` array. A figure
  with no source is a to-do, not a fact.

### 1.8 Two dead tickers served as live prices
- **What broke** — `AII.TO` and `CGEH` both froze at 2026-07-17 while `quotes.json`
  served their last prints as current. Both were **ticker migrations** (Almonty to
  Nasdaq `ALM`; Capstone uplisted to `CEPL`).
- **Why it survived** — A delisted instrument does not leave the feed; the provider
  keeps serving old history and pads a null bar at today's timestamp, so the last row
  looks current.
- **Fix** — Staleness measured from the last **non-null** close, drop over 14 days and
  name what was dropped. Tickers corrected, not removed.
- **Standing check** — Run the universe-wide staleness sweep on any pipeline change.

### 1.9 Lynas Seadrift: a "delay" that was a pivot
- **What broke** — The DoD program card said the Texas heavy-rare-earth plant was
  "targeted operational in FY2026", later softened to "status not confirmed". Both
  framings implied a schedule slip. The reality: Lynas told the market in 2025-08
  there was *"significant uncertainty as to whether construction … will proceed, and
  if so, in what form"*, and on **2026-03-16 the US Government redirected US$96M of
  construction funding to buying Lynas product from Malaysia instead**. The US-soil
  HREE separation capacity the card implied does not exist and has no date.
- **Why it survived** — "Not confirmed" felt honest, so nobody went and confirmed.
  A hedge is not a check. Also, Lynas's own "US Project Updates" page stops in
  2023-12 — an official page that has gone quiet reads as "no news" when it means
  "no longer maintained".
- **Fix** — Rewritten with the sequence and its thesis consequence; the page-source
  trap recorded in the entry's `verification` field.
- **Standing check** — A hedge ("not confirmed", "status unclear") is a to-do with a
  date on it, not a resting state. And check when an official status page was last
  updated before treating its silence as information.

### 1.10 CHIPS: "various stages of build" while one fab had run for two years
- **What broke** — The card listed four fab programmes as "in various stages of
  build". TSMC Arizona Fab 1 had been in N4 volume production since Q4 2024 and Intel
  Fab 52 since 2025-10. It also named "Samsung Austin" — Samsung's *legacy* fab; the
  CHIPS-funded one is **Taylor**.
- **Why it survived** — It carried an honest "spot-checked only" disclosure, and the
  disclosure did its job too well: it made the entry feel handled. See 1.9 — same
  mechanism.
- **Fix** — Per-fab status with a source and date on each. Wafer-per-month figures
  **withheld** because sources conflict by more than 2× on TSMC Arizona and the
  demand-pull thesis does not need them.
- **Standing check** — A "spot-checked" flag has a shelf life. Put a re-check date on
  it, or it becomes permanent.

---

## Class 2 — Figures that are arithmetically valid and meaningless

Near-zero denominators and unconverged recursions. Nothing crashes; the number is
simply not about what the label says it is about.

### 2.1 A −1,998% earnings surprise
- **What broke** — FLNC reported −$0.19 against a **+$0.01** consensus. The provider
  renders that as −1,997.7%. True, and useless.
- **Fix** — Percentages withheld below a |consensus| of $0.15, with the reason stated;
  the **cash beat/miss** is kept because it cannot be distorted.
- **Standing check** — Before displaying any ratio, ask what happens as the
  denominator approaches zero.

### 2.2 EV/EBITDA above 100× presented as a valuation
- **What broke** — BE, LEU, LYC.AX and MP showed 125×–305×. The multiple is measuring
  a near-zero denominator, not an expensive stock.
- **Fix** — Above 100× the figure renders amber with a note that it reads as
  pre-earnings, not as expensive. Negative EBITDA renders `n/m`.

### 2.3 A "52-week drawdown" computed from 37 sessions
- **What broke** — CGEH had 37 bars. The pipeline computed drawdown from the highest
  close *available*, the UI labelled it "52w drawdown", and the alert engine fired
  **"−27.6% below 52w high — entry window"**. A five-week pullback read as a
  year-long de-rating.
- **Why it survived** — Every layer was individually reasonable; only the composition
  was false. This one **fabricated a signal** rather than hiding one.
- **Fix** — Quotes carry `bars` and `dd_full`. Entry-window and froth-vs-high alerts
  are gated on real history and the suppression is **logged by name and bar count**.
- **Standing check** — A label naming a window (52-week, all-time, YTD) must assert
  that the window exists in the data.

### 2.4 Recursive indicators not reproducible on short history
- **What broke** — On a 33-bar name (GOGL), our EMA21 and pandas `ewm(adjust=False)`
  disagreed by **1.27pp**, and RSI by **7.7 points**. Both arithmetically correct;
  the difference is purely the seeding convention.
- **Why it survived** — It only appears when you recompute with a *different* code
  path. A second copy of the same convention agrees perfectly and proves nothing.
- **Fix** — EMA, RSI and ATR withheld below **5× their period**. Plain SMAs are
  unaffected — computable or not.
- **Standing check** — Distinguish indicators that are *undefined* on short history
  from those that are *seed-dependent*. The second kind is the dangerous one.

### 2.5 ATR sanity — the failure that hides a big day
- **What broke (pre-empted)** — An ATR larger than half the share price means the ATR
  predates a split or consolidation while the price does not. Left in, it divides a
  real move by a nonsense denominator and buries the name at `0.0×`.
- **Why this matters** — The failure **hides** a big day rather than inventing one,
  which is the harder kind to notice.

### 2.6 No noise floor on relative performance
- **What broke** — vs-market and vs-sector figures were coloured green or red at any
  magnitude. A +0.03pp relative move was rendered as outperformance.
- **Fix** — Below a fifth of the name's own typical daily move the figure reads
  "little changed" in grey. This affected **~50 of 167 rows** on each column.

### 2.7 A market cap on a dead ticker that did not match its own last close
- **What broke** — The `CEPL`/`CGEH` "discrepancy" was carried as an open risk for
  three weeks. Resolving it from primary data took ten minutes: shares outstanding
  were unchanged (32.2M → 32.6M), and CEPL opened at $9.75 against CGEH's last $9.85
  — the gap was a ~50% price fall *after* listing. But the "~$381M" figure that made
  it look structural was the data provider's market cap on the dead CGEH symbol, and
  **it did not even equal price × shares for that symbol** (9.85 × 32.2M ≈ $317M). It
  was from some earlier date than the last close.
- **Why it survived** — I recorded the observation "deliberately unexplained" as if
  that were rigour. It was deferral. Two numbers from the same provider on the same
  symbol were assumed to be from the same moment.
- **Fix** — Caveat rewritten with the reconciliation. Also noted: web searches for
  this name return filings from **Capstone Holding Corp** (CIK 887151), a different
  issuer — one result about a reverse-split authorisation nearly got imported.
- **Standing check** — On a delisted symbol, every derived field (market cap, P/E,
  float) is unreliable, not merely stale — cross-check against price × shares. And
  confirm the CIK before importing anything from a search on a common company name.

---

## Class 3 — Data written but never rendered

The data layer and the view layer drift apart silently. The JSON is right, the page
is wrong, and nothing errors.

### 3.1 A `scope` field that existed only in the file
- **What broke** — The FCC regime's `scope` field (EV chargers, wind, data centres)
  was written to `policy.json` and never rendered. `buildPolicy()` read only eight
  fields.
- **Standing check** — After adding a field, assert it appears in the rendered DOM,
  not just in the file.

### 3.2 `data_caveat` — six records, zero renders, and I kept adding more
- **What broke** — Found immediately after writing 3.1, by checking whether the class
  had other instances. Six records carried a `data_caveat` field and `index.html`
  referenced it **zero times**. Among them FLNC's caveat that its inverter
  manufacturing location is unverified — the single most FCC-exposed name in the
  book — written earlier the same day in the belief it was visible to a reader.
- **Why it survived** — Writing a field feels like publishing it. Nothing errors, the
  JSON validates, and the drawer looks complete because you do not miss a block you
  never saw. I then added two MORE caveats to the same invisible field while
  migrating tickers.
- **Fix** — Rendered as a warn-bordered block in the company drawer; verified all six
  appear and that a name without one renders no empty block.
- **Standing check** — When you find one unrendered field, **grep the renderer for
  every field name in the schema**. This class does not occur alone.

### 3.3 The flash card's upgrade path was dead code
- **What broke** — `wnWire()` branched on `e.reported` to swap "figures not published
  yet" for "confirmed figures". **Nothing ever wrote that field.** Every flash card in
  the app's history showed the wires-only caption regardless of whether figures had
  landed.
- **Why it survived** — The branch is invisible when the flag is never set; the
  fallback is a plausible sentence.
- **Standing check** — For any conditional in the view, confirm a writer exists for
  the condition. A branch nothing can reach is a bug, not a safeguard.

### 3.4 `metrics.json` was orphaned, not stale
- **What broke** — Diagnosed as "stale since 2026-04-30". The real finding was worse:
  **the app never loaded it.** 24 records, every valuation field null, and a
  capex-cycle read on 20 names — the book's primary selection criterion — invisible.
- **Standing check** — Periodically diff `ls data/*.json` against what `loadData()`
  actually fetches.

### 3.5 A ticker rename leaves every generated file carrying the old symbol
- **What broke** — Found while writing this log. After correcting `AII.TO`→`ALM` and
  `CGEH`→`CEPL` in `companies.json`, `quotes.json` still held the two **dead**
  symbols with their frozen prices, and held **no entry at all** for the two live
  ones. The Companies tab would have shown the new names priceless and the old ones
  as though trading.
- **Why it survived** — Hand-editing the universe is instant; the generated files
  only catch up on the next full pass. Between those two moments the repo is
  internally inconsistent and nothing says so. I created this defect in the same
  session I fixed the underlying one.
- **Fix** — Ran a full pipeline pass. Verified afterwards that the dead symbols are
  absent from `quotes.json`, `ALM` carries 251 bars with `dd_full: true`, and `CEPL`
  carries 28 bars with `dd_full: false` and is correctly excluded from the trend
  ladder and named in its drop list.
- **Standing check** — **Editing a ticker in `companies.json` is not complete until a
  full pass has run.** After any universe edit, assert that no removed symbol and no
  added symbol is missing from `quotes.json`.

### 3.6 The nightly workflow's `git add` list went stale twice
- **What broke** — The workflow staged an explicit file list. `metrics.json` and both
  trends files were generated by the pipeline and **never committed**.
- **Fix** — Stage `data/` wholesale; the workflow runs on a clean checkout.
- **Standing check** — Prefer directory-level staging over enumerations that must be
  maintained in a second place.

### 3.7 The schema sweep: 14 fields written and never rendered
- **What broke** — Acting on 3.2's standing check, I swept every field in every
  hand-maintained data file against the renderer. **14 fields had never been
  referenced.** The two that mattered:
  - **`impact` on all 8 policy regimes** — the "why it matters to this book"
    paragraph on every regime card, including the CORRECTED copper mechanism written
    hours earlier explaining that the previous conclusion was backwards. Invisible.
  - **`date_note` on 4 levers** — the honest dating annotations ("this window has
    passed with no outcome", "this is a placeholder, not an announced date").
    Invisible, which is worse than absent: the point of those notes is to stop a
    reader trusting a date.
- **Why it survived** — Same as 3.1 and 3.2. Writing to JSON feels like publishing.
- **Fix** — Both rendered. The remaining 12 are internal keys (sort keys, colour
  tokens, ids) and are fine unrendered.
- **Standing check** — Run the sweep as a periodic audit, not only when a specific
  field is suspected. Three separate instances of this class were found in one
  session, two of them by looking rather than by noticing.

### 3.8 A tab that told the reader it was sorted, and was not
- **What broke** — The Critical Minerals tab printed, in a note-box: *"Sorted by gap
  priority — most designated and least held first — not alphabetically."* **There was
  no sort.** Rows rendered in file order. The code comment above the function made
  the same false claim. Five minerals I appended that day therefore sat at the bottom
  regardless of being the least-covered entries on the map.
- **Why it survived** — The claim and the implementation live in different places,
  and file order looked deliberate enough to pass. This is the purest form of the
  pattern at the top of this file: a confidently phrased sentence that was false.
- **Fix** — Sorts on gap severity first, `priority` as tiebreak. NOT on `priority`
  alone: it was scored at different times on different scales (original no-exposure
  entries at 12, ones added 2026-08-11 at 34–37), so ranking on it alone would order
  rows by **when they were written** rather than by exposure. Re-scoring is owner
  judgment, so the code works around the inconsistency and says why.
- **Standing check** — **Any sentence describing the page's own behaviour is a
  testable assertion.** Assert it in the browser: the check here walks the rendered
  rows and fails if a covered mineral precedes an uncovered one.

### 3.9 A value-level sweep found four whole blocks the name-level sweep had passed
- **What broke** — `scripts/audit_schema.py` reported clean while four blocks of
  research had never been rendered: the **geopolitical actor map** (44 cells — "which
  chain stages China actually controls", promised by the learning path), the
  **Portfolio four screening questions** (the learning path tells the reader to "work
  through" them) and its catalyst table, `matrix.integrated_companies`, the two
  `source_note` provenance entries — and `levers[].sources`, which I had added that
  morning and not rendered, the fourth time this session I wrote to a field
  believing it was visible.
- **Why it survived** — The name-level sweep has two blind spots. It walked only
  top-level record keys, so `themes[].items[].why` and `portfolio.four_questions[].q`
  were never tested. And a field name read by *any* builder passes for *all* files:
  `why` renders on Picks & Shovels, so it "passed" everywhere. A tool that reports
  clean is more dangerous than no tool.
- **Fix** — All rendered. `audit_schema.py` now walks every level and top-level
  scalars, and says its remaining limit out loud. `scripts/dom_field_sweep.js` tests
  **values** against the rendered page — every tab, every heat-map row, every theme
  detail, every drawer — which catches both blind spots by construction. It also
  corrects two probe errors of my own: `innerText` excludes hidden panes (only the
  active tab was being tested), and data with `<b>` markup never matches
  `textContent` unless tags are stripped first.
- **Standing check** — Run the static sweep on every change and the DOM sweep on
  every audit. A miss the DOM sweep cannot explain is a bug, not noise; a pane it
  cannot open is a gap in the sweep to fix, not a reason to dismiss the miss.

---

## Class 4 — Asserting without checking

My own reasoning failures. Each produced a confident, wrong statement.

### 4.1 Claiming absence without searching
- **What broke** — Reported "no listed Western pure-play found" for several critical
  minerals, based on a memory-derived candidate list. A per-mineral search found
  Almonty, 5N Plus, AMG, Tharisa and Orbia. Coverage went from 19 uncovered to 4.
  Separately, marked Chinese producers as not investable — CMOC, China Northern Rare
  Earth, Huayou, Xiamen Tungsten, Chalco, Ganfeng and Zijin are all listed and priced.
- **Standing check** — "None exists" requires a search, per item, every time.

### 4.2 Estimating a figure instead of computing it
- **What broke** — Claimed Bloom Energy's relative-value case had "substantially
  closed" at 30–40× revenue. Actual: $64.6B / $3.11B = **20.8×**. The user's original
  figure was essentially right.
- **Standing check** — If two numbers are in the session, divide them.

### 4.3 Over-correcting the user from a paraphrase
- **What broke** — Told the user their `DC↔AC` framing "under-scoped" the FCC rule.
  The adopted text opens *"any **bi-directional** power device or system"*. Their
  framing was right; I had trusted a law-firm summary that dropped the qualifier.
- **Standing check** — Before correcting the user, confirm the source is primary. A
  paraphrase is evidence about a paraphrase.

### 4.4 Reporting a workflow had "never fired"
- **What broke** — It had fired, and failed. I read absence of success as absence of
  execution.

### 4.5 Nearly "fixing" something correct
- **What broke** — `08:30 EDT (04:30 PM your time)` looked wrong. The browser is
  Asia/Dubai, UTC+4. The conversion was correct.
- **Standing check** — Before fixing an oddity, reproduce it and confirm it *is* one.
  Establish which side is wrong. See 6.2.

---

## Class 5 — Renderer and layout traps

### 5.1 An array insert that killed every tab
- **What broke** — Three macro cards were appended into `const models=[` instead of
  `const drivers=[`, and the previously-final entry had no trailing comma. The whole
  script block failed to parse, so **no tab rendered at all**.
- **Standing check** — Brace-balance the concatenated `<script>` contents after every
  scripted edit, then load the page and read the console.

### 5.2 CI broken by concatenating the two HTML copies
- **What broke** — `node --check` ran over both copies joined, colliding on every
  top-level `const`.
- **Fix** — Check each file separately.

### 5.3 Two HTML copies synced by hand
- **What broke** — Nothing yet — they were byte-identical modulo the data path. That
  is luck, and the failure mode is silent: two dashboards that disagree with nothing
  on the page saying which is stale.
- **Fix** — `index.html` is the source, `widgets/widget_combined.html` is **generated**
  by `scripts/sync_widget.py`, and CI fails on drift. Drift detection was itself
  tested by appending a byte and confirming a non-zero exit.

### 5.4 Inner element overriding its wrapper's colour
- **What broke** — Signed figures set colour on the wrapper span, but the inner `<b>`
  reset it to the default text colour, so beat/miss rendered grey instead of red/green.
- **Standing check** — Read back `getComputedStyle` on the element that actually
  carries the text, not the one carrying the style.

### 5.5 A badge that contradicted its own row
- **What broke** — The "China-restricted" badge and filter fired on any non-empty
  `china` field, including rows whose text read *"not a supply chokepoint"*.
- **Fix** — Restrictions live in `china`; dominance, consumption and ownership live in
  `china_context` and render without a badge.
- **Standing check** — Assert programmatically that no badged row contains text
  contradicting the badge.

### 5.6 Linkifier rewriting inside HTML attributes
- **What broke** — `linkifyTickers` matched ticker text inside tag attributes,
  corrupting markup. Fixed by splitting on tags before substituting.

### 5.7 Tab order coupled by index
- **The trap** — `ST()` pairs `TAB_IDS` to `.tab` spans **by index**. Insert a tab in
  one place and not the other and every subsequent tab opens the wrong pane.
- **Standing check** — Click all tabs programmatically and assert the matching pane is
  visible. Keep the Start Here learning path in the same order.

---

## Class 6 — Verification that proves nothing

### 6.1 A replay that shares the original's assumption
- **The trap** — In the source method this dashboard borrows from, a Python replay
  reproduced the page's state counts exactly — because it had reimplemented the *same
  wrong* settled-close rule.
- **Standing check** — `verify_trends.py` deliberately does **not** import
  `trends.py`. It recomputes with pandas (a different code path) and, for judgement
  calls, **prints the raw dated bars** so verdicts are checked against inputs.

### 6.2 The verifier was wrong, not the page
- **What broke** — Full verification reported GOGL `ema5x21: page=None raw=bear`. The
  page was **right** — that rung depends on EMA21, correctly withheld at 33 bars. The
  verifier computed it unconditionally.
- **Why this matters** — The tempting move is to change whatever makes the test pass.
- **Fix** — The verifier now asserts the value *is* withheld where the raw series
  cannot support it.
- **Standing check** — On disagreement, work out which side is wrong before editing.

### 6.3 The settled-close trap
- **The trap** — A bar is still forming only if it belongs to the session running
  **right now**. Testing "has the current session ended?" is a different question:
  with markets shut, the newest bar is usually a completed close from an earlier
  session and gets wrongly discarded as live. In the source method this hit 52 of 72
  symbols and ran the whole rule set a session late.
- **Implementation** — `settled = NOT (lastBar >= sessionStart AND now < sessionEnd)`.
  16 Asia-Pacific names correctly had a forming bar dropped on the first run.

### 6.5 A `try/except: pass` that switched off the front door's recency gate
- **What broke** — News dates were stored as `published[:10]`, which on an RFC-2822
  string (`"Thu, 03 Sep 2026 …"`) yields **`"Thu, 03 Se"`**. That rendered verbatim in
  the News tab and every drawer — it looked like a deliberately short date, so no
  one questioned it. Downstream, the headline classifier's `date.fromisoformat()`
  failed on every item inside a `try/except: pass`, which meant **the 3-day/8-day
  recency window described in `breaking.json`'s own metadata never applied to a
  single headline**. 0 of 48 stored dates were parseable when caught.
- **Why it survived** — Two separate camouflages. The broken date *looked* like a
  format choice. And the gate failed *open*: an exception path that continues
  produces the same output as "no articles were too old", so the Act Now tab looked
  plausible on every quiet day. Found only by reading the raw record behind one
  signal, not by anything on screen.
- **Fix** — Dates parsed from `published_parsed` (or RFC-2822) to ISO. An article
  whose date cannot be parsed now has an *unknown* age and is **excluded and
  counted** ("N excluded as undated" appears in the checks list) rather than passed.
- **Standing check** — A guard that fails open is not a guard. When an exception
  path leads to `continue`/`pass`, ask what the output looks like if it fires on
  every record — if the answer is "normal", it will hide for months.
  `verify_breaking.py` now re-derives every headline signal's age from `news.json`.

### 6.4 Instrument readings that were misleading
- **What broke** — `getBoundingClientRect` reported all five mobile drawer icons
  offscreen; the screenshot showed them rendering correctly.
- **Standing check** — When a measurement and a screenshot disagree about something
  visual, trust the screenshot and find out why the measurement lied.

---

## Class 7 — Timezone and symbol-convention mismatches

### 7.1 Tokyo names labelled EDT
- **What broke** — `SESSIONS` is keyed on Yahoo suffixes (`.T`) but classification ran
  on our convention (`.JP`), so the lookup missed and fell through to the US default.
- **Fix** — Normalise through `yahoo_symbol()` before the session lookup.
- **Standing check** — There are **two** ticker conventions in this repo. Every lookup
  keyed on a suffix must state which one it expects. `yahoo_symbol()` is mirrored in
  the app JS as `yahooSymbol()` and the two must stay identical.

### 7.2 Ranking against the wrong tape
- **The trap** — Comparing a Tokyo name's move to the S&P measures the wrong market.
  `MARKET_INDEX` maps each listing venue to its local index, **keyed by name in a
  dict** rather than by position — positional maps over the same case space have
  silently mismatched rows before.

### 7.3 A ticker is not a word
- **What broke** — The Act Now front door showed a **company-critical signal on
  Cheniere** for *"Japan Bank for International Cooperation Launches Investigation
  of Freeport LNG"* — Freeport LNG is a private company. The headline classifier
  attributed tickers by matching every universe symbol as a bare whole word, so the
  commodity word "LNG" hit Cheniere's ticker. Four LNG-market headlines were
  attributed to Cheniere at the time; **80 tickers in this universe are ≤3 letters**
  (AA, AR, BE, CAT, DE, HP, ICE, MP, NE, RIG, TT, VAL …) and all were exposed.
- **Why it survived** — Whole-word matching feels precise. It is precise about
  *strings*, not about *meaning*, and the app already knew this — `AMBIGUOUS_TK`
  exists in the linkifier for exactly LNG and CF — but the pipeline never got the
  rule. Same knowledge, two places, one applied.
- **Fix** — Attribution now matches on the **company name** (full, or
  suffix-stripped when ≥5 chars). Bare tickers count only at 4+ characters or with
  an exchange suffix; short ones only in explicit forms — `(LNG)`, `$LNG`,
  `NYSE: LNG`. Names ≤3 chars (SQM, ICE, CSX) attribute *only* from the explicit
  form, by design: a false negative is the cheaper error on the front door.
- **Two data defects surfaced by testing the rule**: Cheniere was stored as
  `"Cheniere Energy (LNG)"` — the prose ticker convention leaking into the `name`
  field — and H&P as its 3-letter nickname, which no prose rule can ever match.
  Both normalised; `"Nokia (ex-Infinera)"` would have failed the same way and the
  key derivation now strips any trailing parenthetical.
- **Standing check** — `verify_breaking.py` prints, for every headline signal, the
  exact substring that justifies each attributed ticker, using a deliberately
  cruder rule than the pipeline's. Any attribution it cannot justify fails the run.

---

## Class 8 — Git and pipeline mechanics

### 8.1 Rebase refuses on a dirty tree, twice
- **What broke** — The nightly workflow ran `git add` after `git pull --rebase`. Fixed
  the order; it then failed again because the pipeline touched a file not in the add
  list (`calendar.json`).
- **Fix** — Commit before pulling, then `git checkout -- .` to discard remaining
  regenerated output before the rebase. Now also stages `data/` wholesale (3.4).

### 8.2 Conflicts with the nightly bot on generated data
- **What broke** — Committing while the scheduled workflow had just pushed produced
  conflicts across five generated JSON files.
- **Resolution** — These are regenerated outputs: take the local copy, then re-run the
  pipeline so the committed state is genuinely current.

### 8.3 `__pycache__` tracked in git
- **Fix** — Added to `.gitignore` and untracked.

---

## Class 9 — One fact, many copies

A correction is applied where the error was *found*, and the same sentence lives on
in every other file that repeated it. Distinct from Class 1: the fact was already
known to be wrong.

### 9.1 The "50% rule" survived its own correction in four places
- **What broke** — On 2026-08-11 the REE "extraterritorial 50% rule" claim was
  corrected in `policy.json` (threshold 0.1%, and suspended). Three weeks later the
  original wording was still live in **`geopolitical.json`, `annotations.json`,
  `portfolio.json`, and hardcoded prose in `index.html`** — four copies, including one
  that renders on the Geopolitical heat map with a weaponisation score of 5 justified
  by it.
- **Why it survived** — The audit was file-scoped. Nothing connected "this claim is
  wrong" to "where else is this claim". The research prose repeats key facts across
  tabs by design, so any single correction is a minority of copies.
- **Fix** — All four rewritten inline with the correction stated. The Seadrift
  "delay" (1.9) had the same shape: corrected in the DoD program entry, still cited as
  "first Western HREE capacity" in the REE heat-map entry.
- **Standing check** — **A correction is not done until the distinctive tokens of the
  old claim have been grepped across every data file and `index.html`.** The sweep
  script from this session (patterns for each corrected claim, excluding contexts
  containing "previously/corrected/CORRECTION") should be re-run after any audit;
  it found this in seconds.

### 9.2 Figures that were wrong in the heat map, right next to a score built on them
- **What broke** — `geopolitical.json` heat-map detail carried: South Africa "~40% Rh"
  (it is **~80%** — rhodium is *more* concentrated in South Africa than platinum, and
  the card implied the reverse); Chile "20–30% state participation" (the 2023 strategy
  requires a **state majority** in strategic salars; no such percentage exists); China
  copper smelting "~40%" (**~50%**); DRC cobalt "~65%" (**~72%**); "Kazatomprom
  controls ~40% of global uranium" (true only for **Kazakhstan on a 100%-operated
  basis** — Kazatomprom's attributable share is ~20%); EXIM Perpetua loan "$2.7B"
  (**$2.9B**, approved 2026-05-21).
- **Why it survived** — Numbers inside prose next to a 0–5 score read as the
  *justification* for the score, and the score is what the eye lands on. Nobody
  re-derives the justification of a number they agree with.
- **Fix** — Each corrected inline with the basis and the previous value stated, so a
  reader can see the change. Scores untouched — they are the owner's judgment.
- **Standing check** — Every percentage that names a *share* must name its basis
  (country vs company; attributable vs operated; production vs reserves vs capacity).
  Half of these errors were basis confusion, not bad data.

### 9.3 Thirty-three occurrences, four files deep, of numbers nobody could source
- **What broke** — The first pass over `themes.json`, `electricity.json`,
  `picks-shovels.json` and the entries they share with `matrix.json`, `explainers.json`
  and `explorer.json`. Three market-share percentages had **no source at all** and
  were withdrawn — Quanta "~40% of US grid construction" (7 copies), Halliburton
  "~40% of US fracking" (2), Energy Recovery "~50%" (3); only "largest" is
  supportable for each. Three had the **wrong basis**: Constellation "~10% of US
  electricity" is ~10% of US *carbon-free* electricity (3 copies); the TMI PPA
  "$110/MWh" is a *Jefferies estimate* of $110–115, the price is undisclosed (8
  copies across 5 files); "380GW offshore wind by 2030 … locked in regardless of
  policy" is a GOWA *target* — GWEC's own forecast was ~234GW (3 copies). Three were
  simply off: VSMPO was ~60% of Airbus, not ~35%; recycled copper is ~32% not ~35%
  and is not "almost entirely Western" (China is the largest scrap importer); PGM
  autocatalyst recycling is ~20–25% of supply, not 30–40%. Franco-Nevada "$30B+" is
  ~$51B — true, and 40% understated.
- **Why it survived** — A round number with a tilde in front of it reads as a
  considered estimate. Nobody asks where "~40%" came from because the tilde already
  concedes imprecision; it does not concede *absence of a source*, which is what it
  was hiding three times here. And the same sentence had been pasted into up to five
  files, so any one reader saw it corroborated by the others.
- **Fix** — Every occurrence rewritten in place with the basis and the previous
  value visible ("previously shown here as …"). Unsourceable percentages withdrawn,
  not softened.
- **Standing check** — **"~N%" needs a source exactly as much as "N%".** And the
  claim-repetition count from this session is the map: before editing any figure,
  count its copies across `data/*.json` and `index.html` and fix them as one change.

### 9.4 Research prose hardcoded in `index.html` — outside every data audit
- **What broke** — The tail of `buildGeo()` is a "Key chokepoints" block written
  directly into the JavaScript template, dated 2026-08-03. It still said *"China
  banned [antimony] exports Oct 2024"* — the exact claim corrected in `policy.json`
  on 2026-08-11 — and repeated the Kazatomprom "40% of mining" without its basis.
  The Class 9 sweep that had just caught the "50% rule" in four places **missed this
  one**: its pattern matched `\bban\b`, and the text said "banned".
- **Why it survived** — Every audit in this repo iterates `data/*.json`. Prose that
  lives in `index.html` is invisible to all of them, and it is the prose most likely
  to be stale because nobody thinks of a renderer as a place claims live. Twenty
  labelled claims are hardcoded there.
- **Fix** — Both lines corrected; header re-dated. The other hardcoded claims are
  listed in this entry's discovery script output and are on the open-risks table
  until each is sourced or moved into a data file.
- **Standing check** — Class 9 sweeps must include `index.html`, and their patterns
  must match inflections (`ban|banned|banning`). Longer term: **prose belongs in
  data files**, where the audits can see it. Hardcoded research text in the renderer
  is a defect in itself.

### 9.5 A whole theme item built on a claim removed four weeks earlier
- **What broke** — "HALEU for next-gen naval fuel" was removed from `policy.json` on
  2026-08-11 as unsubstantiated. The Defense theme in `themes.json` still carried an
  entire item on it: label *"Uranium — naval nuclear propulsion"*, rationale *"US
  Navy's nuclear-powered fleet requires enriched uranium fuel. HALEU is needed for
  advanced naval … designs."* Naval reactors run on HEU that NNSA supplies from excess
  weapons material, sufficient into the 2050s (GAO-26-107385). No listed name sells
  the Navy fuel. The item was not a phrase to fix; its thesis was false.
- **Why it survived** — The sweep pattern that caught the "50% rule" in four files
  looked for `HALEU … naval` within 60 characters; here the words sat in different
  fields of the same record. And my exclusion filter for "already-logged corrections"
  clipped its context window mid-word ("REMOVED" → "MOVED"), so five real
  corrections showed up as live while this real one was nearly lost among them.
- **Fix** — Rewritten onto the defense angles that hold: NNSA's unobligated
  enrichment need for tritium (FY2026 Defense Fuels Program names the AC100 —
  Centrus's centrifuge), Project Pele's TRISO/HALEU microreactor (BWXT), and the
  Russian import ban. Not removed — the owner's rule — but no longer wrong.
- **Standing check** — When a *claim* is removed, search for its *premise* as well as
  its wording: "naval" alone would have found this in seconds. And a Class 9 sweep's
  exclusion filter must widen its context window enough to see the whole correction
  sentence, or it will cry wolf on the fixes and drown the one live copy.

---

## Open and recurring risks

Not yet fixed, or fixed in a way that needs watching.

| Risk | Status |
|---|---|
| ~~`CEPL` price/market cap does not reconcile with `CGEH`'s last print~~ | **Closed 2026-09-05** — shares unchanged (32.2M→32.6M); it was a ~50% post-listing price fall. See 2.7. |
| ~~Lynas Seadrift "targeted operational FY2026" — status not confirmed~~ | **Closed 2026-09-05** — not a delay, a pivot: construction funding redirected to offtake in 2026-03. See 1.9. |
| ~~CHIPS Act regime spot-checked only~~ | **Closed 2026-09-05** — verified per fab. "Samsung Austin" was the wrong fab; one fab had been in volume production for ~2 years while the card said "various stages of build". See 1.10. |
| `verify_trends.py` requires network, so it is a manual/dev tool and **not a CI gate**. Nothing automatically re-checks trend maths. | Structural |
| Weekly/monthly frames are precomputed, so the whole file loads on first toggle. | Accepted trade-off |
| `conviction` and `froth` are owner judgments; the `tracked` tier explicitly does **not** carry one. Do not let coverage read as conviction. | By design — keep visible |
| Two ticker conventions (ours vs Yahoo) remain a live source of lookup bugs. | Structural |
| `themes`, `electricity`, `picks-shovels`, `geopolitical` now carry corrections and sources **inline in prose** and a `_meta.verification` block, but no per-record `sources` array like `policy.json` — adding one needs renderer support in four builders first, or it lands in Class 3. | Open — next chunk |
| Geopolitical heat-map detail renders only on click; corrections there are invisible until a row is expanded. | Known — by design, but worth a visual cue |
| ~20 research claims are hardcoded as prose in `index.html` (Orientation macro text, Geopolitical "Key chokepoints", mental-model cards). Outside every data-file audit. Two were stale on 2026-09-05. Move to data files or source each. | Open |

---

## Append template

```markdown
### N.N Short description
- **What broke** —
- **Why it survived** —
- **Fix** —
- **Standing check** —
```

Add the entry under the matching class. If it fits none, open a new class and add a
line to the pre-flight checklist if the check generalises.
