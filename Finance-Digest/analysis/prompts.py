"""All LLM prompt templates.

Data is injected via Python .format(**kwargs) so fields are {field_name}.
Missing values should be passed as '[UNAVAILABLE]' — never leave gaps.
"""

# ---------------------------------------------------------------------------
# Shared system prompt
# ---------------------------------------------------------------------------

ANALYST_SYSTEM = """You are a professional financial analyst assistant. Your role is to provide \
factual, data-driven analysis to help an investor understand a company.

Rules:
- Always cite specific numbers (prices, percentages, ratios)
- Clearly separate facts from your interpretation
- If data shows '[UNAVAILABLE]', acknowledge the gap — never invent numbers
- Be direct and concise — investors want clarity, not filler
- Use plain English; avoid unnecessary jargon
- Flag risks explicitly, don't bury them
"""

# ---------------------------------------------------------------------------
# Morning briefing — portfolio company (full)
# ---------------------------------------------------------------------------

PORTFOLIO_BRIEFING = ANALYST_SYSTEM + """

You are writing the morning section of a daily financial briefing for one portfolio company.
Keep the response under 600 words. Use the structure below exactly.
"""

PORTFOLIO_BRIEFING_USER = """
=== {ticker} — {name} ({list_type}) ===

== PRICE & MOMENTUM ==
Current Price: {price}
Change Today: {change_pct}%  |  Change This Week: {change_1w_pct}%
52-Week Range: {low_52w} – {high_52w}
RSI-14: {rsi}  |  50-day SMA: {sma50}  |  200-day SMA: {sma200}
MACD Signal: {macd_signal}

== FUNDAMENTALS ==
P/E (TTM): {pe}  |  Forward P/E: {fwd_pe}  |  EPS: {eps}
Revenue Growth (YoY): {rev_growth}%  |  5yr Revenue CAGR: {rev_cagr_5y}%
Gross Margin: {gross_margin}%  |  Net Margin: {net_margin}%
Debt/Equity: {debt_equity}  |  ROE (avg 5yr): {roe_5y}%
ROIC: {roic}%

== EARNINGS ==
Next Earnings: {next_earnings_date}  |  EPS Estimate: {next_eps_est}
Last Quarter: EPS {eps_actual} vs Est {eps_estimate} ({eps_surprise}% surprise)

== ANALYST CONSENSUS ==
Strong Buy: {strong_buy}  |  Buy: {buy}  |  Hold: {hold}  |  Sell: {sell}
Price Target — Mean: {target_mean}  |  High: {target_high}  |  Low: {target_low}
Upside to Mean Target: {target_upside}%

== INSIDER ACTIVITY (last 90 days) ==
{insider_summary}

== RECENT NEWS (last 7 days) ==
{news_bullets}

== INVESTMENT THESIS (stored) ==
{thesis_block}

Respond using EXACTLY this format. No extra sections, no prose outside the headers.

PRICE ACTION: [3-5 sentences. What drove price this week? Reference specific technicals (RSI, SMA, MACD) and any news catalysts. If no clear driver, say so and note whether the move looks like sector rotation or broader market pressure.]

FUNDAMENTAL SIGNAL: [3-5 sentences. The most important data point from fundamentals this week — P/E vs historical, margin trend, revenue growth, earnings surprise. Explain what it signals about the business trajectory.]

THESIS CHECK: [INTACT / CHALLENGED / BROKEN] — [3-5 sentences. Does today's news support or threaten the stored thesis? Be explicit about what specifically challenges it, if anything. Call out the exact headline or data point that matters.]

KEY RISKS: [3-5 bullet points. Most important risks to watch this week, each with a brief explanation of the potential impact.]

VERDICT: HOLD / WATCH / ACT — [2-3 sentences. Justification citing specific data points — price vs target, RSI level, upcoming catalyst, or thesis status.]
"""

# ---------------------------------------------------------------------------
# Morning briefing — watchlist company (lighter)
# ---------------------------------------------------------------------------

