"""SEC EDGAR collector — 10-K / 10-Q filings via the public EDGAR REST API."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import requests

from collectors.base import BaseCollector
from utils import cache, rate_limiter
from utils.config import config

log = logging.getLogger(__name__)
_limiter = rate_limiter.LIMITERS["sec_edgar"]

EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
EDGAR_TICKERS = "https://www.sec.gov/files/company_tickers.json"

# Local cache file for the ticker→CIK map (large download, refresh weekly)
_CIK_MAP_PATH = Path("/tmp/sec_company_tickers.json")
_CIK_MAP_CACHE: dict[str, str] = {}


def _headers() -> dict:
    return {"User-Agent": config.sec_user_agent, "Accept-Encoding": "gzip, deflate"}


class SecEdgarCollector(BaseCollector):
    name = "sec_edgar"

    async def _load_cik_map(self) -> dict[str, str]:
        global _CIK_MAP_CACHE
        if _CIK_MAP_CACHE:
            return _CIK_MAP_CACHE

        # Try local file first
        if _CIK_MAP_PATH.exists():
            age = time.time() - _CIK_MAP_PATH.stat().st_mtime
            if age < 7 * 86400:  # less than 7 days old
                try:
                    raw = json.loads(_CIK_MAP_PATH.read_text())
                    _CIK_MAP_CACHE = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
                    return _CIK_MAP_CACHE
                except Exception:
                    pass

        # Download fresh
        await _limiter.acquire()

        def _download():
            resp = requests.get(EDGAR_TICKERS, headers=_headers(), timeout=30)
            resp.raise_for_status()
            return resp.json()

        data = await self._fetch_with_retry(_download)
        if data:
            _CIK_MAP_PATH.write_text(json.dumps(data))
            _CIK_MAP_CACHE = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}

        return _CIK_MAP_CACHE

    async def get_cik(self, ticker: str) -> str | None:
        cik_map = await self._load_cik_map()
        return cik_map.get(ticker.upper())

    async def get_recent_filings(self, ticker: str, form_types: list[str] | None = None,
                                  limit: int = 4) -> list[dict]:
        if form_types is None:
            form_types = ["10-K", "10-Q"]

        cached = await cache.get(ticker, f"sec_filings_{'_'.join(form_types)}")
        if cached:
            return cached

        cik = await self.get_cik(ticker)
        if not cik:
            log.warning("SEC EDGAR: No CIK found for %s", ticker)
            return []

        await _limiter.acquire()

        def _fetch():
            resp = requests.get(EDGAR_SUBMISSIONS.format(cik=cik), headers=_headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            filings = data.get("filings", {}).get("recent", {})
            forms = filings.get("form", [])
            dates = filings.get("filingDate", [])
            accessions = filings.get("accessionNumber", [])
            result = []
            for form, date, acc in zip(forms, dates, accessions):
                if form in form_types:
                    result.append({
                        "form_type": form,
                        "filing_date": date,
                        "accession_number": acc.replace("-", ""),
                        "cik": cik,
                    })
                    if len(result) >= limit:
                        break
            return result

        result = await self._fetch_with_retry(_fetch)
        if result:
            await cache.set(ticker, f"sec_filings_{'_'.join(form_types)}", result,
                            ttl_seconds=7 * 24 * 3600)
        return result or []

    async def get_mda_excerpt(self, ticker: str, max_chars: int = 3000) -> tuple[str | None, str | None]:
        """Fetch the MD&A section from the most recent 10-K or 10-Q."""
        cached_key = "sec_mda_excerpt"
        cached = await cache.get(ticker, cached_key)
        if cached:
            return cached.get("text"), cached.get("form_type")

        filings = await self.get_recent_filings(ticker, form_types=["10-K", "10-Q"], limit=1)
        if not filings:
            return None, None

        filing = filings[0]
        cik = filing["cik"]
        acc = filing["accession_number"]
        form_type = filing["form_type"]

        await _limiter.acquire()

        def _fetch_index():
            # Get filing index to find the primary document
            index_url = f"https://www.sec.gov/Archives/edgar/full-index/{cik[:4]}/{cik[4:]}/{acc[:4]}/{acc[4:]}/{acc}-index.json"
            # Use the simpler accession-based URL
            url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}&dateb=&owner=include&count=1&search_text="
            # Directly fetch the index page
            idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{acc}-index.htm"
            resp = requests.get(
                f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&forms={form_type}",
                headers=_headers(),
                timeout=20,
            )
            return resp

        await _limiter.acquire()

        def _fetch_document():
            # Directly construct filing index URL
            acc_dashed = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"
            idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{acc_dashed}-index.json"
            resp = requests.get(idx_url, headers=_headers(), timeout=30)
            if resp.status_code != 200:
                # Fallback: use EDGAR viewer
                return None
            idx = resp.json()
            docs = idx.get("directory", {}).get("item", [])
            # Find the primary 10-K/10-Q document (HTM or TXT)
            primary = None
            for doc in docs:
                name = doc.get("name", "").lower()
                if name.endswith(".htm") and not name.startswith("r") and primary is None:
                    primary = doc.get("name")
            if not primary:
                return None

            doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{primary}"
            doc_resp = requests.get(doc_url, headers=_headers(), timeout=60)
            doc_resp.raise_for_status()
            return doc_resp.text

        html_text = await self._fetch_with_retry(_fetch_document)
        if not html_text:
            return None, form_type

        # Extract MD&A section via regex
        text = re.sub(r"<[^>]+>", " ", html_text)
        text = re.sub(r"\s+", " ", text).strip()

        mda_pattern = re.compile(
            r"(?:Management.{0,20}Discussion|MD&A|Management.{0,5}Analysis).{0,50}?(?=\n|\.)",
            re.IGNORECASE,
        )
        match = mda_pattern.search(text)
        excerpt = None
        if match:
            start = match.start()
            excerpt = text[start:start + max_chars]
        else:
            # Fallback: take a middle slice of the document
            mid = len(text) // 3
            excerpt = text[mid:mid + max_chars]

        if excerpt:
            await cache.set(ticker, cached_key, {"text": excerpt, "form_type": form_type},
                            ttl_seconds=7 * 24 * 3600)
        return excerpt, form_type


sec_edgar_collector = SecEdgarCollector()
