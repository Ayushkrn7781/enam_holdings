# Build prompt: FINN, a financial investment agent (one-shot build)

You are a senior full-stack AI engineer. Build, test and package **FINN**, a mobile-first investment-intelligence prototype for the ENAM Holdings "AI Engineer Build Challenge", **end to end in this session**. Write real code, run it, test it, look at the UI, fix what breaks, and finish with a working app, a passing test suite, an evaluation report, docs and one-command deployment. Do not stop at a plan.

Everything below is a specification of a build that has already been done and verified once. Follow it closely: the numbers, rules and scenarios are deliberate.

---

## 0. The brief in one paragraph

An investor drowns in prices, filings and results; the scarce skill is **filtering**. FINN has two modes:

* **Push** tells you what changed and why you should care: a windowed digest of exchange filings across a 15–20-stock NSE portfolio, prioritised, with routine items collapsed, plus threshold alerts.
  * For a **management change**, show the incoming person's background.
  * For **quarterly results**, give Revenue, EBITDA, PBT and PAT, QoQ and YoY.
* **Pull** is on-demand research on any NSE ticker, grounded **only** in primary documents (annual reports, concall transcripts, reported financials). No news, no broker notes, no model memory. The headline workflow is **Promise vs delivered**: management's guidance from the last four calls versus what was actually reported.

The grading criteria are creativity, product sense, judgment and architecture; thin-but-working beats broad-but-broken; the design must be mobile-first and carry no "AI slop"; cheap model routing and caching earn bonus points.

---

## 1. Non-negotiable principles

1. **The LLM never does arithmetic.** All growth, margins, ratios and scores are computed in Python (`Decimal`). A missing or zero denominator gives `N/A`, never an invented %.
2. **Never fabricate real data.** When live sources are unreachable, use a **clearly labelled illustrative demo dataset**: every row has `source="demo"`, every generated PDF page carries a watermark "ILLUSTRATIVE DEMO DOCUMENT - NOT A REAL COMPANY FILING - FIGURES ARE SYNTHETIC", the UI shows a "Demo data" badge, and people in demo filings are fictional. A live refresh must purge all demo rows so the two never mix.
3. **Every claim is evidenced.** Answers cite document, period, page, speaker and excerpt. If evidence is missing, say exactly: `I could not verify this claim from the available primary documents.`
4. **Works with zero API keys.** Every LLM feature has a deterministic fallback (rules classifier, extractive answers, rules-based guidance extraction).
5. **Explainable ranking.** The materiality score is a weighted sum of five rule-based components, each with a human-readable reason.
6. **Provenance everywhere.** Every table has a `source` column (`nse | bse | screener | yfinance | pdf | llm | demo`).

---

## 2. Stack

* **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 on SQLite (WAL mode; Postgres-compatible via `DATABASE_URL`), `rank-bm25`, NumPy, PyMuPDF (`fitz`), httpx, BeautifulSoup + lxml, yfinance + pandas (live data only), pytest.
* **Frontend:** React 18 + Vite + TypeScript + Tailwind 3 + Recharts + lucide-react, with font `@fontsource-variable/archivo` (`standard.css`, which carries both the weight and width axes). Hand-build the few UI primitives; don't pull in shadcn.
* **LLM:** **Google Gemini (free tier)** via its OpenAI-compatible endpoint `https://generativelanguage.googleapis.com/v1beta/openai`, env `GEMINI_API_KEY`.
* **Deploy:** one Docker image (Node build stage + Python runtime) serving the API and the built SPA from FastAPI, deployed to **Render** (free plan). Plus a `run.sh` that runs locally or deploys with one command.

---

## 3. Repository layout (create exactly this)

```
finn/
  run.sh  Dockerfile  render.yaml  .env.example  .gitignore  README.md
  docs/COVERING_NOTE.md
  backend/
    requirements.txt
    finn/
      __init__.py config.py db.py models.py universe.py demo.py seed.py refresh.py
      api/app.py
      connectors/prices.py nse.py screener.py
      services/llm.py numbers.py taxonomy.py materiality.py signals.py results.py enrich.py
               market.py digest.py alerts.py pipeline.py
      research/ingest.py retrieval.py answer.py guidance.py health.py periods.py
    eval/questions.json run_eval.py results.json
    tests/test_core.py
    seed/finn.db  seed/docs/demo/*.pdf          # prebuilt demo snapshot (committed)
  frontend/
    index.html vite.config.ts tailwind.config.js postcss.config.js tsconfig.json package.json
    src/main.tsx App.tsx index.css
    src/lib/api.ts format.ts router.ts
    src/components/ui.tsx Ask.tsx
    src/pages/Brief.tsx SignalDetail.tsx Portfolio.tsx Research.tsx Alerts.tsx Settings.tsx
```

---

## 4. Configuration (`config.py`)

* Read everything from env; hard-code nothing secret.
* `DATA_DIR = FINN_DATA_DIR or backend/data`; `DATABASE_URL` defaults to `sqlite:///{DATA_DIR}/finn.db`; `docs_dir = DATA_DIR/docs`.
* LLM settings:
  * `llm_api_key = GEMINI_API_KEY | GOOGLE_API_KEY | LLM_API_KEY`
  * `llm_base_url` defaults to the Gemini OpenAI endpoint.
  * `LLM_FAST_MODEL` and `LLM_STRONG_MODEL` are optional overrides.
  * `LLM_TIMEOUT_S = 60`
  * `LLM_MIN_INTERVAL_S = 4.5` (keeps under the free tier's ~10–15 requests per minute).
* Retrieval settings: `FINN_ENABLE_DENSE = 0` (optional fastembed), `FINN_EMBED_MODEL = BAAI/bge-small-en-v1.5`.
* Web settings: `CORS_ORIGINS = *`, `FRONTEND_DIST = ../frontend/dist`.
* `now_ist()` returns naive IST wall-clock time. **Store all exchange timestamps as naive IST.**

---

## 5. Data model (`models.py`; create with `create_all`)

* **Company:** `ticker` PK, `name`, `sector`, `is_financial` (banks/NBFCs), `about`, `source`.
* **Holding:** `ticker` unique → Company.
* **Price:** `(ticker, date)` unique; `open`, `high`, `low`, `close`, `adj_close`, `volume`, `source`.
* **Announcement:**
  * Raw fields: `ticker`, `published_at`, `subject`, `body`, `exchange_category`, `attachment_url`, `attachment_text` (pages joined by `\f`), `source`, `dedupe_key` (unique sha256).
  * Derived: `category`, `category_method`, `score`, `priority`, `score_breakdown` JSON, `summary`, `enrichment` JSON, `is_duplicate_of`.
* **FinancialPeriod:** `(ticker, period_type 'Q'|'Y', period_end, basis)` unique; `label` (e.g. "Sep 2026"), `basis` (consolidated/standalone), `unit = "INR crore"`, `metrics` JSON, `source`, `source_url`.
  * Metric keys: `revenue`, `expenses`, `ebitda`, `other_income`, `interest`, `depreciation`, `pbt`, `tax_pct`, `pat`, `eps`, `exceptional`.
  * Annual rows add: `net_worth`, `borrowings`, `cfo`, `cfi`, `fcf`, `debtor_days`, `inventory_days`, `payable_days`, `ccc`, `roce`, `roe`.
* **Document:** `(ticker, url)` unique; `doc_type` (annual_report | transcript | results | presentation), `title`, `period_label` ("Q2 FY27", "FY26"), `period_end`, `local_path`, `pages`, `status` (discovered | downloaded | indexed | failed), `error`, `source`.
* **Chunk:** `document_id`, `ticker`, `page`, `section`, `kind` (text | table), `speaker`, `text`, `embedding` (blob, optional).
* **Guidance:** `ticker`, `document_id`, `chunk_id`, `page`, `said_in` (call label), `statement` (verbatim), `speaker`, `metric` (revenue_growth | ebitda_margin | pat_growth | capex | volume | qualitative), `target_low`, `target_high`, `unit` ("%" | "INR cr"), `horizon`, `commitment` (explicit_target | range | outlook | qualitative), `method` (llm | rules).
* **AlertRule:** `ticker` (null = whole portfolio), `kind` (price_up | price_down | volume | category), `threshold`, `category`, `priority`, `enabled`.
* **AlertEvent:** `(rule_id, ticker, ref)` unique (ref like `px:2026-11-02` or `ann:12`); `triggered_at`, `message`, `value`, `announcement_id`, `seen`.
* **ResearchLog** (question, route, answer, latency) and **Meta** (key → JSON: `data_mode`, `source_status`, `triage`, `materiality_weights`, `ingest:<T>`).

**The LLM cache does NOT live in the main DB.** Use a separate SQLite file `DATA_DIR/llm_cache.db` accessed with raw `sqlite3`, a lock and a 5 s timeout, and swallow cache errors. (This build hit a real deadlock: an LLM call made inside an open write transaction tried to insert into the cache via another connection, and SQLite returned "database is locked".)

---

## 6. Universe (`universe.py`)

Twenty portfolio names across sectors and sizes, as `(ticker, name, sector, is_financial)`:

| Ticker | Sector | Financial |
|---|---|---|
| RELIANCE | Energy & Conglomerate | |
| HDFCBANK, ICICIBANK, SBIN | Banking | ✓ |
| INFY, TCS, KPITTECH | IT Services | |
| TMPV, MARUTI, M&M | Automobiles | |
| LT | Infrastructure | |
| ITC, HINDUNILVR | FMCG | |
| SUNPHARMA | Pharmaceuticals | |
| BHARTIARTL | Telecom | |
| NTPC | Power | |
| TITAN, ASIANPAINT | Consumer Discretionary | |
| DIXON | Electronics Manufacturing | |
| POLYCAB | Capital Goods | |

Tata Motors demerged in Oct 2025; the listed passenger-vehicle entity trades as **TMPV**.

Ad-hoc research names: TRENT (Retail), PERSISTENT (IT), HAL (Defence), BAJFINANCE (NBFC, financial), DMART (Retail).

The engine must work for **any** NSE symbol (`^[A-Z0-9&\-]{1,20}$`).

---

## 7. Deterministic maths (`services/numbers.py`)

* `growth_pct(cur, base) = (cur − base) / |base| × 100`, rounded to 0.1 with `ROUND_HALF_UP`; `None` if either side is missing or base = 0. Using |base| means a narrowed loss (−100 → −50) reads as +50%.
* `margin_pct`, `ratio`, `daily_return_pct = (close / prev − 1) × 100`.
* `volume_ratio = today / mean(trailing 20 sessions excluding today)`; `zscore`; `cagr_pct`.
* `fmt_cr` uses Indian grouping (₹12,34,567 Cr).

---

## 8. Push engine

### 8.1 Taxonomy and classifier (`services/taxonomy.py`)

Seventeen categories with base importance:

| Category | Importance |
|---|---|
| results | 90 |
| M&A | 85 |
| management_change | 75 |
| fund_raise | 70 |
| litigation | 70 |
| pledging | 70 |
| capex | 65 |
| credit_rating | 55 |
| bonus_split | 55 |
| insider_trading | 50 |
| press_release | 40 |
| dividend | 40 |
| earnings_call | 35 |
| agm_egm | 25 |
| postal_ballot | 20 |
| investor_meetings | 15 |
| unclassified (routine) | 5 |

Rules are ordered regexes producing `(category, subtype)`:

* **pledging:** `pledg|encumbrance`.
* **insider_trading:** `regulation 7(2)|insider trading|sast…`.
* **earnings_call:** `transcript` → subtype transcript; `audio/video recording` → recording; `earnings call|conference call|con. call|concall` → notice.
* **investor_meetings:** `analyst|institutional investor|investor meet|investor conference|non-deal roadshow|one-on-one`.
* **results:**
  * Board notice (`board meeting.{0,80}(consider|approve).{0,60}results|intimation of board meeting.{0,40}result`) → subtype board_notice.
  * Results proper (`financial results?|quarterly results?|unaudited…results|audited…results|results for the (quarter|year)|outcome of board meeting.{0,60}result|investor presentation|earnings (release|update)|shareholders' letter`) → subtype results.
* **M&A:** `acqui(re|sition)|amalgamation|merger|demerger|scheme of arrangement|joint venture|stake (sale|purchase)|divest|incorporation of…subsidiary|investment in…subsidiar`.
* **management_change:** `ceo|cfo|managing director|whole-time director|coo|change in (directors|key managerial|management)|resignation of|appointment of|cessation|re-appointment|company secretary|compliance officer`.
* **fund_raise:** `qip|qualified institution|rights issue|preferential|buy-?back|ncds?|non-convertible debenture|commercial paper|fund rais|raising of funds|issue of (equity|securities)`.
* **credit_rating:** `credit rating|crisil|icra|care ratings|india ratings…`.
* **litigation:**
  * Subtype regulatory: `usfda|form 483|warning letter|import alert|official action indicated`.
  * Subtype legal: `litigation|penalty|show cause|sebi order|tribunal|nclt|insolvency|court|arbitration|tax demand|gst…(demand|order)|regulatory action|search and seizure`.
* **bonus_split:** `bonus|stock split|sub-division`.
* **dividend:** `dividend`.
* **capex:** `capex|capital expenditure|capacity expansion|new (plant|facility|factory|unit)|greenfield|brownfield|commissioning|commercial (production|operation)`.
* **postal_ballot:** `postal ballot|e-voting result|scrutinizer`.
* **agm_egm:** `agm|egm|annual general meeting|book closure`.
* **press_release:** order wins (`order (win|received|inflow)|bags…order|letter of award|contract (award|win)|secures`) → subtype order; `press release|launch|partnership|collaborat|clarification|media release|update on` → subtype news.

**ROUTINE** regex, checked first, against subject plus exchange label: `trading window|esop|esos|esps|allotment of shares under|regulation 74(5)|compliance certificate|loss of share certificate|duplicate share|newspaper (publication|advertisement)|copy of newspaper|spurious|investor complaints|reconciliation of share capital|certificate under|brsr|business responsibility|sustainability report|esg|secretarial compliance|appointment of (statutory|secretarial|cost|internal) auditor|record date for interest|change in registrar|iepf`. A match gives `unclassified/routine`.

**Matching order:** test the subject first, then the exchange's own label, then the first 600 characters of the body. (Bug seen in this build: testing the exchange label first turned "Intimation of participation in an investor conference", filed under NSE's "Analysts/…/Con. Call Updates", into an earnings call.)

