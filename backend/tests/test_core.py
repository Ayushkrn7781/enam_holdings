"""Core tests. All LLM keys are unset, so every path exercised here is the deterministic one."""
from __future__ import annotations

import os
import tempfile

for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY"):
    os.environ.pop(k, None)
os.environ["FINN_NO_DOTENV"] = "1"  # never pick up a developer's .env key during tests
os.environ["FINN_DATA_DIR"] = tempfile.mkdtemp(prefix="finn_test_")
os.environ["FINN_SNAPSHOT_DIR"] = os.path.join(os.environ["FINN_DATA_DIR"], "no_snapshot")

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from finn.research import guidance as G  # noqa: E402
from finn.research import periods as P  # noqa: E402
from finn.research.retrieval import split_sentences, stem  # noqa: E402
from finn.services import enrich, materiality as M, results  # noqa: E402
from finn.services import numbers as N  # noqa: E402
from finn.services.taxonomy import classify  # noqa: E402


# ---------------------------------------------------------------- maths
def test_growth_and_edge_cases():
    assert N.growth_pct(120, 100) == 20.0
    assert N.growth_pct(100, 0) is None
    assert N.growth_pct(None, 100) is None
    assert N.growth_pct(-50, -100) == 50.0  # a narrowed loss reads as +50%
    assert N.growth_pct(20500, 14855) == 38.0


def test_margin_return_volume_and_format():
    assert N.margin_pct(25, 200) == 12.5
    assert N.margin_pct(1, 0) is None
    assert N.daily_return_pct(105, 100) == 5.0
    assert N.volume_ratio(300, [100] * 20) == 3.0
    assert N.fmt_cr(1234567) == "₹12,34,567 Cr"
    assert N.fmt_cr(950) == "₹950 Cr"


# ---------------------------------------------------------------- classifier
@pytest.mark.parametrize("subject,label,expected", [
    ("Outcome of Board Meeting - Unaudited financial results for the quarter ended 30 September 2026",
     "Outcome of Board Meeting", "results"),
    ("Resignation of Chief Financial Officer (CFO)", "Change in Directors/KMP", "management_change"),
    ("Acquisition of 100% stake in XYZ GmbH", "Acquisition", "M&A"),
    ("Closure of trading window", "Trading Window", "unclassified"),
    ("Certificate under Regulation 74(5) of SEBI (DP) Regulations, 2018", "Certificate", "unclassified"),
    ("Intimation of participation in an investor conference",
     "Analysts/Institutional Investor Meet/Con. Call Updates", "investor_meetings"),
    ("Transcript of the earnings conference call for Q2 FY27", "Analysts/Institutional Investor Meet/Con. Call Updates",
     "earnings_call"),
    ("CRISIL reaffirms AAA/Stable rating", "Credit Rating", "credit_rating"),
    ("USFDA inspection concludes with Form 483 with 3 observations", "Updates", "litigation"),
    ("Disclosure of encumbrance / pledge of promoter shares", "Updates", "pledging"),
    ("Record date for interim dividend of Rs. 7 per share", "Record Date", "dividend"),
])
def test_classifier(subject, label, expected):
    assert classify(subject, label)[0] == expected


# ---------------------------------------------------------------- materiality
def test_score_is_weighted_sum_and_bands():
    comps = {k: {"value": v, "reason": ""} for k, v in
             {"category": 80, "financial": 60, "deviation": 40, "relevance": 100, "novelty": 50}.items()}
    sc, bd = M.score(comps)
    assert sc == round(0.25 * 80 + 0.25 * 60 + 0.2 * 40 + 0.15 * 100 + 0.15 * 50, 1)
    assert abs(sum(c["contribution"] for c in bd.values()) - sc) < 0.05
    assert M.priority(80) == "critical" and M.priority(79.9) == "high"
    assert M.priority(35) == "medium" and M.priority(34.9) == "low"


def test_amount_extraction():
    assert enrich.amount_cr("consideration of up to Rs. 950 crore in cash") == 950
    assert enrich.amount_cr("Rs. 2,500 to 5,000 crore") == 5000
    assert enrich.amount_cr("revenue of EUR 96 million") is None
    assert enrich.amount_cr("an amount of ₹120 lakh") == 1.2


