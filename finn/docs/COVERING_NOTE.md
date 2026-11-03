**To:** assessment@enam.com
**Subject:** ENAM - IIT screening - 2027

Dear ENAM team,

Please find my submission for the FINN build challenge below. I am submitting after the 1 November deadline. [One line on why, or remove.]

- **Prototype (open on a phone):** [Render URL]
- **Repository:** [GitHub URL]
- **AI build history:** [Claude share link / export], plus the commit history

**What I built.** FINN is a mobile-first triage tool for a 20-stock NSE portfolio. The morning *Brief* turns every filing into a ranked card deck: swipe right to pin, left once seen, tap for "Why should I care?". Each card shows its materiality score as a five-part strip (category, financial size, unusualness, relevance, novelty), so the ranking is never a black box. Results filings are parsed straight from the PDF and reconciled against the structured quarterly table, giving Revenue, EBITDA, PBT and PAT, QoQ and YoY. A management-change filing shows the incoming person's profile, read from the disclosure SEBI already requires. On the pull side, *Ask FINN* is docked on every screen and follows the company in view. Each question is routed to the right engine: structured maths, guidance grading, health rules, or retrieval over the annual report and concall transcripts. Every claim cites a document, page and speaker. The flagship view is **Promise vs delivered**: four calls of management guidance, quoted verbatim, graded against reported numbers, with revisions and repeated misses called out.

**Key decisions.**
1. Numbers never come from an LLM. Growth, margins, ratios and the score itself are computed in Python, and the results numbers come from two reconciled sources.
2. Anti-hallucination by construction, not by prompt. Every number in an answer must appear in its cited excerpt, and every guidance quote must be found verbatim in the transcript. I tested this against a deliberately dishonest mock LLM, and both checks caught it.
3. Cheap by default. Filings are classified by rules, Gemini Flash-Lite handles extraction, Gemini Flash is used only for synthesis, and every call goes through a content-addressed cache. The whole demo runs with zero API calls and the app works without any key.
4. An explicit "I could not verify this" rather than a fluent guess.

**Trade-offs and what I left out.**
- The deployed app runs on a clearly labelled *illustrative* dataset, because the exchanges and screener.in block cloud IPs. Real data loads with one command (`python -m finn.refresh`) from a normal connection, and it replaces the demo rows completely.
- I chose SQLite + BM25 over Postgres + pgvector. Dense retrieval is optional.
- There is no LinkedIn scraping, because of LinkedIn's terms.
- Monitoring is end-of-day, with no real-time feed.

**Next.** Scheduled refresh with push notifications; segment-level guidance from investor presentations; and a relevance weight that learns from each investor's triage swipes.

The README covers the architecture, the scoring rules, the evaluation harness (27 curated questions) and a five-minute demo script.

Best regards,
[Name]
[Roll number / programme, IIT Kanpur]