If still unclassified and an LLM is available, ask the **fast** tier for one category in JSON.

**Sub-type importance overrides** (each returns `(score, reason)`):

* results board_notice → 30.
* Management change: CEO/MD/CFO → 92; company secretary / compliance officer → 30; independent director → 45.
* Credit rating: downgrade or negative outlook → 85; upgrade or positive → 65; reaffirmed → 20.
* Fund raise: commercial paper → 30; buyback → 78.
* Pledge released → 40.
* USFDA: warning letter / import alert / OAI → 85; inspection observations → 60.
* Transcript → 45.
* Order win → 60.

`SCHEDULED_SUBTYPES = {board_notice, routine, meeting, ballot, meet, recording, notice}`.

### 8.2 Materiality (`services/materiality.py`)

`Materiality = 0.25·Category + 0.25·Financial + 0.20·Deviation + 0.15·Relevance + 0.15·Novelty`. Each component is 0–100 and carries a reason. Weights are editable (Meta `materiality_weights`, normalised to sum to 1).

Priority bands (prototype defaults): **critical ≥ 80, high ≥ 60, medium ≥ 35, low < 35**.

* **Financial impact:**
  * Results: `clamp(25 + max(|PAT YoY|, 1.5·|Rev YoY|) · 2.5)`.
  * Any other filing with a ₹ amount: `clamp(20 + 16·√(amount / annual revenue × 100) · 1.1)`. This puts L&T's ₹5,000 Cr order (≈2% of revenue) at *medium* and KPIT's ₹950 Cr acquisition (≈16%) at *critical*.
  * Amount without a revenue base → 45.
  * No amount → category default (management_change/M&A 50, litigation/credit_rating/pledging 45, else 15).
* **Deviation:** the max of:
  * the results surprise, `|z| · 30`, where z = the PAT-YoY z-score versus the company's previous ≤ 8 quarters (needs ≥ 3);
  * the price reaction, `|return_sigma| · 28`, on the first session on or after the filing (filings at or after 16:00 IST count for the next session);
  * the volume reaction, `(volume_ratio − 1) · 45`.

  With nothing available, deviation is 20. **Cap deviation at 25 when category importance < 40** (bug seen: a postal-ballot notice took credit for an unrelated −4.3% move).
* **Relevance:** 100 for a holding in a category you alert on (never for board notices); 75 for a holding; 25 for a non-holding.
* **Novelty:** `100·(1 − max Jaccard similarity)` against the same company's filings in the previous 90 days **with the same subtype only** (bug seen: comparing a results filing with its own board-meeting notice halved its novelty). Cap it at 70 if the same category was filed within 14 days. **Cap at 30 for scheduled subtypes**, and at 10 for unclassified.
* **Duplicates:** similarity > 0.85 within 2 days marks the filing as a duplicate (`is_duplicate_of`), with the score capped at 10.
* For unclassified filings, financial = 0 and deviation is capped at 20.

### 8.3 Signal pipeline (`services/signals.py`)

`process(force)` handles every unscored announcement in chronological order: classify → dedupe and novelty → enrich → components → score → summary → explanation → investigation questions. Wrap each filing in try/except so one bad filing never breaks the feed.

**Enrichment:**

* **Results (not board notices):**
  1. Parse the attachment PDF pages (§8.4); if that fails, the LLM reads the single most relevant page.
  2. Pick the structured quarter with `period_end ≤ published` and within 80 days of it, then `results_card(...)` + `reconcile(...)`.
  3. With no structured quarter, build the card from the filing alone (status `single_source`).
  4. The summary becomes `"Q2 FY27: revenue +38.0% YoY, PAT +47.5% YoY; EBITDA margin 4.0%."`.
* **Management change:** `enrich.management_change` (§8.5).
* **Amount:** the largest ₹ amount in subject plus text, in crore (`Rs.|₹|INR` with crore/cr/lakh/lac/million/mn/billion/bn).
* **Reaction:** the EOD snapshot on the reaction date.
* **Summary:** the fast LLM writes one sentence (≤ 28 words, concrete facts, no adjectives) for non-routine filings; otherwise use the cleaned subject.

**"Why should I care?"** is stored in `enrichment.why`:

* `what_happened`: facts, including every results row ("Revenue ₹20,500 Cr — QoQ +28.9%, YoY +38.0%"), people and amounts.
* `implication`: per-category template text, flagged as inference.
* `is_it_unusual`: the deviation and novelty reasons.
* `financial_size`.
* `history`: count and last date of same-category filings in 90 days, plus the last 8 quarters of PAT.
* `uncertain`: no attachment text, verification not passed, results flags, "bio as disclosed", no EOD reaction yet. Prefix "ILLUSTRATIVE DEMO DATA — not a real filing." for demo rows.

**Investigation questions per category:**

* results:
  * "Was the YoY change driven by volume, price or mix?"
  * "Did margins move because of input costs or one-offs/exceptional items?"
  * "How does this quarter compare with what management guided last quarter?"
* management_change:
  * "Is the departure planned succession or abrupt?"
  * "Does the incoming person come from inside the company or a peer?"
  * "Any other KMP changes in the last 12 months?"
* M&A: valuation, funding, mix. fund_raise: dilution, use of proceeds, D/E. Litigation, rating, pledging, capex, insider, press, dividend, bonus and earnings_call follow the same pattern.

### 8.4 Results intelligence (`services/results.py`)

* `periods(ticker, 'Q'|'Y')` prefers consolidated.
* `results_card(ticker, period_end)` returns, per metric (Revenue, EBITDA, PBT, PAT): current, previous quarter, same quarter last year, QoQ and YoY.
* Margins: EBITDA margin now, previous and a year ago, with the bps change YoY; PAT margin.
* Flags: exceptional items; other income above 25% of PBT.
* Trend: the last 8 quarters.
* **Labels are fiscal:** `quarter_label(period_end)` → "Q2 FY27" (Indian FY: FY27 runs 1 Apr 2026 – 31 Mar 2027, and Q1 = Apr–Jun). The card also carries `period_end_label`.
* For lenders (`is_financial`), EBITDA is N/A with the note "Not meaningful for lenders…".

