"""Shared dataclasses used across the project."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Company:
    ticker: str
    name: str | None
    list_type: str          # 'portfolio' or 'watchlist'
    added_at: str
    notes: str | None = None


@dataclass
class InvestmentThesis:
    ticker: str
    strengths: str | None = None
    weaknesses: str | None = None
    opportunities: str | None = None
    threats: str | None = None
    moat: str | None = None
    entry_rationale: str | None = None
    target_price: float | None = None
    questions: str | None = None
    updated_at: str | None = None

    def to_prompt_block(self) -> str:
        """Format thesis as a structured block for LLM prompts."""
        parts = []
        if self.strengths:
            parts.append(f"Strengths: {self.strengths}")
        if self.weaknesses:
            parts.append(f"Weaknesses: {self.weaknesses}")
        if self.opportunities:
            parts.append(f"Opportunities: {self.opportunities}")
        if self.threats:
            parts.append(f"Threats: {self.threats}")
        if self.moat:
            parts.append(f"Competitive Moat: {self.moat}")
        if self.entry_rationale:
            parts.append(f"Entry Rationale: {self.entry_rationale}")
        if self.target_price:
            parts.append(f"Personal Target Price: ${self.target_price:.2f}")
        if self.questions:
            parts.append(f"Open Questions: {self.questions}")
        return "\n".join(parts) if parts else "[No thesis recorded]"


@dataclass
class CompanySnapshot:
    ticker: str
    name: str
    list_type: str
    quote: dict[str, Any] = field(default_factory=dict)
    technicals: dict[str, Any] = field(default_factory=dict)
    financials: dict[str, Any] = field(default_factory=dict)
    cagr: dict[str, Any] = field(default_factory=dict)           # multi-period CAGR
    common_size: dict[str, Any] = field(default_factory=dict)    # income stmt as % revenue
    returns: dict[str, Any] = field(default_factory=dict)        # ROIC, ROCE, ROE history
    capex: dict[str, Any] = field(default_factory=dict)          # CapEx history + % of revenue
    financial_health: dict[str, Any] = field(default_factory=dict)  # FCF, net debt, shares, coverage, etc.
    news: list[dict[str, Any]] = field(default_factory=list)
    sentiment: dict[str, Any] = field(default_factory=dict)
    earnings: dict[str, Any] = field(default_factory=dict)
    analyst_targets: dict[str, Any] = field(default_factory=dict)
    insider_transactions: list[dict[str, Any]] = field(default_factory=list)
    peers: list[dict[str, Any]] = field(default_factory=list)    # peer comparison data
    sec_summary: str | None = None
    sec_form_type: str | None = None
    strategy_excerpt: str | None = None   # earnings call / MD&A excerpt
    errors: list[str] = field(default_factory=list)
    snapshot_time: datetime = field(default_factory=datetime.utcnow)

    def has_data(self) -> bool:
        return bool(self.quote or self.financials)


@dataclass
class OpportunityScore:
    ticker: str
    name: str | None
    score: int
    signals: list[str] = field(default_factory=list)  # human-readable triggered signals
    piotroski_fscore: int | None = None               # 0-9 Piotroski F-Score (None = insufficient data)
    llm_evaluation: str | None = None
    snapshot: CompanySnapshot | None = None