# ---------------------------------------------------------------- results parser
SAMPLE = """XYZ Industries Ltd
Statement of Unaudited Consolidated Financial Results for the quarter ended 30 September 2026
(Rs. in lakh)
1 Revenue from operations 1,20,000.00 1,00,000.00 90,000.00
2 Other income 2,000.00 1,500.00 1,000.00
4 Expenses
b) Finance costs 3,000.00 2,800.00 2,500.00
c) Depreciation and amortisation expense 5,000.00 4,800.00 4,500.00
5 Profit before exceptional items and tax 18,000.00 15,000.00 12,000.00
6 Exceptional items 0.00 0.00 0.00
7 Profit before tax 18,000.00 15,000.00 12,000.00
9 Net profit for the period 13,500.00 11,250.00 9,000.00"""


def test_results_parser_lakh_consolidated():
    out = results.parse_results_pages(["Outcome of board meeting", SAMPLE])
    assert out["page"] == 2 and out["basis"] == "consolidated"
    assert out["revenue"] == 1200.0  # lakh -> crore
    assert out["pat_ya"] == 90.0
    assert out["pbt"] == 180.0  # not the 'before exceptional items' row
    assert out["ebitda"] == round(180 + 30 + 50 - 20, 2)


# ---------------------------------------------------------------- fiscal periods
def test_fiscal_periods():
    assert P.quarter_label(date(2026, 9, 30)) == "Q2 FY27"
    assert P.quarter_end(4, 26) == date(2026, 3, 31)
    assert P.next_quarter("Q1 FY27") == "Q2 FY27" and P.next_quarter("Q4 FY26") == "Q1 FY27"
    assert P.fy_end(27) == date(2027, 3, 31)


# ---------------------------------------------------------------- guidance
def test_guidance_targets_and_horizons():
    assert G.parse_target("we expect revenue growth of 30% to 35%", "revenue_growth") == (30, 35, "%")
    assert G.parse_target("revenue growth of at least 30% year-on-year", "revenue_growth") == (30, None, "%")
    assert G.parse_target("revenue growth of around 20%", "revenue_growth") == (19.5, 20.5, "%")
    assert G.parse_target("Capex for FY26 will be about Rs. 1,000 crore", "capex") == (1000, 1000, "INR cr")
    assert G.parse_horizon("For Q1 FY27 we expect margin of 4%", "Q4 FY26") == "Q1 FY27"
    assert G.parse_horizon("For the next quarter we expect growth of 30%", "Q1 FY27") == "Q2 FY27"
    assert G.parse_horizon("Over the medium term we aspire to 4.5%", "Q2 FY27") == "medium term"


def test_grading():
    assert G._grade(19.5, 20.5, 16.0) == "missed"
    assert G._grade(11, 11.5, 11.2) == "achieved"
    assert G._grade(30, 35, 38.0) == "exceeded"
    assert G._grade(4.0, 4.2, 3.7) == "missed"  # 0.05 pp tolerance only
    assert G._grade(25, None, 22.2) == "missed"
    assert G._grade(15, None, 16.7) == "achieved"


def test_backward_looking_excluded_and_verbatim_check():
    items = G.rules_extract("FY26 revenue grew about 16%, below the 20% we had indicated. For FY27 we are guiding "
                            "revenue growth of 18% to 20%.", "Q4 FY26")
    assert len(items) == 1 and items[0]["horizon"] == "FY27"
    chunk = "For FY27 we are guiding revenue growth of 18% to 20%."
    assert G.is_verbatim("we are guiding revenue growth of 18% to 20%", chunk)
    assert not G.is_verbatim("we promise revenue growth of 25% next year", chunk)
    assert split_sentences("Capex will be about Rs. 1,000 crore. Next.") == ["Capex will be about Rs. 1,000 crore.",
                                                                             "Next."]


