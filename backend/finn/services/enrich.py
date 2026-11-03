"""Filing enrichment: who is involved in a management change, and ₹ amounts.

SEBI LODR requires the filing itself to carry a brief profile of an appointee, so the bio is read
from the filing. LinkedIn is not scraped (its terms forbid it); a people-search link is attached.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote_plus

from . import llm

_HON = r"(?:Mr|Ms|Mrs|Dr|Shri|Smt)\.?"
_NAME = re.compile(rf"\b{_HON}\s+((?:[A-Z][a-zA-Z'\-]+\.?\s?){{1,4}})")
_ROLE = re.compile(r"(Chief Financial Officer|Chief Executive Officer|Chief Operating Officer|Managing Director(?: and CEO)?|"
                   r"Whole[- ]time Director|Independent Director|Non-Executive Director|Company Secretary|"
                   r"Compliance Officer|Chairman|\bCFO\b|\bCEO\b|\bCOO\b|\bMD\b|Key Managerial Personnel|KMP)", re.I)
_EFF = re.compile(r"(?:w\.e\.f\.?|with effect from|effective(?: from)?)\s*(?:the\s+)?(?:close of business hours on\s+)?"
                  r"([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+,?\s+[0-9]{4}|[A-Z][a-z]+\s+[0-9]{1,2},?\s+[0-9]{4}|"
                  r"[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{2,4})", re.I)
_REASON = re.compile(r"(to pursue [^.;,]+)", re.I)
_PROFILE = re.compile(rf"Brief profile of\s+{_HON}?\s*([A-Z][\w .'\-]+?)\s*:\s*(.+?)(?:\n\s*\n|$)", re.S)

ROLE_CANON = {"cfo": "Chief Financial Officer", "ceo": "Chief Executive Officer", "coo": "Chief Operating Officer",
              "md": "Managing Director", "kmp": "Key Managerial Personnel"}


def linkedin_search(name: str, company: str | None = None) -> str:
    q = f"{name} {company or ''}".strip()
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(q)}"


def _canon_role(r: str) -> str:
    return ROLE_CANON.get(r.lower(), r.title() if r.isupper() is False else r)


def _clip_words(text: str, n: int) -> str:
    w = text.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def management_change_rules(text: str) -> list[dict]:
    text = text or ""
    profiles = {}
    for m in _PROFILE.finditer(text):
        profiles[m.group(1).strip().rstrip(".")] = " ".join(m.group(2).split())
    people: dict[str, dict] = {}
    for m in _NAME.finditer(text):
        name = " ".join(m.group(1).split()).rstrip(".")
        # drop trailing lowercase words captured by mistake
        name = " ".join(t for t in name.split() if t[0].isupper())
        if not name or name in people:
            continue
        after = text[m.end(): m.end() + 260]
        sent_end = re.search(r"(?<!\bw\.e\.f)\.\s+(?=[A-Z])", after)
        ctx = after[: sent_end.start() + 1] if sent_end else after
        # same-sentence lead-in, e.g. "approved the appointment of Ms. X"
        before = text[max(0, m.start() - 100): m.start()]
        before = re.split(r"(?<!\bw\.e\.f)\.\s+(?=[A-Z])|\n", before)[-1]
        change = None
        if re.search(r"resign|tender(ed)? (his|her) resignation|cessation|ceases?|stepp(ed|ing) down", ctx, re.I):
            change = "leaves"
        elif re.search(r"retir", ctx, re.I):
            change = "retires"
        elif re.search(r"appoint|joins|designated|elevated|re-appoint", before + " " + ctx, re.I):
            change = "joins"
        if not change:
            continue
        role_m = _ROLE.search(ctx)
        eff = _EFF.search(ctx)
        reason = _REASON.search(ctx)
        people[name] = {"name": name, "role": _canon_role(role_m.group(1)) if role_m else None, "change": change,
                        "effective": eff.group(1) if eff else None,
                        "reason": reason.group(1).strip() if reason else None, "profile": None, "method": "rules"}
    for pname, prof in profiles.items():
        target = next((p for n, p in people.items() if n.endswith(pname) or pname.endswith(n)), None)
        if target is None:
            target = next((p for p in people.values() if p["change"] == "joins"), None)
        if target is not None:
            target["profile"] = _clip_words(prof, 60)
    out = sorted(people.values(), key=lambda p: 0 if p["change"] == "joins" else 1)
    return out


def management_change(text: str, company: str | None = None) -> list[dict]:
    people: list[dict] = []
    if llm.available() and text:
        res = llm.complete_json([
            {"role": "system", "content": "Extract people from an Indian exchange filing about a management change. "
                                          "Use only the filing text. JSON only."},
            {"role": "user", "content": 'Return {"people":[{"name","role","change":"joins|leaves|retires",'
                                        '"effective","reason","profile"}]} where profile is <=45 words taken from the '
                                        f"filing's brief profile, or null.\n\n{text[:5000]}"},
        ], tier="fast")
        if isinstance(res, dict) and isinstance(res.get("people"), list):
            for p in res["people"]:
                if isinstance(p, dict) and p.get("name") and p["name"].split()[-1] in text:
                    p["method"] = "llm"
                    if p.get("profile"):
                        p["profile"] = _clip_words(str(p["profile"]), 45)
                    people.append(p)
    if not people:
        people = management_change_rules(text)
    for p in people:
        p["linkedin_search"] = linkedin_search(p["name"], company)
        p["profile_source"] = "Brief profile disclosed in the filing (SEBI LODR)" if p.get("profile") else None
    people.sort(key=lambda p: 0 if p.get("change") == "joins" else 1)
    return people


_U = r"(crores?|cr\b|lakhs?|lacs?|millions?|mn\b|billions?|bn\b)"
_AMT = re.compile(r"(?:Rs\.?|₹|INR)\s*([0-9][0-9,]*(?:\.[0-9]+)?)(?:\s*(?:crores?|cr)?\s*(?:to|-|–)\s*(?:Rs\.?|₹|INR)?\s*"
                  r"([0-9][0-9,]*(?:\.[0-9]+)?))?\s*" + _U, re.I)


def amount_cr(text: str) -> Optional[float]:
    """Largest ₹ amount in the text, in crore. Foreign-currency amounts are ignored."""
    best = None
    for m in _AMT.finditer(text or ""):
        v = max(float(x.replace(",", "")) for x in (m.group(1), m.group(2)) if x)
        unit = m.group(3).lower()
        if unit.startswith("cr"):
            cr = v
        elif unit.startswith(("lakh", "lac")):
            cr = v / 100
        elif unit.startswith(("million", "mn")):
            cr = v / 10
        else:
            cr = v * 100
        best = cr if best is None else max(best, cr)
    return round(best, 2) if best is not None else None