**Deterministic SEBI-format PDF parser:**

* Find a page containing "before tax" and "revenue|income from operations".
* Units: lakh ÷ 100, million ÷ 10, else crore. Basis: "consolidated" in the first 1,500 characters.
* Row regexes allow optional prefixes (`(i)`, `1`, `a)`): revenue from operations / income from operations / net sales; other income; finance costs / interest expense; depreciation; `profit…before tax` (must NOT match "Profit before exceptional items and tax"); `(net) profit… (for the period|after tax)`.
* Numbers match `\(?-?[\d,]+\.\d+\)?` or Indian-grouped integers; parentheses mean negative. Take the first three numbers as current | preceding quarter | same quarter last year.
* `EBITDA = PBT + finance cost + depreciation − other income`. Prefer consolidated pages.
* `reconcile(card, filing)`: if every metric is within max(1, 2%), the status is **verified** ("Matches the results filing (p.2, consolidated) within 2%"); otherwise **mismatch** with the details and "check basis or restatement".

### 8.5 Management change (`services/enrich.py`)

SEBI LODR requires a "brief profile" of the appointee **in the filing**. Read the bio from there; do **not** scrape LinkedIn (its terms forbid it). Attach a LinkedIn people-search URL instead.

* **With an LLM:** the fast tier returns JSON `{people:[{name, role, change, effective, reason, profile ≤ 45 words}]}`.
* **Rules fallback:** find each `Mr./Ms./Mrs./Dr./Shri/Smt. <Name>`.
  * The change comes from the verb after the name: resign/tendered/cessation, retire, or appoint (in context). Skip names with no change attached.
  * Role regex; effective date after `w.e.f.|with effect from|effective (from)?`, optionally followed by "close of business hours on"; reason "to pursue …".
  * Assign the "Brief profile of <Name>:" paragraph to that person, or else to the appointee.
  * Sort appointments first.

### 8.6 Market (`services/market.py`)

`snapshot(rows)` returns date, close, return_pct, volume, avg_volume (20 sessions, excluding today), volume_ratio, return_sigma (vs. 20-day stdev), 1-year return, 52-week high/low, source. `reaction(rows, date)` gives the snapshot as of the first session on or after that date.

### 8.7 Alerts (`services/alerts.py`)

* Default rules:
  * volume ≥ 2× (high);
  * price up ≥ 4% (medium) and price down ≥ 4% (high);
  * category alerts for results (high), management_change (critical), M&A (high), fund_raise (medium), litigation (medium), credit_rating (medium), pledging (high).
