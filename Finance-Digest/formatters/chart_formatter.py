"""Matplotlib chart generation for paper trading reports."""
from __future__ import annotations

import io
from datetime import datetime

import matplotlib
matplotlib.use('Agg')  # headless — must be before pyplot import
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker


def build_portfolio_chart(
    daily_values: list[dict],
    spy_history: list[tuple[str, float]],
    starting_cash: float = 10_000.0,
) -> io.BytesIO:
    """
    Line chart: portfolio value vs SPY (both normalized to starting_cash).
    Returns PNG as BytesIO.
    """
    fig, ax = plt.subplots(figsize=(10, 4.5))

    if daily_values:
        dates = [datetime.strptime(r["snapshot_date"], "%Y-%m-%d") for r in daily_values]
        values = [r["portfolio_value"] for r in daily_values]
        ax.plot(dates, values, color="#2563EB", linewidth=2, label="Paper Portfolio", zorder=3)

    if spy_history and len(spy_history) > 1:
        spy_dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in spy_history]
        spy_base = spy_history[0][1]
        spy_norm = [starting_cash * price / spy_base for _, price in spy_history]
        ax.plot(spy_dates, spy_norm, color="#9CA3AF", linewidth=1.5,
                linestyle="--", label="SPY (normalized)", zorder=2)

    ax.axhline(y=starting_cash, color="#D1D5DB", linewidth=1, linestyle=":", zorder=1)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.AutoDateFormatter(mdates.AutoDateLocator()))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax.set_title("Paper Portfolio vs SPY Benchmark", fontsize=13, fontweight="bold", pad=10)
    ax.set_ylabel("Portfolio Value", fontsize=10)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf


def build_allocation_chart(
    daily_positions: list[dict],
) -> io.BytesIO:
    """
    Stacked area chart showing % allocation per ticker over time.
    Includes a CASH band. Returns PNG as BytesIO.
    """
    if not daily_positions:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "No position history yet", ha="center", va="center",
                transform=ax.transAxes, fontsize=12, color="#6B7280")
        ax.set_title("Historical Portfolio Allocation", fontsize=13, fontweight="bold")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        plt.close(fig)
        return buf

    # Pivot: {date: {ticker: weight_pct}}
    pivot: dict[str, dict[str, float]] = {}
    for row in daily_positions:
        d = row["snapshot_date"]
        pivot.setdefault(d, {})[row["ticker"]] = row["weight_pct"]

    all_dates = sorted(pivot.keys())
    all_tickers = sorted(
        {r["ticker"] for r in daily_positions if r["ticker"] != "CASH"},
        key=lambda t: -max(pivot[d].get(t, 0) for d in all_dates)
    )
    # CASH always last (bottom of stack = top visual band)
    ordered = all_tickers + ["CASH"]

    dates_dt = [datetime.strptime(d, "%Y-%m-%d") for d in all_dates]

    # Build weight matrix
    weights: dict[str, list[float]] = {
        t: [pivot[d].get(t, 0.0) for d in all_dates]
        for t in ordered
    }

    cmap = plt.get_cmap("tab10")
    colors = [cmap(i % 10) for i in range(len(all_tickers))]
    colors.append("#E5E7EB")  # light grey for CASH

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.stackplot(
        dates_dt,
        [weights[t] for t in ordered],
        labels=ordered,
        colors=colors,
        alpha=0.85,
    )

    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.AutoDateFormatter(mdates.AutoDateLocator()))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax.set_title("Historical Portfolio Allocation", fontsize=13, fontweight="bold", pad=10)
    ax.set_ylabel("Allocation %", fontsize=10)
    ax.legend(loc="upper left", fontsize=8, ncol=2, framealpha=0.7)
    ax.grid(axis="y", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf
