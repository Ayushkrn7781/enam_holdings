"""Core correctness tests: arithmetic, classification, scoring, parsing, grading, retrieval, API."""
import os
import tempfile

os.environ.setdefault("FINN_DATA_DIR", tempfile.mkdtemp(prefix="finn-test-"))
os.environ.pop("GROQ_API_KEY", None)  # tests must pass with no LLM

import pytest
from fastapi.testclient import TestClient

from finn.research.guidance import _grade, _horizon, _rules_extract, _targets, _verbatim
from finn.research.periods import fy_end, next_quarter, quarter_end, quarter_label
from finn.research.retrieval import split_sentences, tokenize
from finn.services import materiality
from finn.services.enrich import extract_amount_cr, management_change
from finn.services.numbers import daily_return_pct, fmt_cr, growth_pct, margin_pct, volume_ratio
from finn.services.results import parse_results_pages
from finn.services.taxonomy import classify


# ---------------------------------------------------------------- arithmetic
def test_growth_basic_and_na():
    assert growth_pct(110, 100) == 10.0
    assert growth_pct(90, 100) == -10.0
    assert growth_pct(100, 0) is None  # never invent a % on a zero base
    assert growth_pct(None, 100) is None
    assert growth_pct(-50, -100) == 50.0  # loss narrowed -> positive


def test_ratios():
    assert margin_pct(25, 200) == 12.5
    assert daily_return_pct(102, 100) == 2.0
    assert volume_ratio(300, [100, 100, 100]) == 3.0
    assert volume_ratio(300, []) is None


def test_indian_number_format():
    assert fmt_cr(1234567) == "₹12,34,567 Cr"
    assert fmt_cr(None) == "N/A"


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize("subject,excat,expected", [
    ("Outcome of Board Meeting - Unaudited Financial Results for the quarter ended 30 September 2026", "Outcome of Board Meeting", "results"),
    ("Resignation of Chief Financial Officer", None, "management_change"),
    ("Acquisition of 100% stake in XYZ GmbH", "Acquisition", "M&A"),
    ("Closure of trading window", "Trading Window", "unclassified"),
    ("Compliance certificate under Regulation 74(5)", None, "unclassified"),
    ("Intimation of participation in an investor conference", "Analysts/Institutional Investor Meet/Con. Call Updates", "investor_meetings"),
    ("Transcript of the earnings conference call", "Analysts/Institutional Investor Meet/Con. Call Updates", "earnings_call"),
    ("Credit rating reaffirmed by CRISIL", "Credit Rating", "credit_rating"),
    ("USFDA inspection concluded with three observations (Form 483)", "Updates", "litigation"),
    ("Creation of pledge on promoter shares", None, "pledging"),
    ("Record date for interim dividend", "Record Date", "dividend"),
])
def test_classifier(subject, excat, expected):
    assert classify(subject, excat).category == expected


# ---------------------------------------------------------------- materiality
def test_score_is_weighted_sum_and_bands():
    comps = {k: materiality.Component(v, "") for k, v in dict(category=100, financial=100, deviation=100, relevance=100, novelty=100).items()}
    total, br = materiality.score(comps)
    assert total == 100.0 and sum(x["contribution"] for x in br.values()) == pytest.approx(100.0)
    assert materiality.priority_for(80) == "critical" and materiality.priority_for(79.9) == "high"
    assert materiality.priority_for(35) == "medium" and materiality.priority_for(34.9) == "low"


def test_amount_extraction():
    assert extract_amount_cr("consideration of up to Rs. 950 crore") == 950
    assert extract_amount_cr("Rs. 2,500 crore to Rs. 5,000 crore") == 5000
    assert extract_amount_cr("EUR 96 million") is None
    assert extract_amount_cr("₹ 120 lakh") == 1.2


# ---------------------------------------------------------------- results filing parser
FILING = """Statement of Unaudited Consolidated Financial Results for the quarter ended 30 September 2026
(Rs. in lakhs)
1 Revenue from operations    1,000,000.00    900,000.00    800,000.00
2 Other income    10,000.00    9,000.00    8,000.00
  b) Finance costs    5,000.00    5,000.00    4,000.00
  c) Depreciation and amortisation expense    20,000.00    19,000.00    18,000.00
5 Profit before exceptional items and tax    85,000.00    76,000.00    66,000.00
7 Profit before tax    85,000.00    76,000.00    66,000.00
9 Net profit for the period    63,750.00    57,000.00    49,500.00
"""


def test_results_parser_units_and_columns():
    p = parse_results_pages(["cover page", FILING])
    assert p["page"] == 2 and p["basis"] == "consolidated" and p["unit_in_filing"] == "lakh"
    assert p["current"]["revenue"] == 10000.0  # lakh -> crore
    assert p["year_ago"]["pat"] == 495.0
    # EBITDA = PBT + finance + depreciation - other income  (computed, never read from an LLM)
    assert p["current"]["ebitda"] == pytest.approx(850 + 50 + 200 - 100)


# ---------------------------------------------------------------- periods & guidance
def test_fiscal_periods():
    from datetime import date

    assert quarter_label(date(2026, 9, 30)) == "Q2 FY27"
    assert quarter_end("Q4 FY26") == date(2026, 3, 31)
    assert next_quarter("Q4 FY26") == "Q1 FY27"
    assert fy_end("FY26") == date(2026, 3, 31)


