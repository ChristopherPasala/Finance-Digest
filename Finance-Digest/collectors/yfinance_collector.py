"""Yahoo Finance data collector via yfinance."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from collectors.base import BaseCollector
from utils import cache, rate_limiter

log = logging.getLogger(__name__)
_limiter = rate_limiter.LIMITERS["yfinance"]


def _safe_float(val: Any, default: Any = None) -> float | None:
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return default


def _safe_pct(new: float | None, old: float | None) -> float | None:
    if new is not None and old and old != 0:
        return round((new - old) / abs(old) * 100, 2)
    return None


class YFinanceCollector(BaseCollector):
    name = "yfinance"

    async def _ticker(self, ticker: str) -> yf.Ticker:
        await _limiter.acquire()
        loop = __import__("asyncio").get_event_loop()
        return await loop.run_in_executor(None, yf.Ticker, ticker)

    async def get_quote(self, ticker: str) -> dict:
        cached = await cache.get(ticker, "quote")
        if cached:
            return cached

        def _fetch():
            t = yf.Ticker(ticker)
            info = t.fast_info
            hist = t.history(period="5d")
            price = _safe_float(getattr(info, "last_price", None))
            prev_close = _safe_float(getattr(info, "previous_close", None))
            change_pct = _safe_pct(price, prev_close)
            week_ago = hist["Close"].iloc[0] if len(hist) >= 5 else None
            change_1w = _safe_pct(price, _safe_float(week_ago))
            return {
                "price": price,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "change_1w_pct": change_1w,
                "volume": _safe_float(getattr(info, "three_month_average_volume", None)),
                "market_cap": _safe_float(getattr(info, "market_cap", None)),
                "52w_high": _safe_float(getattr(info, "year_high", None)),
                "52w_low": _safe_float(getattr(info, "year_low", None)),
            }

        await _limiter.acquire()
        result = await self._fetch_with_retry(_fetch)
        if result:
            await cache.set(ticker, "quote", result)
        return result or {}

    async def get_info(self, ticker: str) -> dict:
        cached = await cache.get(ticker, "fundamentals")
        if cached:
            return cached

        def _fetch():
            info = yf.Ticker(ticker).info
            return {
                "name": info.get("shortName") or info.get("longName", ticker),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "description": (info.get("longBusinessSummary", "") or "")[:500],
                "pe_ratio": _safe_float(info.get("trailingPE")),
                "forward_pe": _safe_float(info.get("forwardPE")),
                "eps": _safe_float(info.get("trailingEps")),
                "revenue_growth": _safe_float(info.get("revenueGrowth")),
                "earnings_growth": _safe_float(info.get("earningsGrowth")),
                "gross_margins": _safe_float(info.get("grossMargins")),
                "operating_margins": _safe_float(info.get("operatingMargins")),
                "profit_margins": _safe_float(info.get("profitMargins")),
                "debt_to_equity": _safe_float(info.get("debtToEquity")),
                "current_ratio": _safe_float(info.get("currentRatio")),
                "return_on_equity": _safe_float(info.get("returnOnEquity")),
                "return_on_assets": _safe_float(info.get("returnOnAssets")),
                "beta": _safe_float(info.get("beta")),
                "dividend_yield": _safe_float(info.get("dividendYield")),
                "price_to_book": _safe_float(info.get("priceToBook")),
                "ev_to_ebitda": _safe_float(info.get("enterpriseToEbitda")),
                "free_cashflow": _safe_float(info.get("freeCashflow")),
                "total_revenue": _safe_float(info.get("totalRevenue")),
                "analyst_target": _safe_float(info.get("targetMeanPrice")),
                "analyst_target_high": _safe_float(info.get("targetHighPrice")),
                "analyst_target_low": _safe_float(info.get("targetLowPrice")),
                "recommendation": info.get("recommendationKey"),
                "number_of_analysts": info.get("numberOfAnalystOpinions"),
            }

        await _limiter.acquire()
        result = await self._fetch_with_retry(_fetch)
        if result:
            await cache.set(ticker, "fundamentals", result)
        return result or {}

    async def get_financials_history(self, ticker: str) -> dict:
        """Income statement + balance sheet history for CAGR and common-size analysis."""
        cached = await cache.get(ticker, "financials")
        if cached:
            return cached

        def _fetch():
            t = yf.Ticker(ticker)
            income = t.financials        # annual, columns = dates
            quarterly = t.quarterly_financials
            balance = t.balance_sheet
            cashflow = t.cashflow

            def df_to_dict(df: pd.DataFrame) -> dict:
                if df is None or df.empty:
                    return {}
                result = {}
                for col in df.columns:
                    col_str = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                    result[col_str] = {
                        row: _safe_float(df.loc[row, col])
                        for row in df.index
                        if not pd.isna(df.loc[row, col])
                    }
                return result

            return {
                "annual_income": df_to_dict(income),
                "quarterly_income": df_to_dict(quarterly),
                "annual_balance": df_to_dict(balance),
                "annual_cashflow": df_to_dict(cashflow),
            }

        await _limiter.acquire()
        result = await self._fetch_with_retry(_fetch)
        if result:
            await cache.set(ticker, "financials", result)
        return result or {}

    async def get_technicals(self, ticker: str) -> dict:
        cached = await cache.get(ticker, "technicals")
        if cached:
            return cached

        def _fetch():
            t = yf.Ticker(ticker)
            hist = t.history(period="1y")
            if hist.empty:
                return {}
            close = hist["Close"]

            # RSI-14
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi = 100 - 100 / (1 + rs)
            rsi_val = _safe_float(rsi.iloc[-1])

            # Moving averages
            sma50 = _safe_float(close.rolling(50).mean().iloc[-1])
            sma200 = _safe_float(close.rolling(200).mean().iloc[-1])

            # MACD
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_val = _safe_float(macd_line.iloc[-1])
            signal_val = _safe_float(signal_line.iloc[-1])
            macd_bullish = macd_val is not None and signal_val is not None and macd_val > signal_val

            return {
                "rsi_14": rsi_val,
                "sma_50": sma50,
                "sma_200": sma200,
                "macd": macd_val,
                "macd_signal": signal_val,
                "macd_bullish": macd_bullish,
                "current_price": _safe_float(close.iloc[-1]),
            }

        await _limiter.acquire()
        result = await self._fetch_with_retry(_fetch)
        if result:
            await cache.set(ticker, "technicals", result)
        return result or {}

    async def get_news(self, ticker: str, days_back: int = 7) -> list[dict]:
        cached = await cache.get(ticker, "news")
        if cached is not None:
            return cached

        def _fetch():
            t = yf.Ticker(ticker)
            raw_news = t.news or []
            cutoff = datetime.utcnow() - timedelta(days=days_back)
            articles = []
            for item in raw_news[:20]:
                ts = item.get("providerPublishTime", 0)
                pub_dt = datetime.utcfromtimestamp(ts) if ts else None
                if pub_dt and pub_dt < cutoff:
                    continue
                articles.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "source": item.get("publisher", ""),
                    "published_at": pub_dt.strftime("%Y-%m-%d") if pub_dt else "",
                })
            return articles

        await _limiter.acquire()
        result = await self._fetch_with_retry(_fetch)
        if result is not None:
            await cache.set(ticker, "news", result)
        return result or []

    async def compute_cagr(self, ticker: str) -> dict:
        """Compute 5-year and 10-year CAGR for revenue, operating income, EPS."""
        cached = await cache.get(ticker, "cagr_metrics")
        if cached:
            return cached

        financials = await self.get_financials_history(ticker)
        annual = financials.get("annual_income", {})
        if not annual:
            return {}

        dates = sorted(annual.keys(), reverse=True)  # newest first

        def _cagr(values: list[float | None], years: int) -> float | None:
            clean = [v for v in values if v is not None and v > 0]
            if len(clean) < 2:
                return None
            n = min(years, len(clean) - 1)
            if n <= 0:
                return None
            latest, oldest = clean[0], clean[n]
            if oldest == 0:
                return None
            return round((latest / oldest) ** (1 / n) - 1, 4)

        def _extract_row(row_name: str) -> list[float | None]:
            results = []
            for date in dates[:11]:  # up to 10 years + current
                val = annual.get(date, {}).get(row_name)
                results.append(_safe_float(val))
            return results

        # Try common row names
        revenue_keys = ["Total Revenue", "Revenue"]
        op_income_keys = ["Operating Income", "EBIT"]
        eps_keys = ["Basic EPS", "Diluted EPS"]

        def _get_series(keys: list[str]) -> list[float | None]:
            for k in keys:
                series = _extract_row(k)
                if any(v is not None for v in series):
                    return series
            return [None] * 11

        rev = _get_series(revenue_keys)
        op = _get_series(op_income_keys)
        eps = _get_series(eps_keys)

        result = {
            "revenue_cagr_5y": _cagr(rev, 5),
            "revenue_cagr_10y": _cagr(rev, 10),
            "operating_income_cagr_5y": _cagr(op, 5),
            "eps_cagr_5y": _cagr(eps, 5),
            "eps_cagr_10y": _cagr(eps, 10),
        }
        await cache.set(ticker, "cagr_metrics", result, ttl_seconds=24 * 3600)
        return result

    async def compute_capex(self, ticker: str) -> dict:
        """Extract CapEx history and CapEx-as-%-of-revenue from annual cashflow statement."""
        cached = await cache.get(ticker, "capex_metrics")
        if cached:
            return cached

        financials = await self.get_financials_history(ticker)
        annual_cashflow = financials.get("annual_cashflow", {})
        annual_income = financials.get("annual_income", {})
        if not annual_cashflow:
            return {}

        dates = sorted(annual_cashflow.keys(), reverse=True)[:5]
        capex_keys = ["Capital Expenditure", "Capital Expenditures",
                      "Purchase Of Plant And Equipment", "Purchase of Property Plant And Equipment"]

        history = {}
        pct_rev = {}
        for date in dates:
            cf_year = annual_cashflow.get(date, {})
            capex_raw = None
            for k in capex_keys:
                v = _safe_float(cf_year.get(k))
                if v is not None:
                    capex_raw = v
                    break
            if capex_raw is None:
                continue
            capex_abs = abs(capex_raw)
            history[date[:4]] = capex_abs

            rev = _safe_float((annual_income.get(date) or {}).get("Total Revenue")
                              or (annual_income.get(date) or {}).get("Revenue"))
            if rev and rev > 0:
                pct_rev[date[:4]] = round(capex_abs / rev * 100, 2)

        result = {"history": history, "pct_rev": pct_rev}
        if history:
            await cache.set(ticker, "capex_metrics", result, ttl_seconds=24 * 3600)
        return result

    async def compute_financial_health(self, ticker: str) -> dict:
        """
        Extract multi-year financial health metrics from already-fetched statements.
        Covers: FCF trend, cash conversion, net debt, interest coverage,
        shares outstanding, buybacks, R&D%, SG&A%, goodwill%, working capital.
        """
        cached = await cache.get(ticker, "financial_health")
        if cached:
            return cached

        financials = await self.get_financials_history(ticker)
        annual_cf  = financials.get("annual_cashflow", {})
        annual_bs  = financials.get("annual_balance", {})
        annual_inc = financials.get("annual_income", {})

        if not annual_cf and not annual_bs:
            return {}

        def _get(d: dict, date: str, *keys) -> float | None:
            row = d.get(date, {})
            for k in keys:
                v = _safe_float(row.get(k))
                if v is not None:
                    return v
            return None

        _CF_DATES  = sorted(annual_cf.keys(),  reverse=True)[:5]
        _BS_DATES  = sorted(annual_bs.keys(),  reverse=True)[:5]
        _INC_DATES = sorted(annual_inc.keys(), reverse=True)[:5]

        # ── Cash flow metrics ────────────────────────────────────────────────
        fcf_trend        = {}
        cash_conversion  = {}   # Operating CF / Net Income
        buyback_trend    = {}

        for date in _CF_DATES:
            yr = date[:4]
            op_cf  = _get(annual_cf, date,
                          "Operating Cash Flow",
                          "Cash Flow From Continuing Operating Activities",
                          "Total Cash From Operating Activities")
            capex  = _get(annual_cf, date,
                          "Capital Expenditure", "Capital Expenditures",
                          "Purchase Of Plant And Equipment",
                          "Purchase of Property Plant And Equipment")
            buyback = _get(annual_cf, date,
                           "Repurchase Of Capital Stock",
                           "Common Stock Repurchased",
                           "Repurchase of Common Stock")
            net_inc = _get(annual_inc, date,
                           "Net Income", "Net Income Common Stockholders")

            if op_cf is not None and capex is not None:
                fcf_trend[yr] = op_cf - abs(capex)

            if op_cf is not None and net_inc and net_inc != 0:
                cash_conversion[yr] = round(op_cf / net_inc, 2)

            if buyback is not None:
                buyback_trend[yr] = abs(buyback)

        # ── Balance sheet metrics ────────────────────────────────────────────
        net_debt_trend       = {}
        shares_trend         = {}
        goodwill_pct_assets  = {}
        working_capital      = {}

        for date in _BS_DATES:
            yr = date[:4]
            total_debt   = _get(annual_bs, date, "Total Debt",
                                "Long Term Debt And Capital Lease Obligation")
            cash         = _get(annual_bs, date,
                                "Cash And Cash Equivalents",
                                "Cash Cash Equivalents And Short Term Investments")
            shares       = _get(annual_bs, date,
                                "Ordinary Shares Number", "Share Issued")
            goodwill     = _get(annual_bs, date, "Goodwill")
            total_assets = _get(annual_bs, date, "Total Assets")
            curr_assets  = _get(annual_bs, date, "Current Assets")
            curr_liab    = _get(annual_bs, date, "Current Liabilities")

            if total_debt is not None and cash is not None:
                net_debt_trend[yr] = total_debt - cash   # negative = net cash

            if shares is not None:
                shares_trend[yr] = shares

            if goodwill and total_assets and total_assets > 0:
                goodwill_pct_assets[yr] = round(goodwill / total_assets * 100, 1)

            if curr_assets is not None and curr_liab is not None:
                working_capital[yr] = curr_assets - curr_liab

        # ── Income statement ratios ──────────────────────────────────────────
        interest_coverage = {}
        rd_pct_rev        = {}
        sga_pct_rev       = {}

        for date in _INC_DATES:
            yr    = date[:4]
            rev   = _get(annual_inc, date, "Total Revenue", "Revenue")
            ebit  = _get(annual_inc, date, "EBIT", "Operating Income")
            intex = _get(annual_inc, date,
                         "Interest Expense", "Interest Expense Non Operating")
            rd    = _get(annual_inc, date, "Research And Development")
            sga   = _get(annual_inc, date,
                         "Selling General And Administrative",
                         "Selling General And Administration")

            if ebit is not None and intex and intex != 0:
                interest_coverage[yr] = round(ebit / abs(intex), 1)

            if rev and rev > 0:
                if rd is not None:
                    rd_pct_rev[yr]  = round(abs(rd)  / rev * 100, 1)
                if sga is not None:
                    sga_pct_rev[yr] = round(abs(sga) / rev * 100, 1)

        result = {
            "fcf_trend":           fcf_trend,
            "cash_conversion":     cash_conversion,
            "buyback_trend":       buyback_trend,
            "net_debt_trend":      net_debt_trend,
            "shares_trend":        shares_trend,
            "goodwill_pct_assets": goodwill_pct_assets,
            "working_capital":     working_capital,
            "interest_coverage":   interest_coverage,
            "rd_pct_rev":          rd_pct_rev,
            "sga_pct_rev":         sga_pct_rev,
        }
        await cache.set(ticker, "financial_health", result, ttl_seconds=24 * 3600)
        return result

    async def compute_returns(self, ticker: str) -> dict:
        """Compute ROE approximations and Piotroski F-Score inputs from historical financials."""
        cached = await cache.get(ticker, "return_metrics")
        if cached:
            return cached

        financials = await self.get_financials_history(ticker)
        annual_income = financials.get("annual_income", {})
        annual_balance = financials.get("annual_balance", {})
        annual_cashflow = financials.get("annual_cashflow", {})
        if not annual_income or not annual_balance:
            return {}

        dates = sorted(annual_income.keys(), reverse=True)[:5]
        roe_series = []
        for date in dates:
            net_income = (_safe_float(annual_income.get(date, {}).get("Net Income"))
                          or _safe_float(annual_income.get(date, {}).get("Net Income Common Stockholders")))
            equity = (_safe_float(annual_balance.get(date, {}).get("Stockholders Equity"))
                      or _safe_float(annual_balance.get(date, {}).get("Common Stock Equity")))
            if net_income and equity and equity != 0:
                roe_series.append(round(net_income / equity, 4))

        # ── Piotroski F-Score inputs (last 3 years) ──────────────────────────
        dates_3y = sorted(annual_income.keys(), reverse=True)[:3]
        roa_history: dict[str, float] = {}
        gross_margin_history: dict[str, float] = {}
        asset_turnover_history: dict[str, float] = {}
        ocf_history: dict[str, float] = {}
        current_ratio_history: dict[str, float] = {}

        for date in dates_3y:
            yr = date[:4]
            inc = annual_income.get(date, {})
            bs  = annual_balance.get(date, {})
            # Use income date as primary key; cashflow dates may differ by a day
            cf  = annual_cashflow.get(date, {})

            net_income   = (_safe_float(inc.get("Net Income"))
                            or _safe_float(inc.get("Net Income Common Stockholders")))
            total_assets = _safe_float(bs.get("Total Assets"))
            revenue      = (_safe_float(inc.get("Total Revenue"))
                            or _safe_float(inc.get("Revenue")))
            gross_profit = (_safe_float(inc.get("Gross Profit"))
                            or _safe_float(inc.get("Gross Income")))
            op_cf        = (_safe_float(cf.get("Operating Cash Flow"))
                            or _safe_float(cf.get("Cash Flow From Continuing Operating Activities"))
                            or _safe_float(cf.get("Total Cash From Operating Activities")))
            curr_assets  = _safe_float(bs.get("Current Assets"))
            curr_liab    = _safe_float(bs.get("Current Liabilities"))

            if net_income is not None and total_assets and total_assets != 0:
                roa_history[yr] = round(net_income / total_assets, 4)

            if gross_profit is not None and revenue and revenue != 0:
                gross_margin_history[yr] = round(gross_profit / revenue, 4)

            if revenue is not None and total_assets and total_assets != 0:
                asset_turnover_history[yr] = round(revenue / total_assets, 4)

            if op_cf is not None:
                ocf_history[yr] = op_cf

            if curr_assets is not None and curr_liab is not None and curr_liab != 0:
                current_ratio_history[yr] = round(curr_assets / curr_liab, 4)

        result = {
            "roe_history":             roe_series,
            "roe_avg_5y":              round(sum(roe_series) / len(roe_series), 4) if roe_series else None,
            "roa_history":             roa_history,
            "gross_margin_history":    gross_margin_history,
            "asset_turnover_history":  asset_turnover_history,
            "ocf_history":             ocf_history,
            "current_ratio_history":   current_ratio_history,
        }
        await cache.set(ticker, "return_metrics", result, ttl_seconds=24 * 3600)
        return result


yfinance_collector = YFinanceCollector()