def test_management_change_rules_fallback():
    text = ("Mr. Kunal Mehrotra has tendered his resignation as Chief Financial Officer to pursue opportunities outside "
            "the Company, w.e.f. close of business hours on 30 November 2026. The Board approved the appointment of "
            "Ms. Ritika Sharan as Chief Financial Officer w.e.f. 1 December 2026.\n\nBrief profile of Ms. Ritika Sharan: "
            "Ms. Sharan is a Chartered Accountant with 22 years of experience.\n\n")
    people = enrich.management_change_rules(text)
    assert [p["name"] for p in people] == ["Ritika Sharan", "Kunal Mehrotra"]
    assert people[0]["change"] == "joins" and "Chartered Accountant" in people[0]["profile"]
    assert people[1]["change"] == "leaves" and people[1]["profile"] is None
    assert people[1]["effective"] == "30 November 2026"


def test_stemmer():
    assert stem("investments") == "invest" and stem("companies") == "company" and stem("margins") == "margin"


# ---------------------------------------------------------------- API on the demo dataset
@pytest.fixture(scope="module")
def client():
    from finn.api.app import app
    with TestClient(app) as c:
        yield c


def test_digest(client):
    d = client.get("/api/digest").json()
    items = d["items"]
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    assert items[0]["ticker"] == "DIXON"
    assert all(r["priority"] == "low" or r["is_duplicate"] for r in d["routine"])
    c = d["counts"]
    assert c["critical"] + c["high"] + c["medium"] + c["routine"] == c["filings"] == 18
    assert d["headline"] == "5 holdings need your attention"


def test_dixon_results_verified(client):
    d = client.get("/api/digest").json()
    dixon = next(i for i in d["items"] if i["ticker"] == "DIXON")
    det = client.get(f"/api/signals/{dixon['id']}").json()
    card = det["enrichment"]["results"]
    assert card["verification"]["status"] == "verified"
    rev = next(r for r in card["rows"] if r["key"] == "revenue")
    assert rev["yoy"] == N.growth_pct(rev["current"], rev["year_ago"])


def test_bank_ebitda_not_meaningful(client):
    r = client.post("/api/research/query", json={"ticker": "HDFCBANK", "question": "What was EBITDA growth YoY?"}).json()
    assert r["route"] == "metric" and "N/A" in r["answer"]
    fin = client.get("/api/research/HDFCBANK").json()["overview"]["latest_quarter"]
    eb = next(x for x in fin["rows"] if x["key"] == "ebitda")
    assert eb["current"] is None and eb["note"]


def test_titan_guidance(client):
    g = client.get("/api/research/TITAN/management-guidance").json()
    assert g["summary"]["missed"] == 2 and g["summary"]["hit_rate"] == 33
    assert any(r["direction"] == "down" for r in g["revisions"])
    assert all(r["citation"]["page"] for r in g["rows"])


def test_unknown_evidence_refusal(client):
    r = client.post("/api/research/query", json={"ticker": "HAL", "question": "What are the key risks to the business?"}).json()
    assert "could not verify" in r["answer"] and r["citations"] == []


def test_metric_route_deterministic(client):
    r = client.post("/api/research/query", json={"ticker": "TITAN", "question": "What was PAT growth YoY?"}).json()
    assert r["route"] == "metric" and r["engine"] == "deterministic"


def test_alert_crud(client):
    bad = client.post("/api/alerts", json={"kind": "price_up", "priority": "high"})
    assert bad.status_code == 422
    r = client.post("/api/alerts", json={"kind": "price_up", "threshold": 3, "ticker": "KPITTECH", "priority": "high"})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.patch(f"/api/alerts/{rid}", json={"threshold": 2.5}).json()["threshold"] == 2.5
    assert client.delete(f"/api/alerts/{rid}").status_code == 200
    assert client.delete(f"/api/alerts/{rid}").status_code == 404


def test_portfolio_add_remove(client):
    assert client.post("/api/portfolio", json={"ticker": "TRENT"}).status_code == 200
    assert client.delete("/api/portfolio/TRENT").status_code == 200
    assert client.delete("/api/portfolio/TRENT").status_code == 404


def test_error_shapes(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert client.get("/api/signals/999999").status_code == 404
    assert client.post("/api/research/query", json={"ticker": "TITAN", "question": "x"}).status_code == 422
