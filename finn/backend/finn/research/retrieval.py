"""Hybrid retrieval: BM25 (always) + dense embeddings (optional, fastembed/ONNX) fused with Reciprocal Rank Fusion.

RRF(d) = sum_r 1 / (k + rank_r(d)),  k = 60   — transparent, no tuned score scales.
Metadata filters (doc_type, period) are applied before ranking. Indexes are cached per ticker.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Chunk, Document

log = logging.getLogger("finn.retrieval")
_lock = threading.Lock()
_cache: dict[str, "_Index"] = {}
_embedder = None

STOP = set("the a an of to in and or for on at by with from is are was were be been this that it its as we our us you your they their".split())
SYN = {  # light domain query expansion so plain-English questions hit accounting vocabulary
    "revenue": ["sales", "turnover", "topline", "income from operations"],
    "debt": ["borrowings", "leverage", "loans", "debentures"],
    "margin": ["ebitda", "operating profit", "opm"],
    "guidance": ["outlook", "expect", "target", "guide", "aspire", "aim"],
    "cash": ["cash flow", "operating activities", "free cash"],
    "risk": ["risks", "threats", "concerns", "headwinds"],
    "capex": ["capital expenditure", "capacity", "investment", "plant"],
    "profit": ["pat", "net profit", "earnings"],
    "business": ["operates", "segments", "products", "overview", "revenue mix", "businesses"],
    "does": ["operates", "businesses", "segments"],
}


_ABBR = re.compile(r"\b(Rs|Mr|Ms|Mrs|Dr|No|Nos|Co|Ltd|Pvt|Inc|vs|approx|e\.g|i\.e|viz|Sr|Jr|St)\.$", re.I)


def split_sentences(text: str) -> list[str]:
    """Sentence splitter that doesn't break on 'Rs.', 'Mr.', 'No.' and friends — common in Indian filings."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'₹])", text)
    out: list[str] = []
    for p in parts:
        if out and _ABBR.search(out[-1]):
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return [x.strip() for x in out if x.strip()]


def _stem(w: str) -> str:
    """Tiny suffix stripper (investing/investment/invest -> invest); enough for BM25 recall on financial prose."""
    for suf in ("ments", "ment", "ings", "ing", "ions", "ion", "ies", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokenize(t: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9%]+", t.lower()) if w not in STOP and len(w) > 1]


def expand(q: str) -> str:
    extra = []
    low = q.lower()
    for k, vs in SYN.items():
        if k in low:
            extra.extend(vs)
    return q + " " + " ".join(extra)


@dataclass
class Hit:
    chunk_id: int
    score: float
    bm25_rank: int | None
    dense_rank: int | None


class _Index:
    def __init__(self, chunks: list[Chunk], docs: dict[int, Document]):
        self.ids = [c.id for c in chunks]
        self.meta = {c.id: (docs[c.document_id].doc_type, docs[c.document_id].period_label) for c in chunks}
        self.bm25 = BM25Okapi([tokenize(f"{c.section or ''} {c.text}") for c in chunks]) if chunks else None
        self.vecs = None
        if settings.enable_dense and chunks:
            emb = _get_embedder()
            if emb is not None:
                self.vecs = np.array(list(emb.embed([c.text for c in chunks])), dtype=np.float32)
                self.vecs /= np.linalg.norm(self.vecs, axis=1, keepdims=True) + 1e-9


def _get_embedder():
    global _embedder
    if _embedder is None:
        try:
            from fastembed import TextEmbedding

            _embedder = TextEmbedding(settings.embed_model)
        except Exception as e:  # not installed / model download blocked
            log.warning("dense retrieval disabled: %s", e)
            _embedder = False
    return _embedder or None


def invalidate(ticker: str) -> None:
    with _lock:
        _cache.pop(ticker, None)


def _index(s: Session, ticker: str) -> _Index:
    with _lock:
        if ticker in _cache:
            return _cache[ticker]
    docs = {d.id: d for d in s.scalars(select(Document).where(Document.ticker == ticker, Document.status == "indexed")).all()}
    chunks = s.scalars(select(Chunk).where(Chunk.ticker == ticker).order_by(Chunk.id)).all() if docs else []
    chunks = [c for c in chunks if c.document_id in docs]
    idx = _Index(chunks, docs)
    with _lock:
        _cache[ticker] = idx
    return idx


def search(
    s: Session,
    ticker: str,
    query: str,
    k: int = 6,
    doc_types: list[str] | None = None,
    periods: list[str] | None = None,
) -> list[tuple[Chunk, Hit]]:
    idx = _index(s, ticker)
    if not idx.ids:
        return []
    allowed = [
        i for i, cid in enumerate(idx.ids)
        if (not doc_types or idx.meta[cid][0] in doc_types) and (not periods or idx.meta[cid][1] in periods)
    ]
    if not allowed:
        return []
    ranks: list[dict[int, int]] = []
    bm = idx.bm25.get_scores(tokenize(expand(query)))
    order = sorted(allowed, key=lambda i: -bm[i])
    bm_rank = {i: r for r, i in enumerate(order[:100]) if bm[i] > 0}
    ranks.append(bm_rank)
    dense_rank: dict[int, int] = {}
    if idx.vecs is not None:
        emb = _get_embedder()
        qv = np.array(list(emb.embed([query]))[0], dtype=np.float32)
        qv /= np.linalg.norm(qv) + 1e-9
        sims = idx.vecs @ qv
        dorder = sorted(allowed, key=lambda i: -sims[i])
        dense_rank = {i: r for r, i in enumerate(dorder[:100])}
        ranks.append(dense_rank)
    fused: dict[int, float] = {}
    for rk in ranks:
        for i, r in rk.items():
            fused[i] = fused.get(i, 0.0) + 1.0 / (60 + r + 1)
    top = sorted(fused.items(), key=lambda x: -x[1])[:k]
    by_id = {c.id: c for c in s.scalars(select(Chunk).where(Chunk.id.in_([idx.ids[i] for i, _ in top]))).all()}
    return [
        (by_id[idx.ids[i]], Hit(idx.ids[i], round(sc, 5), bm_rank.get(i), dense_rank.get(i) if dense_rank else None))
        for i, sc in top
        if idx.ids[i] in by_id
    ]


def mode() -> str:
    return "bm25+dense (RRF)" if settings.enable_dense and _get_embedder() else "bm25"
