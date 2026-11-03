**To:** assessment@enam.com
**Subject:** ENAM - IIT screening - 2027

Dear ENAM team,

Please find my submission for the AI Engineer Build Challenge below.

- **Prototype (open on a phone):** [LIVE_URL]
- **Repository:** [GITHUB_URL]
- **AI build history:** [BUILD_HISTORY_LINKS]

**What I built.** FINN is a mobile-first agent with two modes.

*Push* is a windowed brief of exchange filings across a 20-stock NSE portfolio.
- Every filing gets an explainable materiality score: five rule-based components, each with a reason, shown as a strip on every card.
- You triage the brief as a swipeable deck, and routine paperwork stays collapsed.
- Results cards give Revenue, EBITDA, PBT and PAT, QoQ and YoY, verified against the filing PDF.
- Management changes show the incoming person's background, read from the profile SEBI requires in the filing.
- Threshold alerts are configurable.

*Pull* is research on any NSE ticker, grounded only in annual reports, transcripts and reported financials. The headline workflow is **Promise vs delivered**: management's guidance from the last four calls, quoted verbatim and graded in code against what was reported, with revisions and repeated misses called out.

**Key decisions.**
- The LLM never does arithmetic, and every number is computed in Python.
- A deterministic router keeps numeric and guidance questions away from the model entirely.
- Narrative answers must cite excerpts, and a verifier tags any sentence whose numbers are not in its sources.
- The app runs with zero API keys, because every LLM step has a rules or extractive fallback.
- With a Gemini free-tier key, Flash-Lite does bulk extraction and Flash does synthesis only. Responses are cached and throttled.

**Trade-offs.**
- SQLite instead of Postgres/pgvector, and BM25 with optional dense retrieval, to keep it one-command and free to host.
- Exchange and screener sites often block cloud IPs, so the deployed demo runs on a clearly watermarked illustrative dataset with fictional people. A live refresh replaces it and never mixes the two.

**What I left out.** BSE de-duplication, real-time intraday alerts, LinkedIn scraping (its terms forbid it), and lender-specific health metrics. Bank health is marked insufficient rather than guessed.

**Where I'd take it next.**
- Scheduled ingestion with push notifications.
- Segment-level guidance and KPI tracking.
- Cross-call narrative-vs-numbers contradiction detection.

Thank you for your time.

[NAME]
[PHONE] · [EMAIL]