WATCHLIST_BRIEF_USER = """
=== {ticker} — {name} (WATCHLIST) ===

Price: {price} ({change_pct}% today)  |  52-Week Range: {low_52w} – {high_52w}
P/E: {pe}  |  Analyst Mean Target: {target_mean}  |  Upside: {target_upside}%
RSI: {rsi}  |  Earnings Surprise (last Q): {eps_surprise}%
Sentiment: {sentiment_desc}

Recent News:
{news_bullets}

Entry Rationale: {thesis_rationale}

Respond using EXACTLY this format. No extra sections, no prose outside the headers.

PRICE CHECK: [3-5 sentences. Is the current price more or less attractive than when added? Reference the P/E ratio, analyst upside, 52-week position, and RSI to build your case.]

NEWS IMPACT: [3-5 sentences. Does any headline materially change the investment case? Explain what the news means for the thesis and whether the market reaction looks overdone or justified. If nothing is significant, write "No material news changes" and briefly explain why the headlines don't move the needle.]

KEY RISK: [3-5 sentences. The most important risk to watch this week — explain the mechanism and potential magnitude of impact.]

MONITOR: YES or NO — [2-3 sentences explaining the reasoning, referencing at least one specific metric.]

VERDICT: HOLD / WATCH CLOSELY / CONSIDER ENTRY — [2-3 sentences. Justification citing specific data points — price vs target, RSI level, upcoming catalyst, or entry rationale alignment.]
"""

# ---------------------------------------------------------------------------
# Step 2 — Business understanding (SWOT)
# ---------------------------------------------------------------------------

BUSINESS_UNDERSTANDING_USER = """
Analyze {ticker} ({name}) — Sector: {sector}, Industry: {industry}

== COMPANY DESCRIPTION ==
{description}

== RECENT NEWS HEADLINES (for context) ==
{news_bullets}

== SEC 10-K BUSINESS SECTION EXCERPT ==
{sec_excerpt}

Provide a structured SWOT analysis:

**STRENGTHS** (internal advantages, competitive moat, revenue model durability)
**WEAKNESSES** (internal vulnerabilities, dependencies, cost structure issues)
**OPPORTUNITIES** (market tailwinds, addressable market expansion, strategic options)
**THREATS** (competitive pressure, regulation, macro risks, disruptive forces)
**MOAT ASSESSMENT** (rate the moat: None / Weak / Moderate / Strong — explain in 2 sentences)
**REVENUE TYPE** (Recurring subscription / Contractual / Transactional / Mixed — explain)

Keep each section to 2-3 bullets. Be specific to this company, not generic.
"""

# ---------------------------------------------------------------------------
# Step 3 — Financial analysis
# ---------------------------------------------------------------------------

FINANCIAL_ANALYSIS_USER = """
Financial analysis for {ticker} ({name}):

== GROWTH (CAGR) ==
Revenue CAGR 5yr: {rev_cagr_5y}%  |  10yr: {rev_cagr_10y}%
EPS CAGR 5yr: {eps_cagr_5y}%  |  10yr: {eps_cagr_10y}%
Operating Income CAGR 5yr: {op_cagr_5y}%

== PROFITABILITY ==
Gross Margin: {gross_margin}%  |  Operating Margin: {op_margin}%  |  Net Margin: {net_margin}%
ROE (avg 5yr): {roe_5y}%  |  ROIC: {roic}%  |  ROA: {roa}%
SG&A as % of Revenue: {sga_pct_rev}
R&D as % of Revenue: {rd_pct_rev}

== CASH FLOW QUALITY ==
FCF Trend (Operating CF - CapEx): {fcf_trend}
Cash Conversion Ratio (Op CF / Net Income): {cash_conversion}
(Ratio > 1.0 = earnings backed by real cash; < 0.7 = potential quality concern)

== BALANCE SHEET ==
Debt/Equity: {debt_equity}  |  Current Ratio: {current_ratio}
Net Debt Trend (Total Debt - Cash): {net_debt_trend}
(Negative = net cash position)
Interest Coverage (EBIT / Interest): {interest_coverage}
(Below 3x is a warning sign)
Working Capital Trend: {working_capital}
Shares Outstanding Trend: {shares_trend}
(Growing = dilution risk; Shrinking = buyback compounding)
Goodwill as % of Total Assets: {goodwill_pct}
FCF Yield (TTM): {fcf_yield}%

== SHAREHOLDER RETURNS ==
Annual Buybacks: {buyback_trend}

== FORENSIC FLAGS ==
GAAP vs Adjusted EPS divergence: {gaap_vs_adj}
Insider Activity: {insider_summary}

== PEER COMPARISON ==
{peer_table}

Provide financial analysis covering:
1. Is growth accelerating, steady, or decelerating? What does the CAGR trend suggest?
2. Cash flow quality — does the cash conversion ratio support the reported earnings?
3. Capital allocation — ROIC, buybacks, and whether management creates or destroys value
4. Balance sheet health — net debt trend, interest coverage, and working capital trajectory
5. Any dilution or goodwill concerns hiding in the balance sheet?
6. Any forensic red flags (low cash conversion, large GAAP/adjusted divergence, insider selling)?

Keep under 450 words. Be specific with numbers.
"""

