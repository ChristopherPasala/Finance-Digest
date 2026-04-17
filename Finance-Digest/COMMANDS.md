# Finance Digest — Discord Commands

All commands are Discord slash commands. Type `/` in any channel where the bot has access to see them.

---

## `/add`

Add a stock to your **portfolio** or **watchlist**.

- **Portfolio** — companies you currently own. Gets a full briefing each morning including thesis integrity checks.
- **Watchlist** — companies you're monitoring. Gets a lighter briefing with entry point analysis.

The ticker is validated against Yahoo Finance before being saved. Only valid US stock symbols are accepted (1–5 uppercase letters).

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `ticker` | Yes | Stock symbol, e.g. `AAPL` |
| `list_type` | No | `Portfolio` or `Watchlist` (defaults to Watchlist) |

**Examples**

```
/add AAPL
/add NVDA Watchlist
/add MSFT Portfolio
```

---

## `/remove`

Remove a stock from tracking entirely (portfolio or watchlist).

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `ticker` | Yes | Stock symbol to remove |

**Examples**

```
/remove AAPL
/remove TSLA
```

---

## `/list`

Show all currently tracked companies, grouped by portfolio and watchlist, with the date each was added.

**Examples**

```
/list
```

**Sample output**

```
📈 Portfolio
• AAPL — Apple Inc. (added 2026-03-01)
• MSFT — Microsoft Corporation (added 2026-03-01)

👀 Watchlist
• NVDA — NVIDIA Corporation (added 2026-03-15)
• AMD — Advanced Micro Devices (added 2026-03-20)
```

---

## `/analyze`

Run a full **6-step deep-dive analysis** on any stock ticker and receive a formatted PDF report.

The six steps follow a professional portfolio manager's research framework:

1. **Data collection** — price, financials, technicals, news, SEC filings
2. **Business Understanding** — SWOT analysis, competitive moat, revenue type
3. **Financial Analysis** — CAGR (5/10yr), margins, ROIC, debt, FCF yield
4. **Strategy Assessment** — management priorities, capex trends, capital allocation
5. **Valuation** — P/E vs history, EV/EBITDA, analyst targets, FCF yield
6. **Thesis Check** — compares today's data against your stored thesis (if one exists)

Takes **2–5 minutes**. The bot will acknowledge immediately while the analysis runs in the background.

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `ticker` | Yes | Stock to analyze |

**Examples**

```
/analyze AAPL
/analyze AMD
/analyze NVDA
```

**Output:** A PDF file attachment (e.g. `finance_analysis_AAPL_2026-03-22.pdf`)

---

## `/briefing`

Manually trigger a **full morning briefing** for all tracked companies right now, without waiting for the scheduled time.

Generates the same report as the automatic daily briefing:
- Portfolio company updates with thesis integrity checks
- Watchlist entry point analysis
- Top opportunity scores
- Weekly new ticker suggestions (if it has been 7+ days since the last suggestion)

The briefing is posted as a PDF to your configured briefing channel. Takes several minutes depending on how many companies you track.

**Examples**

```
/briefing
```

**Output:** PDF posted to the briefing channel (e.g. `finance_briefing_2026-03-22.pdf`)

---

## `/opportunities`

Score your **watchlist** companies and surface the best current investment opportunities using a quantitative signal model.

**How scoring works:**

| Signal | Points |
|--------|--------|
| RSI below 30 (oversold) | +2 |
| Earnings surprise above 5% | +2 |
| Analyst consensus buy/strong-buy | +2 |
| Price below analyst mean target | +2 |
| Revenue beat | +1 |
| Price below 52-week average | +1 |
| News sentiment bullish | +1 |
| ROIC above 15% | +1 |
| Negative headlines (fraud/lawsuit) | -2 |
| Earnings miss above 5% | -2 |
| High debt (D/E > 2.0) | -1 |

Companies scoring **4 or above** get an additional LLM evaluation with context from recent news.

**Examples**

```
/opportunities
```

**Output:** Scored embed showing top opportunities + LLM commentary for the top 3.

---

## `/screen`

Ask the LLM to **suggest new tickers** to research based on your existing portfolio themes.

Looks at the sectors, industries, and moats of your portfolio companies and suggests related candidates not already in your watchlist. Useful for expanding your universe.

Requires at least one company in your portfolio.

**Examples**

```
/screen
```

**Output:** A list of suggested tickers with brief rationale for each.

---

## `/thesis`

View or update your **investment thesis** for a tracked stock.

The thesis is used in two ways:
1. The `/analyze` command's Step 6 checks whether the data supports or challenges your thesis
2. The morning briefing flags any news that threatens your stored thesis

Running `/thesis TICKER` with no additional parameters **displays** the current thesis. Adding any parameter **updates** just that field — existing fields are preserved.

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `ticker` | Yes | Stock ticker |
| `moat` | No | What is the competitive advantage? |
| `entry_rationale` | No | Why did you add this to your portfolio/watchlist? |
| `strengths` | No | Key strengths (SWOT) |
| `weaknesses` | No | Key weaknesses (SWOT) |
| `opportunities` | No | Key opportunities (SWOT) |
| `threats` | No | Key threats (SWOT) |
| `target_price` | No | Your personal price target (number) |
| `questions` | No | Open questions to follow up on later |

**Examples**

```
/thesis AAPL
```
View the stored thesis for Apple.

```
/thesis NVDA moat:"Dominant GPU architecture for AI training, CUDA ecosystem lock-in" entry_rationale:"Positioned at the center of the AI infrastructure buildout"
```
Set the moat and entry rationale for NVIDIA.

```
/thesis MSFT target_price:450 questions:"Watch Azure growth rate — is it reaccelerating?"
```
Update only the target price and open questions, leaving all other fields unchanged.

---

## Automatic Morning Briefing

In addition to the slash commands, the bot automatically posts a morning briefing at the time configured in `.env` (`BRIEFING_TIME`, default `07:00` in `BRIEFING_TIMEZONE`).

The briefing covers:
- **Portfolio companies** — price update, earnings proximity, news summary, thesis check
- **Watchlist companies** — price vs entry point, analyst targets
- **Top opportunities** — highest-scoring watchlist companies with LLM evaluation
- **Weekly new ideas** — suggested tickers (once per week)

Output is a single PDF file posted to `BRIEFING_CHANNEL_ID`.