* `evaluate()` checks the last 10 sessions per holding (that's the history) and category filings from the last 14 days relative to the digest anchor, skipping board notices and duplicates. The unique constraint stops duplicate events.
* Descriptions read like "Volume > 2× 20-day average, any holding" (no middle dots).
* Changing a threshold deletes that rule's events and re-evaluates.

### 8.8 Digest (`services/digest.py`)

* **Anchor:** in demo mode, the latest filing time + 1 minute; in live mode, `now_ist()`.
* **Window:** hours (24, 72, 168) or a custom start/end. Filters: tickers, sector, categories, min_priority; portfolio only.
* Sort by score. Material = critical, high or medium and not a duplicate; everything else is routine (collapsed).
* EOD moves: price and volume alert events in the window.
* Counts; top companies.
* **Headline + lines, assembled, never generated:**
  * The headline is `"N holdings need your attention"` (or "Nothing urgent. N updates worth a glance").
  * The lines are `[{label: category label, tickers: [...]}]` for critical and high items, plus "Unusual volume" and "Outsized price move".
* `serialize()` includes `breakdown` (contribution per component, which drives the UI strip) and `why_rank`: the reason of the stronger of financial and deviation if either value is ≥ 45, else the category reason, or "Duplicate… suppressed".
* Results items carry `results_preview`; management items carry `bio_preview`.

---

## 9. Pull engine

### 9.1 Ingestion (`research/ingest.py`)

1. Read PDFs as **text blocks** (`page.get_text("blocks")` joined by blank lines); this preserves paragraphs.
2. Drop running headers (short lines on ≥ 60% of pages, for docs with ≥ 3 pages) and furniture (watermark line, "Page x of y").
3. Group lines into blank-line-separated paragraphs. **A heading is a whole paragraph:** a single line ≤ 90 characters that either matches a known section name (MD&A, directors' report, auditor's report, notes, contingent liabilities, related party, key ratios, risks, outlook, segment information, business overview, financial performance, Q&A session, opening remarks) or is Title/UPPER case, 1–9 words, with no trailing punctuation and no 3+ digit numbers. Bug seen: line-level detection swallowed "Financial performance: Consolidated revenue…" as a heading, and "Moderator:" lines became sections.
4. Transcripts split on speaker turns: `^Name:` only, ≤ 5 words, with **no** dash separator.
5. Merge paragraphs into chunks of ≤ 1,100 characters. **Never cross a page, section or speaker boundary.** Number-dense blocks (> 35% numeric tokens) become `table` chunks. Very long paragraphs split on sentences. Drop chunks under 40 characters.
6. Invalidate the retrieval cache for that ticker.

### 9.2 Retrieval (`research/retrieval.py`)

* BM25Okapi over `section + text`.
* Tokenizer: lowercase alphanumerics and %, a stopword list, and a **tiny stemmer** (strip ments/ment/ings/ing/ions/ion/ies→y/ed/es/s for words longer than suffix + 3 letters).
* **Query expansion:**
  * revenue → sales, turnover, topline, income from operations
  * debt → borrowings, leverage, loans, debentures
  * margin → ebitda, operating profit, opm
  * guidance → outlook, expect, target, guide, aim
  * cash → cash flow, operating activities, free cash
  * risk → risks, threats, concerns, headwinds
  * capex → capital expenditure, capacity, investment, plant
  * profit → pat, net profit, earnings
  * business/does → operates, segments, products, overview, revenue mix
* Optional dense retrieval with fastembed (ONNX) when `FINN_ENABLE_DENSE=1`.
* Fuse with **Reciprocal Rank Fusion**, `1/(60 + rank)`.
* Metadata filters: doc_types, periods. Cache the index per ticker.
* `split_sentences()` must **not** split after `Rs.|Mr.|Ms.|Mrs.|Dr.|No.|Co.|Ltd.|vs.|approx.|e.g.|i.e.` (bug seen: "Rs. 1,000 crore" was split, breaking capex extraction and the number verifier).

### 9.3 Router and answers (`research/answer.py`)

The deterministic router checks these regexes in order:

* **guidance:** `guid|promis|deliver|target|outlook|forecast|commit|kept (their|its) word|credib|indicated|said (earlier|last)|\b(meet|met|hit|miss|missed|achieve|achieved|beat)\b.{0,40}(\d+\s*%|expectation|plan)`
* **quarters:** `last (four|4|few) quarters|quarter-on-quarter|compare.*quarters|quarterly trend|each quarter`
* **metric:** `^(what|how much|how many).{0,40}(revenue|sales|ebitda|pat|net profit|profit|margin|pbt)\b(?!.*\bwhy\b)|\b(qoq|yoy)\b|growth (in|of) (…)|(revenue|pat|profit|ebitda) growth`
* **health:** `\bdebt\b|leverage|borrow|cash flow|cash conversion|working capital|balance sheet|receivable|inventory|financial health|red flag`
* otherwise **narrative**.

Route labels shown in the UI:

* metric: "Structured financials · deterministic maths"
* quarters: "Structured financials · multi-quarter"
* guidance: "Transcripts → guidance vs. reported actuals"
* health: "Financial statements · health rules + filings"
* narrative: "Hybrid retrieval over annual reports & transcripts"

How each route answers:

* **metric:** a results card turned into lines like `**PAT** Q2 FY27: ₹1,170 Cr — QoQ +1.2% (vs ₹1,156 Cr in Q1 FY27), YoY +4.5% (vs … in Q2 FY26) [1]`, citing the financials table. Engine "deterministic".
* **quarters:** the last 5 quarters, with QoQ revenue, EBITDA margin and QoQ PAT.
* **guidance:** the scorecard interpretation plus up to 5 graded rows with verbatim quotes as citations.
* **health:** the overall label, plus the checks matching the question's pillar (debt → leverage, cash → cash quality, working capital/receivable/inventory → working capital, risk → disclosed risks), or else the flagged checks.
* **narrative:**
  * No indexed docs → `NOT_VERIFIED` + "No primary documents are indexed for this company yet — run document ingestion first."
  * Business-type questions (`what does .* do|business model|segments?|products?|revenue mix|customers`) search the annual report first.
  * No hits → `NOT_VERIFIED` + "Nothing relevant was found…".
  * **With an LLM:** fast tier for business questions, strong tier otherwise. The prompt allows only the numbered excerpts, requires `[n]` on every factual sentence, forbids outside knowledge and arithmetic, mandates the exact refusal sentence, and caps answers at 120 words. Then run `verify()`.
  * **Without an LLM:** an extractive answer, "Most relevant passages from primary documents (extractive — LLM not configured):", taking up to 2 best sentences per top-4 chunk (most query-token overlap, preferring sentences with digits), or else the lead sentences.

`verify(text, cites)`, per sentence:

* `[n]` must point at a real citation.
* Every number token (> 1 digit) must appear in the union of the cited excerpts (with commas stripped).
* Otherwise append `⚠︎ *unverified*`.
* Return counts and the unverified sentences.

**Confidence** is shown as factors and is explicitly *not* a probability: `0.3·retrieval_relevance + 0.3·evidence_coverage + 0.25·numeric_verification + 0.15·source_quality` (demo = 0.6), labelled high ≥ 0.8, medium ≥ 0.55, else low.

Log every answer to ResearchLog with its latency.

`overview(ticker)` returns:

* the business snapshot (annual-report retrieval, then a fast-LLM summary of ≤ 60 words with citations, or extractive, or `company.about`);
* the financial snapshot (latest FY: revenue, EBITDA margin, PAT and margin, ROE, ROCE, D/E; TTM from the last 4 quarters);
* the trajectory (annual series, revenue and PAT CAGR, and a takeaway like "Revenue compounded X% a year over N years; PAT Y%; EBITDA margin moved from a% to b%.");
* the latest quarter card.

`bull_bear(ticker)`:

* **With an LLM:** the strong tier, given computed health metrics plus numbered excerpts, returns JSON with 3 bullets each (≤ 22 words). Run `verify()` on each bullet.
* **Otherwise deterministic:** bull bullets come from "stable" quantitative checks, bear bullets from "elevated"/"monitor" ones (excluding text-detected disclosures) plus repeated guidance misses.

### 9.4 Promise vs delivered (`research/guidance.py`) — the flagship

**Extraction**, over the last 4 indexed transcripts (newest first):

* Candidate chunks match `guid|expect|target|aim\b|aspire|outlook|confident|we see|we should|should be|will be in the|range of|band of|trajectory|plan to|planning|capex|invest` and are not spoken by the moderator.
* **With an LLM:** the fast tier gets those chunks numbered with page and speaker and must copy statements verbatim, never turn vague language into numbers, and return JSON items with `chunk`, `statement`, `metric`, `target_low`/`target_high`, `unit`, `horizon`, `commitment`.
  * **Verbatim check:** after normalising (lowercase, non-word characters → space), the statement must be a substring of the chunk, or its longest match must cover ≥ 85% of it (difflib). Otherwise drop it.
  * If the LLM is absent, or *all* its items were dropped, use the rules extractor.
* **Rules extractor:** for each sentence (using the safe splitter) that matches the keyword regex plus a number (`%|percent|bps|crore|cr`):
  * Skip backward-looking sentences: those containing last year|was|were|grew|delivered|reported|achieved but none of expect|guid|target|aim|will|should.
  * **Targets:**
    * `X% to Y%` or `X–Y%` → (X, Y);
    * capex `Rs. N crore` → (N, N, "INR cr");
    * "double-digit" → (10, None);
    * single `X%` with at least|minimum|upwards of|more than|over|above|exceed → (X, None);
    * with around|about|approximately|~|close to → (X − 0.5, X + 0.5);
    * otherwise (X, X).
  * **Metric**, first match wins: ebitda_margin (ebitda/operating/ebit margin or margin), capex, pat_growth, revenue_growth (revenue/topline/sales/growth/grow), volume, else qualitative.
  * **Horizon:**
    * `Q[1-4] FYxx` → "Qn FYxx" (check this **before** FY);
    * `FYxx`;
    * next/coming/following quarter → `next_quarter(said_in)`;
    * this year/full year/current year → the FY of the call;
    * next year → FY + 1;
    * medium/long term or next 2–3 years → "medium term";
    * default: the FY of the call.
  * **Commitment:** guid|target|commit → range (if low ≠ high) or explicit_target; otherwise outlook. No number → qualitative.

**Grading**: compute the actual in Python.

* For **FYxx**, use the annual row. If it's missing, sum the 4 quarters of that FY; with fewer than 4 quarters it's "pending — k/4 quarters reported". Revenue/PAT growth is YoY; the margin is EBITDA ÷ revenue.
* For **Qn FYxx**, use that quarter: YoY growth or the quarter's margin; if not reported yet, pending.
* "medium term" → long_dated; capex → not comparable from reported financials.
* `_grade(lo, hi, actual)` uses a tolerance of **0.05 pp** (rounding only; bug seen: a 0.3 tolerance graded 3.7% as "achieved" against 4.0–4.2%):
  * hi = None ("at least") → achieved if actual ≥ lo, else missed;
  * above hi → exceeded; below lo → missed; otherwise achieved.
  * Qualitative statements get status qualitative.

**Revisions:** the same (metric, horizon) with a different target on a later call → `{direction up/down, from, to, from_call, to_call}`.

**Scorecard output:**

* rows (said_in, speaker, verbatim statement, metric label, target, horizon, commitment, actual, actual_period, how computed, variance, status, method, citation {document, page, url, period, source});
* summary (counts, hit_rate = met-or-beaten over graded, revisions, repeated misses (same metric missed ≥ 2), calls covered);
* chart rows (% targets with an actual): label, low, high, actual, status;
* uncertainties;
* interpretation: deterministic ("Of N gradeable statements: a met, b beaten, c missed. Revenue growth guidance for FY27 was revised down on the Q1 FY27 call (from 18–20%). Repeated misses on: Revenue growth."). If an LLM is available, the **strong** tier writes 3–4 neutral sentences from the *computed table only*, never accusing management of dishonesty.
* With no guidance: status `no_transcripts` or `no_guidance` plus an honest message.

### 9.5 Financial health (`research/health.py`)

A rule-based early warning; it is explicitly not a probability of default.

Each check returns `{pillar, metric, current, unit, history[(label, value)], direction rising|falling|flat (±5% of first), label stable|monitor|elevated|insufficient, interpretation, source, completeness}`, computed over up to 6 annual periods.

* **Profitability:**
  * Revenue growth: latest-year growth below −10 → elevated, below 0 → monitor; also report the CAGR.
  * EBITDA margin (non-financials): more than 5 pp below its recent peak → elevated; a drop of more than 1.5 pp YoY → monitor.
  * PAT margin.
  * ROE: below 10 → monitor.
  * ROCE (non-financials): below 12 → monitor.
* **Leverage** (non-financials):
  * D/E = borrowings ÷ net worth: above 1.5 → elevated; above 0.8, or up 0.3 over 3 years → monitor.
  * Interest coverage = (PBT + interest) ÷ interest: below 2 → elevated, below 4 → monitor.
  * Total debt: a rising trend → monitor.
  * **For lenders all of these are "insufficient",** with the explanation that NIM, GNPA and CAR are the right lenses but aren't in the data source.
* **Cash quality:**
  * 3-year cumulative CFO ÷ PAT: below 50% → elevated, below 80% → monitor (insufficient for lenders).
  * FCF = `fcf`, or CFO + CFI as a proxy: negative in 3 of the last 3 years → elevated, 2 → monitor.
* **Working capital** (non-financials): receivable days, inventory days and the cash conversion cycle versus the best prior year. An increase above the threshold (20/25/25 days) → monitor; above 1.5× the threshold → elevated.
* **Disclosed risks** are text-detected via annual-report retrieval, each returning its excerpt and page:
  * auditor qualification: elevated only if "basis for qualified opinion" or "adverse opinion" appears;
  * contingent liabilities and related-party transactions: monitor = "read this";
  * promoter pledging: stable if nil.
* **Overall:** elevated needs elevated signals in **≥ 2 different pillars**; otherwise monitor if any pillar is elevated or there are ≥ 3 monitor signals (text-detected disclosures don't count); otherwise stable. Never infer distress from one metric. Report data_completeness.

---

## 10. LLM gateway (`services/llm.py`)

* `available()` is true when a key is set.
* `resolve_models()` runs once per process:
  1. Env overrides win.
  2. Otherwise GET `{base}/models`, strip the `models/` prefix, and keep `gemini-*` IDs that don't match `image|tts|audio|live|embed|vision|thinking|exp|preview|learnlm`.
  3. **fast** = the highest-versioned `flash-lite`; **strong** = the highest-versioned ID ending in `-flash`. Sort versions by the digits before "flash".
  4. Fallbacks: `gemini-3.5-flash-lite` / `gemini-3.8-flash`. **Don't use Pro: it left the free tier in April 2026.**
* `complete(messages, tier, json_mode, max_tokens, temperature=0)`:
  * Cache lookup by sha256(model + messages + json_mode).
  * A throttle enforces `LLM_MIN_INTERVAL_S` between calls.
  * POST `/chat/completions` with a Bearer key; 4 attempts.
  * On **429**, wait for Retry-After or 8·(attempt + 1) seconds, at most 60.
  * On **400 with response_format**, drop JSON mode and retry.
  * On success, write the cache (errors swallowed) and return the text; after repeated failure, return None.
* `complete_json` parses the response and falls back to the first `{…}` or `[…]`.
* `stats()` reports calls, cache hits, tokens, errors, provider ("Google Gemini"), the resolved models and configured status.

**Routing policy:** rules first; Flash-Lite for classification fallback, summaries, bios, results-page fallback and guidance extraction; Flash only for narrative synthesis, guidance interpretation and bull/bear.

---

## 11. Live connectors and ingestion pipeline

* **`connectors/prices.py`:**
  * `yf.download([T.NS...], period="1y", interval="1d", group_by="ticker", auto_adjust=False)`.
  * Upsert with a dialect-aware `insert…on_conflict_do_update` (sqlite or postgresql).
  * `company_info()` via `yf.Ticker(...).info` for unknown tickers.
  * Import yfinance lazily.
* **`connectors/nse.py`:**
  * An httpx client with browser headers and a Referer.
  * Warm up by GETting `https://www.nseindia.com` and `/companies-listing/corporate-filings-announcements` (cookies).
  * Then GET `/api/corporate-announcements?index=equities&symbol=X&from_date=dd-mm-YYYY&to_date=dd-mm-YYYY`.
  * On 401/403, warm up again and retry (3 attempts); wait 0.7 s between symbols.
  * Normalise:
    * subject = `attchmntText` or `desc`;
    * time from `an_dt` / `sort_date` / `dt` (formats `%d-%b-%Y %H:%M:%S`, `%Y-%m-%d %H:%M:%S`);
    * attachment = `attchmntFile`;
    * exchange category = `desc`;
    * dedupe_key = sha256 of `nse|symbol|seq_id|subject|time`.
  * `pdf_text(url)` returns the first 12 pages joined by `\f`.
  * **Cost discipline:** download attachments only when the rules pre-classification isn't routine, investor_meetings, agm_egm, postal_ballot or earnings_call.
* **`connectors/screener.py`:**
  * Try `/company/T/consolidated/`, then `/company/T/` (standalone), with a 1.2 s delay; keep a page if `section#quarters` has more than 3 rows.
  * Parse the tables in `section#quarters`, `#profit-loss`, `#balance-sheet`, `#cash-flow` and `#ratios`. Match row names case-insensitively after stripping a trailing "+":
    * sales/revenue → revenue
    * expenses
    * operating profit / financing profit → ebitda
    * other income, interest, depreciation
    * profit before tax → pbt
    * tax %
    * net profit → pat
    * eps in rs
    * exceptional items
    * equity capital, reserves, borrowings, deposits, other liabilities
    * total liabilities → total_assets
    * fixed assets, cwip, investments, other assets
    * cash from operating/investing/financing activity → cfo/cfi/cff
    * net cash flow, free cash flow
    * debtor days, inventory days, days payable, cash conversion cycle, working capital days
    * roce %, roe %
  * Column headers like "Sep 2026" become month-end dates. Drop TTM columns. `net_worth = equity_capital + reserves`; `is_financial` if a "Financing Profit" row exists.
  * Documents: the first 3 annual-report links ("Financial Year YYYY" → FYyy); up to 6 concalls whose link text contains "Transcript", with the call month.
  * `download()` must check the `%PDF-` magic bytes.
* **`services/pipeline.py`:**
  * `ensure_company` takes a seed entry, else yfinance info.
  * `refresh_prices`, `refresh_announcements(days)`, `refresh_fundamentals(ticker, with_docs)`.
  * A transcript's quarter is the most recent quarter end strictly before the call month: `qm = ((month − 1)//3)·3`, with 0 meaning Dec of the previous year. Download and index the latest AR plus the last 4 transcripts, then `guidance.extract`.
  * `refresh_all` purges demo data if in demo mode, runs each source independently, and records `Meta.source_status[source] = {ok, detail, at}`.
  * Then: set data_mode live, seed alert defaults, `signals.process(force=True)`, `alerts.evaluate()`.
  * One blocked source never stops the others, and failures are reported, never papered over.
* **`refresh.py` CLI:** `python -m finn.refresh [--tickers …] [--research TRENT HAL PERSISTENT] [--days 7] [--no-docs]`.

---

## 12. The illustrative demo dataset (`demo.py`)

Freeze it with `DEMO_TODAY = 2026-11-03`. The last session is the previous weekday (2026-11-02, a Monday). The latest reported quarter is Sep 2026 (Q2 FY27). Build 10 quarters (Q1 FY25 Jun-2024 … Q2 FY27 Sep-2026) and 270 weekday sessions.

**Financials:**

* Each ticker gets a per-company cost structure: `oi = rev·U(0.002, 0.008)`, `dep = ebitda·U(0.12, 0.26)`, `interest = ebitda·U(0.02, 0.10)`, ±3% jitter per quarter, tax 25.2%, `pbt = ebitda + oi − dep − interest`, `pat = pbt·(1 − tax)`. Scaling dep and interest by EBITDA keeps low-margin businesses profitable.
* Banks: `pbt = rev·U(0.24, 0.30)`, EBITDA None.
* Generic tickers: revenue grows backwards from the profile at the profile growth rate, with a seasonality multiplier (Jun 0.96, Sep 1.00, Dec 1.06, Mar 0.98), ±2.5% noise and margin ±0.6 pp.
* **Annual rows:** an FY is the sum of its 4 quarters, using a window of `fe − 360 days < q ≤ fe` (**not 370**: that caught 5 quarters and silently dropped FY26). Earlier years are extrapolated backwards to 5 years total.
* Balance sheet: net worth ≈ PAT·U(5.5, 7.5) growing 8%/yr; borrowings = net worth · D/E; CFO = PAT · conversion ± 15%; CFI = −|CFO|·U(0.45, 0.85) (TITAN: ·1.6); debtor/inventory/payable days, CCC, ROCE, ROE.

**Latest-quarter revenue profile** as `(revenue ₹ cr, YoY growth, EBITDA margin %, D/E, CFO/PAT, debtor days, inventory days)`; banks have `None` for everything after growth:

| Ticker | Profile |
|---|---|
| RELIANCE | 258000, 0.07, 17.5, 0.42, 1.25, 12, 70 |
| HDFCBANK | 86000, 0.11 |
| ICICIBANK | 49000, 0.12 |
| SBIN | 121000, 0.09 |
| INFY | 44500, 0.06, 24.5, 0.05, 1.05, 68, 0 |
| TCS | 66500, 0.05, 27, 0.04, 1.02, 75, 0 |
| KPITTECH | 1620, 0.14, 21, 0.10, 0.95, 62, 0 |
| TMPV | 98000, −0.03, 11, 0.65, 1.40, 18, 55 |
| MARUTI | 40200, 0.09, 12, 0.01, 1.10, 9, 14 |
| M&M | 45800, 0.16, 14, 0.95, 0.85, 22, 45 |
| LT | 67500, 0.12, 10.5, 1.10, 0.90, 95, 12 |
| ITC | 21200, 0.07, 35, 0, 1.05, 14, 160 |
| HINDUNILVR | 16100, 0.03, 23, 0, 1.10, 12, 33 |
| SUNPHARMA | 14100, 0.09, 28, 0.02, 0.95, 95, 210 |
| BHARTIARTL | 52500, 0.18, 55, 1.25, 1.80, 25, 0 |
| NTPC | 45200, 0.04, 28, 1.45, 1.70, 55, 40 |
| ASIANPAINT | 8600, −0.01, 18.5, 0.08, 1.15, 34, 105 |
| POLYCAB | 6700, 0.22, 13.5, 0.02, 0.75, 42, 85 |
| PERSISTENT | 3750, 0.22, 17, 0.05, 1.0, 70, 0 |
| HAL | 7600, 0.11, 28, 0, 1.2, 80, 300 |
| BAJFINANCE | 19500, 0.24 |
| DMART | 16800, 0.15, 8, 0.05, 0.9, 1, 30 |

**Story companies** have explicit 10-quarter paths so promise vs delivered is meaningful. Columns run Jun-24 … Sep-26.

* **DIXON**
  * Revenue: 6580, 11534, 10454, 10293, 12836, 14855, 13200, 12739, 15900, 20500.
  * EBITDA margin: 3.9, 3.7, 3.9, 4.1, 4.0, 3.7, 4.1, 4.2, 3.7, 4.0.
  * D/E by year: 0.12, 0.10, 0.15, 0.14, 0.11. CFO/PAT 1.12. Debtor days: 48→36. Inventory days: 28→22.
* **TITAN**
  * Revenue: 13266, 14656, 17740, 14916, 15520, 16830, 20560, 17370, 17100, 18300.
  * Margin: 11.0, 10.9, 11.6, 11.1, 11.2, 10.6, 11.9, 11.0, 10.9, 10.2.
  * D/E: 0.55, 0.62, 0.78, 0.95, 1.18. CFO/PAT 0.42. Debtor days ~5–7. Inventory days: 205, 210, 222, 236, 262. Payable days 20.
  * This should come out **Elevated**: cash quality plus working capital.
* **TRENT**
  * Revenue: 4104, 4157, 4657, 4217, 4883, 5105, 5800, 5145, 5700, 6050.
  * Margin: 16.0, 16.4, 17.2, 16.9, 17.1, 17.4, 18.3, 17.6, 17.0, 17.8.
  * D/E: 0.35→0.18. CFO/PAT 0.98.
  * This should come out **Stable**.

**Prices:**

* Seeded random walk backwards from a base level: RELIANCE 1480, HDFCBANK 1010, ICICIBANK 1395, SBIN 905, INFY 1540, TCS 3120, KPITTECH 1290, TMPV 410, MARUTI 15800, M&M 3550, LT 3920, ITC 418, HINDUNILVR 2480, SUNPHARMA 1710, BHARTIARTL 2050, NTPC 342, TITAN 3660, ASIANPAINT 2390, DIXON 16800, POLYCAB 7450, TRENT 4720, PERSISTENT 6120, HAL 4810, BAJFINANCE 1035, DMART 4290.
* Daily vol U(1.0, 1.7)%, returns clipped to ±3.2%, volume noise clipped to ±0.45 in log space.
* **Planted moves** as (sessions ago: return %, volume ×):

| Ticker | Planted move |
|---|---|
| DIXON | 0: +6.8%, 3.4× |
| SUNPHARMA | 0: −4.6%, 2.3× |
| KPITTECH | 0: +3.1%, 2.6× |
| POLYCAB | 1: +5.1%, 2.1× |
| ASIANPAINT | 6: −4.3%, 1.9× |
| RELIANCE | 4: +1.2%, 2.2× |
| LT | 0: +2.4%, 1.6× |
| TITAN | 3: −1.8%, 1.4× |

**Announcements** (IST; d0 = last session, d1 = previous weekday, dN = N weekdays back):

| When | Ticker | Exchange label | Subject / content |
|---|---|---|---|
| d0 12:40 | DIXON | Outcome of Board Meeting | Unaudited results; attachment = page 1 "Outcome…" + `\f` + a SEBI-format consolidated table generated from the quarter data in "(Rs. in crore)", with rows 1 Revenue from operations, 2 Other income, 3 Total income, 4 a/b/c expenses (finance costs, depreciation), 5 Profit before exceptional items and tax, 6 Exceptional items 0.00, 7 Profit before tax, 8 Tax, 9 Net profit for the period |
| d0 16:20 | TITAN | Financial Result Updates | Same format. After hours, so there's no reaction yet |
| d0 08:15 | SUNPHARMA | Change in Directors/KMP… | Mr. Kunal Mehrotra resigns as CFO to pursue opportunities outside the Company, w.e.f. close of business hours on 30 November 2026. Ms. Ritika Sharan is appointed CFO and KMP w.e.f. 1 December 2026, with a "Brief profile of Ms. Ritika Sharan:" paragraph (CA, 22 years in finance, treasury and IR; ex-CFO of the India business of a multinational generics company; 11 years at a large Indian IT firm; B.Com from Delhi University) and "(Names are fictional - illustrative demo.)" |
| d0 09:05 | KPITTECH | Acquisition | 100% of a Munich automotive middleware firm for up to Rs. 950 crore in cash, two tranches; EUR 96 million CY2025 revenue; ~800 engineers |
| d0 10:15 | LT | Press Release | "significant" metro order (Rs. 2,500 crore to Rs. 5,000 crore per L&T's classification), 14 stations |
| d1 14:30 | POLYCAB | Updates | Board approves Rs. 1,200 crore capex over FY27–28, Halol brownfield, internal accruals |
| d0 11:00 | ICICIBANK | Credit Rating | CRISIL reaffirms AAA/Stable |
| d0 13:45 | ASIANPAINT | Updates | GST demand of Rs. 118.6 crore; will appeal |
| d0 15:05 and 15:09 | TCS | Analysts/… | "Schedule of analyst / institutional investor meetings", twice (duplicate test) |
| d0 17:30 | M&M | Board Meeting Intimation | Board meeting to approve results |
| d0 18:00 | BHARTIARTL | Updates | NCD allotment, Rs. 2,000 crore |
| d0 18:20 | ITC | Record Date | Interim dividend Rs. 7 |
| d0 18:40 | HDFCBANK | ESOP/ESOS | ESOS allotment (routine) |
| d0 18:45 | INFY | Certificate… | Reg 74(5) certificate (routine) |
| d0 19:00 | RELIANCE | Copy of Newspaper Publication | Newspaper publication (routine) |
| d0 19:10 | MARUTI | Trading Window | Trading window closure (routine) |
| d0 19:15 | NTPC | Updates | 660 MW Unit-2 commercial operation |
| d0 19:30 | TMPV | Analysts/… | Concall transcript |
| d-3 16:45 | ICICIBANK | Financial Result Updates | Standalone results, no attachment (bank card: EBITDA N/A) |
| d-3 14:00 | SBIN | Updates | Up to Rs. 20,000 crore of Basel III bonds |
| d-4 12:00 | HINDUNILVR | Press Release | Premium skincare launch |
| d-4 17:00 | TITAN | Board Meeting Intimation | Board notice |
| d-5 15:30 | RELIANCE | Analysts/… | Investor-conference intimation |
| d-5 12:10 | SUNPHARMA | Updates | USFDA Form 483 with 3 observations |
| d-6 18:00 | DIXON | Board Meeting Intimation | Board notice |
| d-6 10:00 | M&M | Press Release | Monthly sales +17% |
| d-7 11:30 | ASIANPAINT | Shareholders meeting | Postal ballot notice |
| d-7 16:00 | ITC | Insider Trading | Reg 7(2) sale by a designated person |

**Documents** are generated as PDFs with PyMuPDF and run through the **same** ingestion pipeline.

* **PDF writer:** A4, Helvetica (`helv`/`hebo`), the watermark plus the title in a small header on every page, each paragraph a separate textbox (so blocks preserve paragraphs). Write "Rs." rather than ₹, because the base font lacks the glyph.
* **FY26 annual report** for DIXON, TITAN and TRENT:
  * cover;
  * Business Overview (industry, segments, revenue mix);
  * page break; Management Discussion and Analysis (FY26 revenue vs FY25 with growth, EBITDA and margin, PAT, borrowings, net worth, CFO);
  * Outlook;
  * Risks and Concerns (customer concentration, input/commodity volatility, incentive-scheme changes, competition, FX, execution; TITAN adds gold-price volatility and gold metal loans);
  * page break; Key Financial Ratios (number-dense);
  * Notes to the Consolidated Financial Statements: contingent liabilities ≈ 1.1% of revenue; related-party transactions ≈ 0.4% of revenue, at arm's length;
  * page break; Independent Auditor's Report (unmodified opinion; TITAN adds an emphasis of matter on gold metal loans, opinion not modified);
  * Report on Corporate Governance (promoter shares pledged: Nil).
  * Segment mixes: DIXON "mobile and EMS 72%, consumer electronics 16%, home appliances 7%, lighting and others 5%"; TITAN "jewellery 88%, watches and wearables 7%, eyecare 2%, emerging businesses and others 3%"; TRENT "Zudio 58%, Westside 37%, others 5%".
* **Four transcripts each** (Q3 FY26, Q4 FY26, Q1 FY27, Q2 FY27). Speakers: Moderator, Managing Director, Chief Financial Officer, Analyst A, Analyst B. One statement per metric per sentence. Statements, verbatim intent:
  * **DIXON**
    * Q3 FY26: MD "For FY26 we expect revenue growth of 30% to 35%…". CFO "We expect EBITDA margin for FY26 in the range of 3.9% to 4.1%…". MD "Capex for FY26 will be about Rs. 1,000 crore…".
    * Q4 FY26: MD "FY26 was an exceptional year; revenue grew about 38%… for FY27 we are guiding revenue growth of 30% to 35%." CFO "For Q1 FY27 we expect EBITDA margin of 4.0% to 4.2%…". MD on customer-concentration risk.
    * Q1 FY27: MD "Q1 margins came in below our expectation… We are raising our FY27 guidance and now expect revenue growth of 35% to 40% for FY27." CFO "For the next quarter we expect revenue growth of at least 30% year-on-year…". CFO "We expect FY27 EBITDA margin of 3.8% to 4.0%…". CFO on working capital.
    * Q2 FY27: MD "Q2 revenue grew 38%… We maintain the FY27 guidance of revenue growth of 35% to 40%." CFO "Over the medium term we aspire to an EBITDA margin of 4.5%…".
  * **TITAN**
    * Q3 FY26: MD "We expect to close FY26 with revenue growth of around 20%…". CFO "We expect EBITDA margin for FY26 to be in the 11% to 11.5% band…". CFO on gold metal loans.
    * Q4 FY26: MD "FY26 revenue grew about 16%, below the 20% we had indicated… For FY27 we are guiding revenue growth of 18% to 20%." CFO "For Q1 FY27 we expect revenue growth of 14% to 16%…". CFO "We are targeting FY27 EBITDA margin of 11% to 11.5%." CFO on inventory.
    * Q1 FY27: MD "…we now expect FY27 revenue growth of 15% to 17%, lower than our earlier guidance." CFO "We maintain the FY27 EBITDA margin guidance of 11% to 11.5%…". MD on ~60 new stores.
    * Q2 FY27: MD "Q2 revenue grew about 9%…". CFO "…we expect the second half to show double-digit revenue growth with margins recovering."
  * **TRENT**
    * Q3 FY26: MD "We expect FY26 revenue growth of upwards of 25%…". CFO "We expect FY26 EBITDA margin of 16% to 17% on a pre-Ind AS 116 basis." MD "We plan to add about 200 Zudio stores in FY26…".
    * Q4 FY26: MD "FY26 revenue grew about 22%… For FY27 we expect revenue growth of around 20%." CFO "For Q1 FY27 we expect revenue growth of at least 15% year-on-year." CFO "Capex for FY27 will be about Rs. 1,500 crore…".
    * Q1 FY27: MD "Q1 revenue grew about 17%… We maintain our FY27 guidance of revenue growth of around 20%." CFO "We expect FY27 EBITDA margin of 17% to 18%." MD on quick-commerce fashion.
    * Q2 FY27: MD "Q2 revenue grew about 18.5%… Zudio crossing 900 stores." CFO "We expect the next quarter to deliver revenue growth of 18% to 20%…". CFO "…sustaining margins in the 17% to 18% range over the medium term."

**Expected grading with no LLM** (use this as an acceptance test):

* **TITAN:** missed 2 (FY26 growth 16.0% vs 19.5–20.5; Q1 FY27 growth 10.2% vs 14–16), achieved 1 (FY26 margin ≈ 11.2% vs 11–11.5), pending 4. FY27 growth revised **down** 18–20 → 15–17. Repeated misses on revenue growth. Hit rate 33%.
* **DIXON:** exceeded 1 (FY26 growth 38.0% vs 30–35), achieved 2 (FY26 margin; Q2 FY27 YoY 38.0% vs ≥ 30), missed 1 (Q1 FY27 margin 3.7 vs 4.0–4.2), pending 4, long-dated 1, not comparable 1 (capex). FY27 growth revised **up** 30–35 → 35–40.
* **TRENT:** missed 1 (FY26 growth 22.2% vs ≥ 25), exceeded 1 (FY26 margin 17.6 vs 16–17), achieved 1 (Q1 FY27 16.7% vs ≥ 15), pending 5, long-dated 1.

**Expected brief** (24-hour default window, demo anchor d0 19:31):

* Headline: "5 holdings need your attention".
* Lines: Results DIXON TITAN · M&A KPITTECH · Management change SUNPHARMA · Fund raise BHARTIARTL · Unusual volume DIXON KPITTECH SUNPHARMA.
* Counts: 18 filings, 3 critical, 2 high, 6 medium, 7 routine.
* DIXON results rank first (~93), with verification **verified** against the filing on page 2.

`reset()` wipes everything except the LLM cache, then rebuilds companies, financials, prices, holdings, announcements and documents (indexed). It sets Meta `data_mode = demo`, seeds alerts, processes signals, evaluates alerts and extracts guidance for the 3 story companies.

`seed.py` runs `init_db` + `demo.reset`.

**Prebuilt snapshot:**

1. Build with `FINN_DATA_DIR=/tmp/finn`.
2. Checkpoint the WAL and set journal_mode=DELETE.
3. Copy `finn.db` and `docs/` to `backend/seed/`.
4. On API startup, if the DB file doesn't exist and `FINN_SNAPSHOT_DIR` (default `backend/seed`) has `finn.db`, copy it in. Otherwise, if the DB is empty, run `demo.reset`.

`/api/documents/{id}/file` must resolve paths built on another machine: if the stored path is missing, re-root everything after its `docs/` component under this deployment's docs_dir.

---

## 13. API (`api/app.py`; thin handlers, logic in services)

* Startup: restore the snapshot, `init_db`, build the demo if empty.
* An `X-Response-Time-ms` middleware.
* A global exception handler returning `{"error": "internal_error", "detail": …}` with status 500.
* 404s return `{"error": "not_found", "detail": …}`.

| Route | Purpose |
|---|---|
| GET `/api/health` | Liveness |
| GET `/api/system/data-status` | mode, sources, counts, last EOD session, the monitoring note ("End-of-day… Not real-time."), LLM stats, retrieval mode |
| POST `/api/system/demo-reset` | Restores the snapshot if `FINN_SNAPSHOT_DIR` has one (dispose the engine, remove -wal/-shm, copy); else `demo.reset` |
| GET `/api/system/eval` | `backend/eval/results.json`, or `{available: false}` |
| GET `/api/meta/categories` | Category list |
| GET/POST/DELETE `/api/portfolio[/{ticker}]` | Items: ticker, name, sector, is_financial, in_portfolio, price snapshot, 60-day spark, signals_7d, top_score_7d, latest_quarter preview, has_documents. Sectors. POST validates via `ensure_company` (422 if unknown); DELETE gives 404 if not held |
| GET `/api/companies/search?q=` | Known companies + universe; if q looks like a ticker, append "{Q} (any NSE symbol)" |
| GET `/api/companies/{t}` · `/prices?days` · `/financials` · `/announcements` | Company data |
| GET `/api/digest` | Params: hours (1–2160, default 24), start, end, ticker[], sector, category[], min_priority. Adds `triage` per item and data_mode |
| GET `/api/signals` | Params: hours, priority[], category[], ticker, page, page_size. Paginated |
| GET `/api/signals/{id}` | Full detail + triage + 40-day price context + 5 related filings |
| POST `/api/signals/{id}/triage` | `{action: pin \| dismiss \| clear}`, stored in Meta |
| POST `/api/research/query` | `{ticker, question (3–500 characters)}` |
| GET `/api/research/{t}` | Overview + documents + ingestion status + data_mode |
| GET `/api/research/{t}/documents` · `/management-guidance` · `/financial-health` · `/bull-bear` | Research views |
| POST `/api/research/{t}/ingest` | 202; background task: refresh prices + fundamentals + docs, recording `Meta["ingest:T"]` status |
| GET `/api/documents/{id}/file` | Inline PDF |
| GET/POST/PATCH/DELETE `/api/alerts[/{id}]` | Rules + events + unseen + monitoring note. POST validates category, and requires a threshold for price/volume rules. PATCH re-derives history when the threshold changes |
| POST `/api/alerts/seen` | Mark all seen |
| GET/PUT `/api/settings/materiality` | Weights, normalised; PUT re-scores everything |
| `/{path}` | SPA fallback: serve `frontend/dist` (mount `/assets`); `api/*` paths that don't exist give 404 |

---

## 14. Frontend: mobile-first, with a point of view

**Design system.** It has to look like an institutional research terminal, not a template.

* **Colours:** ink `#0E1726` (background), surface `#152033`, raised `#1B2940`, line `#26354F`, fg `#E6ECF5`, dim `#8A9BB5`, faint `#5C6C86`, up `#3FB98A`, info `#5B9BF0`, warn `#E0A84B`, down `#E5675F`.
* **Materiality component colours:** category `#5B9BF0`, financial `#3FB98A`, unusualness `#E0A84B`, relevance `#A48BE8`, novelty `#4FC3C9`.
* **Type:** Archivo variable font with tabular, lining numerals. Its **width axis carries hierarchy**: `.w-cond` (font-stretch 78%) for dense numbers, `.w-semi` (90%) for page titles, `.w-wide` (118%) for the brief headline and wordmark.
* **Radius:** 6 px everywhere; 14 px only for the triage deck cards and sheets.
* **Avoid:** all-caps eyebrow labels, monospace data labels, gradient washes, identical rounded cards everywhere (use hairline-divided rows), "·"-joined meta strings, arrows appended to button text.
* **Quality floor:** keyboard focus rings, `prefers-reduced-motion`, skeleton loaders, empty states that say what to do next, and errors that say what failed plus offer a "Try again" button.

**The signature element:** a **materiality strip**, a 5-segment bar whose segment widths are the components' contributions to the score, shown on every signal.

**Shell:**

* Mobile: sticky top bar with the "FINN" wordmark (`w-wide`, extra-bold), a "Demo data" chip and a settings gear. A bottom tab bar with 4 tabs: Brief, Portfolio, Research, Alerts (unseen-count badge).
* Desktop ≥ md: a 224 px sidebar with the same nav, Settings, and a data-mode note.
* **The Ask FINN bar is docked** above the tab bar on every screen: a pill input showing the current company's ticker chip and "Ask about DIXON…".
* Routing is hash-based (`#/brief`, `#/signal/12`, `#/research/TITAN/guidance`).

**Pages:**

1. **Brief** (home):
   * Date line ("Monday, 2 November, dataset close").
   * The headline in `w-wide` at 25–32 px, bold, then a two-column definition list (label → tappable tickers).
   * A segmented window control (24h / 3d / 7d / Custom with date inputs); a filter button revealing Sector, Category and "Priority at least" selects; an icon toggle between the triage deck and list.
   * Count line: "18 filings from 17 companies: 3 critical, 2 high, 6 medium, 7 routine collapsed".
   * **Triage deck** (default on mobile):
     * A stack of the top card plus 2 peeking cards behind it.
     * Pointer-drag: past ±90 px pins (right) or marks seen (left), with a rotation of dx/28 degrees and "Pin"/"Seen" stamps. A tap opens the detail; the arrow keys and Enter work too.
     * Buttons: Seen · **Why it matters** (primary) · Pin. Progress "3 of 11 reviewed". When the deck is cleared: "Brief cleared", the pinned list, and "Review again".
     * **Card:** ticker + company, priority dot + label + score, category, relative time, Demo badge, the summary in 17 px semibold. Then a 4-column results preview (Revenue/EBITDA/PBT/PAT YoY in `w-cond`, coloured) or the bio preview (name, "joins as"/"leaves as" role, 3-line profile). Then the materiality strip and the `why_rank` line.
   * The deck sets the Ask FINN ticker to the top card's ticker.
   * **List** (default on desktop): hairline rows with ticker, priority, category, time, summary, a results-preview line, a thin strip and a pin toggle.
   * "Unusual end-of-day moves": rows with ticker, a short message, and the value in `w-cond` (e.g. 3.5× or +5.1%).
   * "N routine filings": collapsed, with a per-category count summary; expanding shows the list, with duplicates marked.
2. **Signal detail:**
   * Back link; ticker (links to research), company, sector, "Not in portfolio" if applicable; the summary as h1; priority/score, category ("LLM-classified" if so), time, Demo badge, pin; "Filed as: <subject>".
   * **"Why should I care?"** panel (`w-wide` title): What happened (*Confirmed from the filing*), What it could mean (*Inference, not a fact*), Is this unusual?, What history supports this, What remains uncertain (the demo line in warn colour).
   * **Results card:** fiscal period title, verification pill, basis/unit/comparison periods. A table with columns metric, current, QoQ, YoY (bold `w-cond`), and the year-ago value (from sm up). The EBITDA margin line with bps, the lender note, flags, and a Recharts composed chart: revenue and PAT bars plus an EBITDA-margin line on a hidden right axis, with a legend.
   * **Who is involved:** a card per person with name, change (green or amber), role, effective date/reason, profile, and a "Search LinkedIn" link. Footnote: "read from the profile the company must include in the filing (SEBI LODR)".
   * **Questions worth asking:** each opens Ask FINN for that ticker (strip any trailing parenthetical); plus "Open <T> research".
   * **How FINN ranked this:** the big score, the strip with legend, and a table of component, reason, score, weight and contribution.
   * Price around the filing: a close line plus volume bars, with a dashed amber reference line labelled "filing".
   * Original filing: the exchange link, or the demo filing text in a scroll box. Earlier filings from the same company.
3. **Portfolio:**
   * Title + "20 holdings, equal-weight day move +0.37%, 12 up and 8 down on 2 Nov (EOD)".
   * Ticker search with autocomplete to add.
   * Sector chips; sort control (Signals / Move / Volume / A–Z); an Edit mode with remove buttons (confirm first).
   * Rows: ticker + priority tag if there are 7-day signals, name, a sparkline (green/red), close and % change, volume ratio (warn if ≥ 2). Footnote about EOD.
4. **Research:**
   * Home: the search box, document-indexed chips ("Promise vs delivered"), holdings chips.
   * Company page: header (ticker in `w-wide`, source badge, name and sector, close, day % and 1-year %), a sparkline, an add/remove toggle, and tabs: **Overview, Promise vs delivered, Health, Bull vs bear, Documents**.
   * **Overview:** business text with citations (expandable excerpts), an ingest prompt if there are no docs ("Fetch and index <T>"), a 6-stat financial snapshot (N/A for lenders where it applies), the TTM line, the trajectory takeaway plus chart (FYxx axis), and the latest results card.
   * **Promise vs delivered:**
     * Hit rate as a giant `w-wide` number ("33%"), "of N gradeable promises met or beaten, across K calls", then Beaten/Met/Missed/Pending counts.
     * The interpretation paragraph, then revisions (up/down arrow icons, "18–20% → 15–17% (Q4 FY26 to Q1 FY27 call)").
     * **Dumbbell chart** (custom SVG/CSS): per graded item, the guided band as a translucent blue bar and the reported value as a green (met) or red (missed) dot with its value, on a shared % axis per metric family, with a legend.
     * "Every statement, by call", newest call first: metric, horizon, target, reported value, status pill, "revised down", the **verbatim quote** as a blockquote, then speaker, page, commitment type, method, transcript link and Demo badge.
     * Caveats.
   * **Health:** the overall label in `w-wide` and colour, completeness, reason, the lender note, the disclaimer. Pillars, each a list of rows: metric + sparkline + value + status pill on one line, interpretation + trend underneath, and an evidence excerpt with page for text-detected items.
   * **Bull vs bear:** two columns with green and red left borders, citations, method note.
   * **Documents:** title, type, period, pages, passages indexed, status pill, PDF link, "Re-fetch from screener.in".
5. **Alerts:**
   * "You decide what counts as unusual." plus the monitoring note.
   * Rules list: toggle switch, description, priority, inline threshold input (saves on blur), delete.
   * A new-rule form (When / Threshold or Type / Company / Priority / Add alert).
   * History rows that link to the signal or company. Opening the page marks events seen.
6. **Settings:**
   * The data-mode box (warn styling in demo) with counts and the refresh command; per-source status rows.
   * "Reset demo dataset".
   * Language model: provider and the resolved models with their tier roles, or the no-key explanation (set `GEMINI_API_KEY`); calls, cache hits, tokens; retrieval mode.
   * **Materiality weight sliders** (normalised % display, "Save and re-score", "Restore defaults").
   * The evaluation panel (metrics grid + caveat). About.

**Ask FINN sheet:**

* A bottom sheet on mobile, a centred modal on desktop.
* A conversation of turns. Each shows the ticker and question, then the route-label chip, engine, latency, and the answer rendered by a tiny renderer: paragraphs, "- " bullets, `**bold**`, `[n]` as clickable chips that expand that citation, and `⚠︎ *unverified*` as an amber "unverified" tag.
* An evidence-strength disclosure (label + factors + "not a calibrated probability").
* Sources list: number, document, period, page, speaker, source badge; expanding shows the excerpt and an "Open original" link (not for `demo://` URLs).
* A sticky footer with suggested-question chips and a follow-up input.
* Asking with no company in context returns "Pick a company first…".

---

## 15. Tests (`backend/tests/test_core.py`, pytest; unset all LLM keys)

* growth (including zero base → None, and loss narrowing → +50), margin/return/volume ratio, Indian number format.
* A parametrised classifier test covering 11 cases: results outcome, CFO resignation, acquisition, trading window, Reg 74(5), investor conference → investor_meetings, transcript → earnings_call, CRISIL reaffirm, USFDA 483 → litigation, pledge, dividend record date.
* Score = weighted sum, plus the band edges (80, 79.9, 35, 34.9).
* Amount extraction: 950; "2,500 to 5,000" → 5000; EUR million → None; ₹120 lakh → 1.2.
* Results parser on a lakh-unit consolidated sample: page, basis, unit conversion, year-ago PAT, and EBITDA = PBT + fin + dep − OI.
* Fiscal periods: Q2 FY27, the Q4 FY26 end, next quarter, FY end.
* Guidance target parsing (range, at least, around, capex crore) and horizons (Q1 FY27; next quarter → Q2 FY27; medium term).
* Grading (missed/achieved/exceeded with variance; at-least missed; not comparable).
* A backward-looking sentence is excluded; the verbatim check rejects an invented quote; the sentence splitter handles "Rs.".
* The management-change rules fallback finds two people and attributes the profile correctly.
* API on the demo dataset:
  * digest sorted desc, routine all low, totals add up, DIXON first;
  * DIXON results verified and YoY equal to `growth_pct`;
  * HDFCBANK EBITDA None with a note;
  * TITAN guidance has a miss, a downward revision, and pages on every row;
  * HAL narrative question → "could not verify" with no citations;
  * the metric route is deterministic;
  * alert CRUD, plus 422 on a price rule without a threshold;
  * portfolio add, remove, and 404 on a second remove;
  * the stemmer.

---

## 16. Evaluation harness (`backend/eval/`)

`questions.json` holds 27 items across these types: fact (7), guidance_text (4), numeric (4: TITAN PAT YoY, DIXON revenue YoY, TRENT EBITDA YoY, KPITTECH PBT QoQ), qoq (2), guidance (3, with expected status counts), trend/cross_doc (3, health route), insufficient (3: HAL risks, a TITAN irrelevant question, BAJFINANCE competition), contradiction (1: "Did FY26 revenue growth meet the 20% indicated earlier?" → guidance route, missed = 2).

`run_eval.py` runs each question through `answer.answer()` and scores:

* route accuracy;
* Recall@5 (the gold substring appears in the top-5 chunks);
* citation validity (each excerpt exists in a stored chunk);
* numeric accuracy (a regex on the answer vs an independent recomputation);
* guidance-grading counts;
* insufficient-evidence handling;
* unverified-sentence rate;
* latency p50/p95.

It writes `results.json` with corpus mode, LLM on/off and an honest caveat (a demo corpus validates the pipeline, not real-world accuracy). Target: 100% on every metric with the demo corpus.

---

## 17. Deployment

* **Dockerfile:**
  * Stage 1: `node:20-alpine`, `npm ci && npm run build`.
  * Stage 2: `python:3.12-slim`, `pip install -r backend/requirements.txt`, copy backend and dist.
  * `ENV FRONTEND_DIST=/app/frontend/dist PORT=8000 FINN_DATA_DIR=/tmp/finn FINN_SNAPSHOT_DIR=/app/backend/seed`.
  * `CMD uvicorn finn.api.app:app --host 0.0.0.0 --port ${PORT}`.
* **render.yaml:** a web service `finn`, runtime docker, plan free, healthCheckPath `/api/health`, env `GEMINI_API_KEY` with `sync: false`.
* **.env.example** documents every variable. **.gitignore:** node_modules, dist, `__pycache__`, `.pytest_cache`, `backend/data/*.db*`, `backend/data/docs/`, `.env`, `backend/.venv/`. `backend/seed/` **is committed**.
* **run.sh** (bash 3.2-compatible for macOS; uses python3 for JSON, no jq):
  * `local`: create `backend/.venv`, pip install, `npm ci` + build, start uvicorn with FRONTEND_DIST (PORT overridable).
  * `refresh [TICKERS]`: `python -m finn.refresh --research …`, checkpoint, then copy `data/finn.db` and `docs` into `backend/seed`.
  * `test`: pytest + eval.
  * `deploy`:
    1. Prompt for `RENDER_API_KEY` (silent read from /dev/tty) and an optional `GEMINI_API_KEY`; never write them to disk.
    2. `git init -b main`, add, commit.
    3. If there's no origin, `gh repo create <REPO_NAME> --public|--private` (prompt; default public) with `--source . --remote origin --push`; otherwise push.
    4. GET `{RENDER_API}/owners` for the workspace id.
    5. GET `/services?name=finn&ownerId=…`.
    6. If the service exists: PUT `/services/{id}/env-vars/FINN_DATA_DIR` and, only if a key was given, `/env-vars/GEMINI_API_KEY` (**per-key updates, so a keyless redeploy never wipes the stored key**), then POST `/services/{id}/deploys`.
    7. Otherwise POST `/services` with `{type: web_service, name, ownerId, repo, branch: main, autoDeploy: yes, envVars, serviceDetails: {runtime: docker, plan: free, region: singapore, healthCheckPath: /api/health, envSpecificDetails: {dockerfilePath: ./Dockerfile, dockerContext: .}}}`. If repo access fails, tell the user to connect GitHub in Render (needed for private repos).
    8. Poll `/services/{id}/deploys?limit=1` every 10 s until live (fail on build_failed/update_failed/canceled/deactivated).
    9. Curl `<url>/api/health`, then print the live URL, repo and dashboard link.
  * `RENDER_API` is overridable, so the script can be tested against a mock.

---

## 18. Execution order and verification (do all of it)

1. Scaffold. Write config/db/models/llm, then numbers/taxonomy/materiality/results/enrich/market/signals/alerts/digest, then ingest/retrieval/periods/guidance/health/answer, then connectors/pipeline/refresh, then demo/seed, then the API.
2. `python -m finn.seed`, then print the ranked signals, digest, guidance scorecards and health for DIXON, TITAN and TRENT. **Compare against the expected outputs in §12 and fix until they match.**
3. Smoke-test every endpoint with FastAPI's TestClient (including the error paths). Write the tests; all must pass.
4. Run the evaluation and fix the root causes of any failure (router gaps are real bugs, not test noise).
5. **Test the LLM paths against a mock OpenAI-compatible server** that (a) lists Gemini-like models including image/tts/preview/pro variants, (b) returns 429 with Retry-After once, (c) rejects `response_format` with 400, (d) returns an invented number "Rs. 99,999 crore" in a narrative answer (which must be flagged unverified), and (e) returns an invented guidance quote (which must be dropped, with the rules fallback taking over).
6. Build the frontend (`tsc -b && vite build`), serve it from FastAPI, and take **Playwright screenshots at iPhone 13 size** of Brief, the deck after a swipe, signal detail, Portfolio, Research overview, Promise vs delivered, Health, Alerts, Settings and the Ask FINN sheet, plus desktop at 1360 px. Fix layout problems: a headline too long for the fold, tables overflowing (no min-width), columns squeezed on mobile, wrapping titles. Confirm there are no console errors.
7. Do a clean-copy test: `npm ci` + build, start on an empty data dir, and confirm the snapshot restore, the SPA routes, an unknown `/api/*` returning 404, and PDFs being served.
8. Test `run.sh local` from a fresh copy, and `run.sh deploy` against a mock Render API plus a fake `gh` that pushes to a local bare repo: first deploy, redeploy (the stored key is kept), bad key → clean failure. Confirm the pushed tree has no node_modules, venv or local DB.
9. Write the README:
   * a one-command quick start;
   * a point-of-view table on how an investor uses it;
   * a mermaid architecture diagram;
   * an API table;
   * how materiality, accuracy, hallucination controls, RAG, promise vs delivered, generalisation and cost discipline work;
   * an eval table with its honest caveat;
   * a 5-minute demo script;
   * what's built, the deviations and why (SQLite instead of Postgres/pgvector, fastembed optional, no shadcn, 4 tabs, no LinkedIn scraping), known limitations (live connectors not exercised if the network is blocked; LLM tested on a mock only; lender metrics; segment guidance), and what's next.

   Then write `docs/COVERING_NOTE.md`, the submission email to assessment@enam.com with subject "ENAM - IIT screening - 2027", with placeholders for name and links.

**Environment caveat:** NSE, BSE, screener.in and Yahoo often block cloud IPs. Spend at most one quick reachability check per source. If blocked, don't fight it: build the connectors to their documented endpoints, rely on the labelled demo dataset, and say clearly in the README and final report which parts couldn't be exercised live.

## 19. Final report (end of session)

Briefly cover:

* what was built;
* what makes it different from a dashboard;
* how the materiality engine works;
* how financial accuracy is maintained;
* how hallucinations are prevented;
* how RAG retrieves and cites;
* how guidance comparison works;
* how it generalises to unseen tickers;
* the trade-offs;
* what you'd build next.

List honestly what was verified and what wasn't, and give the exact commands to run, refresh live data and deploy.