# ---------------------------------------------------------------------------
# Step 4 — Strategy assessment
# ---------------------------------------------------------------------------

STRATEGY_ASSESSMENT_USER = """
Strategy assessment for {ticker} ({name}):

== CAPITAL INVESTMENT ==
Annual CapEx (last 5 years): {capex_history}
CapEx as % of Revenue: {capex_pct_rev}
R&D as % of Revenue: {rd_pct_rev}
(Rising CapEx/R&D = investment mode; Falling = harvesting/mature phase)

== CAPITAL RETURNS ==
Annual Buybacks: {buyback_trend}
(Consistent buybacks while growing = strong conviction; buybacks funded by debt = red flag)

== MANAGEMENT PRIORITIES (from latest earnings call / 10-K MD&A) ==
{strategy_excerpt}

== HISTORICAL ROIC ==
{roic_history}
(Consistent ROIC > 15% = strong capital allocator)

== RECENT STRATEGIC ACTIONS (from news) ==
{strategic_news}

Assess management and strategy:
1. What are the top 2-3 strategic priorities management is executing on right now?
2. Is the CapEx/R&D trend consistent with their stated strategy?
3. Are buybacks being funded from genuine free cash flow, or debt-financed?
4. Does the historical ROIC suggest management creates or destroys shareholder value?
5. What is the single biggest execution risk in their current strategy?

Keep under 300 words.

At the very end of your response, on its own line, output:
GUIDANCE_CREDIBILITY: HIGH | MEDIUM | LOW
(HIGH = stated strategy clearly matches capital allocation decisions; MEDIUM = mixed signals; LOW = stated priorities don't match spending or ROIC history is inconsistent with claimed execution)
"""

# ---------------------------------------------------------------------------
# Step 5 — Valuation
# ---------------------------------------------------------------------------

VALUATION_USER = """
Valuation analysis for {ticker} ({name}):

== CURRENT MULTIPLES ==
P/E (TTM): {pe}  |  Forward P/E: {fwd_pe}  |  P/B: {price_to_book}
EV/EBITDA: {ev_ebitda}  |  FCF Yield: {fcf_yield}%
Price/Sales: {price_to_sales}

== HISTORICAL CONTEXT ==
52-Week Range: {low_52w} – {high_52w}
Current Price vs 52w Average: {vs_52w_avg}%

== ANALYST CONSENSUS ==
Mean Target: {target_mean}  |  High: {target_high}  |  Low: {target_low}
Upside to Mean: {target_upside}%
Recommendation: {recommendation}

== PEER MULTIPLES (for comparison) ==
{peer_valuation_table}

== CAPITAL RETURN TO SHAREHOLDERS ==
Annual Buybacks: {buyback_trend}
FCF Trend: {fcf_trend}

== INSIDER SIGNAL ==
{insider_signal}

Provide valuation assessment:
1. Is this stock trading at a discount, fair value, or premium to its fundamentals?
2. How do current multiples compare to historical averages and peers?
3. What does the FCF yield suggest about the return an investor can expect?
4. Is the analyst consensus price target credible given the fundamentals?
5. VERDICT: Attractive entry / Fair value — wait for dip / Overvalued relative to growth

Keep under 250 words.
"""

# ---------------------------------------------------------------------------
# Step 6 — Thesis check
# ---------------------------------------------------------------------------

THESIS_CHECK_USER = """
Thesis integrity check for {ticker} ({name}):

== STORED INVESTMENT THESIS ==
{thesis_block}

== TODAY'S NEWS ==
{news_bullets}

== MATERIAL CHANGES SINCE THESIS WAS WRITTEN ==
Latest Financials: Revenue growth {rev_growth}% | EPS surprise {eps_surprise}%
Analyst Target Change: {target_upside}% upside remaining
Insider Activity: {insider_summary}

Does the current evidence support or challenge the stored investment thesis?

Respond with:
**THESIS STATUS**: [INTACT / CHALLENGED / BROKEN]
**REASONING** (2-3 sentences): What specifically in today's data supports or threatens the thesis?
**ACTION SIGNAL**: [HOLD / WATCH CLOSELY / RE-EVALUATE]

Be direct. If the thesis has a gap, say so.
"""

