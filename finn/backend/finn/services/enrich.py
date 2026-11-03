"""Per-category enrichment for pushed items.

management_change: SEBI LODR (Reg. 30, Schedule III) requires a "brief profile" of any appointed director/KMP
in the filing itself, so FINN reads the bio straight from the primary document — no LinkedIn scraping
(which violates LinkedIn's terms). A LinkedIn *search link* is attached for the investor to click.
"""
from __future__ import annotations

import re
import urllib.parse

from . import llm

_AMOUNT = re.compile(
    r"(?:rs\.?|₹|inr)\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr\.?|lakhs?|lacs?|million|mn|billion|bn)\b"
    r"|([\d,]+(?:\.\d+)?)\s*(crores?|cr\b)",
    re.I,
)


def extract_amount_cr(text: str) -> float | None:
    """Largest INR amount mentioned, in crore. Used for financial-impact scoring."""
    best = None
    for m in _AMOUNT.finditer(text or ""):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        u = unit.lower()
        if u.startswith("lak") or u.startswith("lac"):
            v /= 100
        elif u in ("million", "mn"):
            v /= 10
        elif u in ("billion", "bn"):
            v *= 100
        best = v if best is None else max(best, v)
    return best


_ROLE = r"(Chief Executive Officer|Chief Financial Officer|Managing Director(?: (?:&|and) CEO)?|Whole[- ]Time Director|Chief Operating Officer|Company Secretary|Independent Director|Non-Executive Director|Executive Director|Director|CEO|CFO|COO)"


def management_change(subject: str, text: str) -> dict:
    """Return {people:[{name, role, change, effective, profile, linkedin_search}], method}."""
    if llm.available() and text:
        out = llm.complete_json(
            [
                {
                    "role": "system",
                    "content": "Extract management changes from an Indian corporate filing. Use only facts in the text. "
                    'Reply JSON {"people":[{"name":str,"role":str,"change":"appointment|resignation|retirement|re-appointment|cessation",'
                    '"effective":str|null,"reason":str|null,"profile":str|null}]}. profile = the brief profile/background given in the filing, '
                    "condensed to <=45 words (prior employers, roles, education, years of experience). null if the filing has none.",
                },
                {"role": "user", "content": f"Subject: {subject}\n\n{text[:7000]}"},
            ],
            tier="fast",
            max_tokens=600,
        )
        if out and out.get("people"):
            for p in out["people"]:
                p["linkedin_search"] = _li(p.get("name"))
            return {"people": out["people"], "method": "llm", "source": "filing text"}
    return _rules_management(subject, text)


def _li(name: str | None) -> str | None:
    if not name:
        return None
    return "https://www.linkedin.com/search/results/people/?keywords=" + urllib.parse.quote(name)


_HON = r"(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Shri|Smt\.?)\s+"
_NAME = r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z.]+){0,3})"


def _rules_management(subject: str, text: str) -> dict:
    """Deterministic fallback: one entry per person, with the change attributed from the verb near their name."""
    blob = f"{subject}\n{text or ''}"
    people: dict[str, dict] = {}
    for m in re.finditer(_HON + _NAME, blob):
        name = m.group(1).strip().rstrip(".")
        if name in people:
            continue
        ctx = blob[max(0, m.start() - 120): m.end() + 220]
        after = blob[m.end(): m.end() + 220]
        if re.search(r"resign|tendered|step(ping)? down|cessation|ceased", after, re.I):
            change = "resignation"
        elif re.search(r"retire|superannuat", after, re.I):
            change = "retirement"
        elif re.search(r"appoint", ctx, re.I):
            change = "appointment"
        else:
            continue  # a name with no change attached (e.g. a signatory)
        role_m = re.search(_ROLE, after, re.I) or re.search(_ROLE, ctx, re.I)
        eff = re.search(r"(?:w\.?e\.?f\.?|with effect from|effective(?: from)?)\s*(?:close of business hours on\s*)?([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+[0-9]{4}|[0-9]{1,2}[\-/.][0-9]{1,2}[\-/.][0-9]{2,4})", after, re.I)
        people[name] = {"name": name, "role": role_m.group(1) if role_m else None, "change": change,
                        "effective": eff.group(1).strip() if eff else None, "reason": None, "profile": None, "linkedin_search": _li(name)}
        rm = re.search(r"to pursue ([^.,]{5,80})", after, re.I)
        if change == "resignation" and rm:
            people[name]["reason"] = "to pursue " + rm.group(1).strip()
    for pm in re.finditer(r"brief profile(?: of)?\s*(?:" + _HON + r")?([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z.]+){0,3})?\s*[:\n-]\s*(.{40,900}?)(?:\n\s*\n|disclosure of relationship|$)", blob, re.I | re.S):
        who = (pm.group(1) or "").strip().rstrip(".")
        words = re.sub(r"\s+", " ", pm.group(2)).split()
        prof = " ".join(words[:48]) + ("…" if len(words) > 48 else "")
        target = people.get(who) or next((p for p in people.values() if p["change"] == "appointment"), None)
        if target:
            target["profile"] = prof
    if not people:
        people["?"] = {"name": None, "role": (re.search(_ROLE, blob, re.I) or [None, None])[1] if re.search(_ROLE, blob, re.I) else None,
                       "change": "appointment" if re.search(r"appoint", blob, re.I) else "resignation" if re.search(r"resign", blob, re.I) else "change",
                       "effective": None, "reason": None, "profile": None, "linkedin_search": None}
    order = {"appointment": 0, "re-appointment": 0, "resignation": 1, "retirement": 1, "cessation": 1}
    return {"people": sorted(people.values(), key=lambda p: order.get(p["change"], 2)), "method": "rules", "source": "filing text"}


def one_line_summary(subject: str, text: str | None, category: str) -> tuple[str, str]:
    """(summary, method). Cheap model when available; otherwise a cleaned subject line."""
    clean = re.sub(r"\s+", " ", subject).strip()
    if text and llm.available() and category not in ("unclassified", "investor_meetings", "agm_egm", "postal_ballot"):
        out = llm.complete(
            [
                {
                    "role": "system",
                    "content": "Summarise this Indian corporate filing for a busy investor in ONE sentence (<=28 words). "
                    "State the concrete fact (what, how much, when). No adjectives, no speculation, no advice. "
                    "If the text has no substantive content, repeat the subject plainly.",
                },
                {"role": "user", "content": f"Subject: {clean}\n\n{text[:3500]}"},
            ],
            tier="fast",
            max_tokens=80,
        )
        if out:
            return out.strip().strip('"'), "llm"
    return clean[0].upper() + clean[1:] if clean else clean, "subject"
