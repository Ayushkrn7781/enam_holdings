"""Database schema. Every row carries `source` so provenance survives the whole pipeline.

source values: "nse", "bse", "screener", "yfinance", "pdf", "llm", "demo" (illustrative, never real).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.utcnow()


class Company(Base):
    __tablename__ = "companies"
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str] = mapped_column(String(80), default="Unknown")
    is_financial: Mapped[bool] = mapped_column(Boolean, default=False)  # banks/NBFCs: EBITDA, D/E not meaningful
    about: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="seed")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Holding(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), unique=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    company: Mapped[Company] = relationship()


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("ticker", "date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20))


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("dedupe_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    exchange_category: Mapped[str | None] = mapped_column(String(200))  # exchange's own label
    attachment_url: Mapped[str | None] = mapped_column(Text)
    attachment_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20))
    dedupe_key: Mapped[str] = mapped_column(String(64))

    # --- derived by the signal engine ---
    category: Mapped[str | None] = mapped_column(String(40), index=True)
    category_method: Mapped[str | None] = mapped_column(String(20))  # "rules" | "llm"
    score: Mapped[float | None] = mapped_column(Float, index=True)
    priority: Mapped[str | None] = mapped_column(String(10))
    score_breakdown: Mapped[dict | None] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text)
    enrichment: Mapped[dict | None] = mapped_column(JSON)  # results card / appointee bio / etc.
    is_duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FinancialPeriod(Base):
    """One reporting period of headline numbers, as published (crore INR)."""

    __tablename__ = "financial_periods"
    __table_args__ = (UniqueConstraint("ticker", "period_type", "period_end", "basis"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    period_type: Mapped[str] = mapped_column(String(1))  # "Q" quarterly, "Y" annual
    period_end: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(20))  # e.g. "Sep 2026"
    basis: Mapped[str] = mapped_column(String(14), default="consolidated")
    unit: Mapped[str] = mapped_column(String(12), default="INR crore")
    metrics: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(20))
    source_url: Mapped[str | None] = mapped_column(Text)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("ticker", "url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    doc_type: Mapped[str] = mapped_column(String(20))  # annual_report | transcript | results | presentation
    title: Mapped[str] = mapped_column(Text)
    period_label: Mapped[str | None] = mapped_column(String(20))  # "Q2 FY27", "FY26"
    period_end: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="discovered")  # discovered|downloaded|indexed|failed
    error: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20))
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    page: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10), default="text")  # text | table
    speaker: Mapped[str | None] = mapped_column(String(120))  # transcripts: who said it
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    document: Mapped[Document] = relationship(back_populates="chunks")


class Guidance(Base):
    __tablename__ = "guidance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id"))
    page: Mapped[int | None] = mapped_column(Integer)
    said_in: Mapped[str] = mapped_column(String(20))  # call where it was said, e.g. "Q1 FY26"
    statement: Mapped[str] = mapped_column(Text)  # verbatim
    speaker: Mapped[str | None] = mapped_column(String(120))
    metric: Mapped[str] = mapped_column(String(30))  # revenue_growth | ebitda_margin | pat_growth | capex | volume | qualitative
    target_low: Mapped[float | None] = mapped_column(Float)
    target_high: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(10))  # "%", "INR cr"
    horizon: Mapped[str | None] = mapped_column(String(30))  # "FY26", "next quarter", "medium term"
    commitment: Mapped[str] = mapped_column(String(15))  # explicit_target | range | outlook | qualitative
    method: Mapped[str] = mapped_column(String(10))  # llm | rules


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None = whole portfolio
    kind: Mapped[str] = mapped_column(String(20))  # price_up | price_down | volume | category
    threshold: Mapped[float | None] = mapped_column(Float)
    category: Mapped[str | None] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(10), default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("rule_id", "ticker", "ref"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"))
    ticker: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(String(64))  # "px:2026-11-02" or "ann:123"
    triggered_at: Mapped[datetime] = mapped_column(DateTime)
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    announcement_id: Mapped[int | None] = mapped_column(Integer)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)


class LLMCache(Base):
    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(80))
    response: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ResearchLog(Base):
    __tablename__ = "research_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(String(30))
    answer: Mapped[dict] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Meta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