# ---------------------------------------------------------------------------
# Opportunity evaluation (Gate 3 LLM check)
# ---------------------------------------------------------------------------

PAPER_BUY_SIZE_USER = """
You are sizing a position for a paper trading portfolio.

== PRIOR ANALYSIS OF {ticker} ({name}) ==
{llm_evaluation}

== QUANTITATIVE SCORE: {score}/15 ==
Signals: {signals}
Current price: {price}
Proposed allocation: ${alloc:.0f}

Decision — choose one:
- FULL  : conviction is high; fundamentals support the signals
- HALF  : real concerns exist but opportunity outweighs the risk (invest 50%)
- SKIP  : risks or counter-narratives outweigh the opportunity

Reply with exactly two lines:
SIZE: FULL | SIZE: HALF | SIZE: SKIP
REASON: one sentence
"""

OPPORTUNITY_EVAL_USER = """
Opportunity evaluation for {ticker} ({name}):

== QUANTITATIVE SCORE: {score}/15 ==
Triggered signals:
{signals_list}

== KEY DATA ==
Price: {price} ({change_pct}% today)
P/E: {pe}  |  RSI: {rsi}  |  52w Position: {vs_52w_avg}%
Analyst Target Upside: {target_upside}%
Last Earnings Surprise: {eps_surprise}%

== RECENT NEWS ==
{news_bullets}

Evaluate this investment opportunity:
1. Do the quantitative signals have a plausible fundamental driver, or is this a value trap?
2. Is there a counter-narrative in the news that the numbers don't capture?
3. What is the most important risk in the next 30 days?
4. VERDICT: Worth Adding to Watchlist / Pass — explain in 1 sentence

Keep under 200 words.
"""

# ---------------------------------------------------------------------------
# Market scanner — LLM-generated universe from today's news
# ---------------------------------------------------------------------------

MARKET_UNIVERSE_USER = """
You are a financial analyst. Based on today's market news, suggest stocks to screen for investment opportunities.

== TODAY'S MARKET NEWS HEADLINES ==
{news_headlines}

== ALREADY TRACKED (exclude all of these) ==
Portfolio: {portfolio_tickers}
Watchlist: {watchlist_tickers}

Suggest exactly {target_count} US-listed stocks to screen today.

Requirements:
- Span at least 4 different sectors (e.g. Tech, Healthcare, Financials, Energy, Consumer, Industrials)
- Large-cap or mid-cap only — no penny stocks or micro-caps
- Prioritise stocks directly mentioned in or affected by the news headlines above
- Do NOT include any ticker already in the portfolio or watchlist lists above
- Return ONLY a comma-separated list of ticker symbols — no explanations, no numbering

Example output: AAPL, NVDA, JPM, XOM, LLY, HD, BA, PFE, COST, AMGN, NEE, CAT, SCHW, MRK, DIS, CVX, TMO, UPS, GS, V
"""

# ---------------------------------------------------------------------------
# Daily market news summary
# ---------------------------------------------------------------------------

MARKET_NEWS_SUMMARY_USER = """
You are writing the opening section of a daily financial briefing. Summarize today's market environment based on the headlines below.

== TODAY'S HEADLINES ==
{news_headlines}

Respond using EXACTLY this format:

MARKET MOOD: [1 sentence. Overall tone — risk-on, risk-off, mixed? Reference one specific driver.]

KEY THEMES: [3-5 bullet points. The most important stories moving markets today. Each bullet: what happened and why it matters for investors.]

SECTORS TO WATCH: [2-3 sentences. Which sectors or asset classes are most affected by today's news, and in which direction.]

MACRO SIGNALS: [2-3 sentences. Any notable macro data, Fed signals, geopolitical developments, or commodity moves in the headlines.]
"""

# ---------------------------------------------------------------------------
# Weekly opportunity scan — suggest new tickers
# ---------------------------------------------------------------------------

OPPORTUNITY_SCAN_USER = """
Portfolio theme analysis:

Current portfolio: {portfolio_tickers}
Current watchlist: {watchlist_tickers}

Based on these holdings, suggest 3-5 additional companies that might be worth researching:
- Companies in adjacent sectors or supply chains
- Peers that may be relatively undervalued
- Companies that would benefit from the same macro trends driving these holdings
- Do NOT suggest companies already in the portfolio or watchlist

For each suggestion, provide:
- Ticker and company name
- One sentence on why it fits the portfolio themes
- One key risk to be aware of

Format each as: TICKER | Company Name | Rationale | Key Risk
"""