def test_guidance_target_parsing():
    assert _targets("we expect revenue growth of 30% to 35%") == (30.0, 35.0, "%")
    assert _targets("growth of at least 15% year-on-year") == (15.0, None, "%")
    assert _targets("growth of around 20%") == (19.5, 20.5, "%")
    assert _targets("Capex for FY26 will be about Rs. 1,000 crore") == (1000.0, 1000.0, "INR cr")
    assert _horizon("For Q1 FY27 we expect margins of 4%", "Q4 FY26") == "Q1 FY27"
    assert _horizon("For the next quarter we expect growth of 30%", "Q1 FY27") == "Q2 FY27"
    assert _horizon("over the medium term we aspire to 4.5%", "Q2 FY27") == "medium term"


def test_grading():
    assert _grade(4.0, 4.2, 3.7, "%")[0] == "missed"
    assert _grade(4.0, 4.2, 4.1, "%")[0] == "achieved"
    assert _grade(30, 35, 38, "%") == ("exceeded", 3.0)
    assert _grade(25, None, 22.2, "%")[0] == "missed"
    assert _grade(25, None, None, "%")[0] == "not_comparable"


def test_backward_looking_statements_are_not_guidance():
    class C:  # minimal chunk stub
        text = "Revenue grew 38% last year. We expect FY27 revenue growth of 30% to 35%."

    items = _rules_extract(C, "Q4 FY26")
    assert len(items) == 1 and items[0]["horizon"] == "FY27"


def test_verbatim_check_rejects_invented_quotes():
    src = "We expect FY27 revenue growth of 30% to 35% led by mobiles."
    assert _verbatim("We expect FY27 revenue growth of 30% to 35%", src)
    assert not _verbatim("We guarantee 50% growth every year", src)


def test_sentence_splitter_handles_rs():
    assert split_sentences("Capex will be Rs. 1,000 crore. Margins should improve.") == ["Capex will be Rs. 1,000 crore.", "Margins should improve."]


def test_management_change_rules_two_people():
    txt = ("Mr. Kunal Mehrotra has tendered his resignation as Chief Financial Officer with effect from 30 November 2026. "
           "The Board has appointed Ms. Ritika Sharan as Chief Financial Officer with effect from 1 December 2026.\n\n"
           "Brief profile of Ms. Ritika Sharan:\nMs. Ritika Sharan is a Chartered Accountant with 22 years of experience.\n\n")
    out = management_change("CFO change", txt)
    byname = {p["name"]: p for p in out["people"]}
    assert byname["Ritika Sharan"]["change"] == "appointment" and "Chartered Accountant" in byname["Ritika Sharan"]["profile"]
    assert byname["Kunal Mehrotra"]["change"] == "resignation" and byname["Kunal Mehrotra"]["profile"] is None


# ---------------------------------------------------------------- end-to-end on the demo dataset
@pytest.fixture(scope="module")
def client():
    from finn.api.app import app

    with TestClient(app) as c:
        yield c


def test_api_digest_ranked_and_routine_collapsed(client):
    d = client.get("/api/digest?hours=24").json()
    scores = [x["score"] for x in d["material"]]
    assert scores == sorted(scores, reverse=True)
    assert all(x["priority"] == "low" for x in d["routine"])
    assert d["counts"]["total"] == len(d["material"]) + len(d["routine"])
    assert d["material"][0]["ticker"] == "DIXON"


def test_api_results_card_verified_against_filing(client):
    d = client.get("/api/digest?hours=24").json()
    dixon = next(x for x in d["material"] if x["ticker"] == "DIXON" and x["has_results"])
    sig = client.get(f"/api/signals/{dixon['id']}").json()
    card = sig["enrichment"]["results"]
    assert card["verification"]["status"] == "verified"
    rev = next(r for r in card["rows"] if r["metric"] == "revenue")
    assert rev["yoy_pct"] == growth_pct(rev["current"], rev["year_ago"])


def test_api_bank_has_no_ebitda(client):
    card = client.get("/api/companies/HDFCBANK/financials").json()["latest_results"]
    e = next(r for r in card["rows"] if r["metric"] == "ebitda")
    assert e["current"] is None and e["qoq_pct"] is None and e["note"]


def test_api_promise_vs_delivered(client):
    sc = client.get("/api/research/TITAN/management-guidance").json()
    assert sc["status"] == "ok"
    assert any(r["status"] == "missed" for r in sc["rows"])
    assert any(rv["direction"] == "down" for rv in sc["summary"]["revisions"])
    for r in sc["rows"]:
        assert r["citation"]["page"] is not None


def test_api_insufficient_evidence_is_honest(client):
    r = client.post("/api/research/query", json={"ticker": "HAL", "question": "What risks does management disclose?"}).json()
    assert "could not verify" in r["answer"].lower() and r["citations"] == []


def test_api_metric_route_is_deterministic(client):
    r = client.post("/api/research/query", json={"ticker": "TITAN", "question": "What was PAT growth?"}).json()
    assert r["route"] == "metric" and r["engine"] == "deterministic"


def test_api_alert_crud(client):
    r = client.post("/api/alerts", json={"kind": "volume", "threshold": 1.2, "ticker": "DIXON"})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.patch(f"/api/alerts/{rid}", json={"enabled": False}).json()["enabled"] is False
    assert client.delete(f"/api/alerts/{rid}").status_code == 200
    assert client.post("/api/alerts", json={"kind": "price_up"}).status_code == 422


def test_api_portfolio_add_remove(client):
    assert client.post("/api/portfolio", json={"ticker": "TRENT"}).status_code == 201
    assert any(i["ticker"] == "TRENT" for i in client.get("/api/portfolio").json()["items"])
    assert client.delete("/api/portfolio/TRENT").status_code == 200
    assert client.delete("/api/portfolio/TRENT").status_code == 404


def test_tokenize_stems():
    assert "invest" in tokenize("investing") and "invest" in tokenize("investment")
