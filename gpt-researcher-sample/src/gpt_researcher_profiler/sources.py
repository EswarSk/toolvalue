from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol

from .dataset import PAPERS, PaperFixture


SOURCE_ORDER = ("crossref", "openalex", "open_citations", "europe_pmc")


class SourceClient(Protocol):
    async def crossref(self, doi: str) -> dict[str, Any]: ...
    async def openalex(self, doi: str) -> dict[str, Any]: ...
    async def open_citations(self, doi: str) -> dict[str, Any]: ...
    async def europe_pmc(self, doi: str) -> dict[str, Any]: ...


def _record(
    source: str,
    doi: str,
    *,
    title: str | None = None,
    year: int | None = None,
    first_author: str | None = None,
    venue: str | None = None,
    url: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "doi": doi,
        "title": title,
        "year": year,
        "first_author": first_author,
        "venue": venue,
        "url": url,
        "error": error,
    }


def _first(mapping: Mapping[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _year_from_parts(value: Any) -> int | None:
    try:
        return int(value["date-parts"][0][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class PublicSourceClient:
    """Four unauthenticated scholarly APIs used as independent source tools."""

    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ToolValue-GPT-Researcher/0.1 (https://github.com/EswarSk/toolvalue)",
            },
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (OSError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.25)
        assert last_error is not None
        raise last_error

    async def crossref(self, doi: str) -> dict[str, Any]:
        try:
            payload = await asyncio.to_thread(
                self._get_json,
                f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}",
            )
            message = payload.get("message", {}) if isinstance(payload, dict) else {}
            author = _first(message, "author") or {}
            name = " ".join(
                part for part in (author.get("given"), author.get("family")) if part
            ) or None
            return _record(
                "crossref",
                doi,
                title=_first(message, "title") or None,
                year=_year_from_parts(message.get("published")),
                first_author=name,
                venue=_first(message, "container-title") or None,
                url=f"https://doi.org/{doi}",
            )
        except Exception as exc:
            return _record("crossref", doi, error=f"{type(exc).__name__}: {exc}")

    async def openalex(self, doi: str) -> dict[str, Any]:
        try:
            payload = await asyncio.to_thread(
                self._get_json,
                "https://api.openalex.org/works",
                {"filter": f"doi:{doi}", "per-page": 1},
            )
            results = payload.get("results", []) if isinstance(payload, dict) else []
            work = results[0] if results else {}
            authorships = work.get("authorships") or []
            first_author = (
                (authorships[0].get("author") or {}).get("display_name")
                if authorships
                else None
            )
            location = work.get("primary_location") or {}
            venue = (location.get("source") or {}).get("display_name")
            return _record(
                "openalex",
                doi,
                title=work.get("display_name") or work.get("title") or None,
                year=work.get("publication_year"),
                first_author=first_author,
                venue=venue,
                url=work.get("id"),
            )
        except Exception as exc:
            return _record("openalex", doi, error=f"{type(exc).__name__}: {exc}")

    async def open_citations(self, doi: str) -> dict[str, Any]:
        try:
            payload = await asyncio.to_thread(
                self._get_json,
                f"https://api.opencitations.net/meta/v1/metadata/doi:{urllib.parse.quote(doi, safe='/')}",
            )
            work = payload[0] if isinstance(payload, list) and payload else {}
            author = (work.get("author") or "").split(";", 1)[0]
            author = author.split("[", 1)[0].strip()
            if "," in author:
                family, given = (part.strip() for part in author.split(",", 1))
                author = " ".join(part for part in (given, family) if part)
            publication_date = str(work.get("pub_date") or "")
            return _record(
                "open_citations",
                doi,
                title=work.get("title") or None,
                year=int(publication_date[:4]) if publication_date[:4].isdigit() else None,
                first_author=author or None,
                venue=work.get("venue") or None,
                url=f"https://doi.org/{doi}",
            )
        except Exception as exc:
            return _record("open_citations", doi, error=f"{type(exc).__name__}: {exc}")

    async def europe_pmc(self, doi: str) -> dict[str, Any]:
        try:
            payload = await asyncio.to_thread(
                self._get_json,
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                {"query": f"DOI:{doi}", "format": "json", "pageSize": 1},
            )
            results = ((payload.get("resultList") or {}).get("result") or [])
            work = results[0] if results else {}
            author_string = work.get("authorString") or ""
            first_author = author_string.split(",", 1)[0].strip() or None
            return _record(
                "europe_pmc",
                doi,
                title=(work.get("title") or "").rstrip(".") or None,
                year=int(work["pubYear"]) if work.get("pubYear") else None,
                first_author=first_author,
                venue=work.get("journalTitle"),
                url=(f"https://europepmc.org/article/{work.get('source')}/{work.get('id')}" if work else None),
            )
        except Exception as exc:
            return _record("europe_pmc", doi, error=f"{type(exc).__name__}: {exc}")


class FixtureSourceClient:
    """Stable facsimile of observed public records for zero-cost regression tests."""

    def __init__(self) -> None:
        self._papers = {paper.doi: paper for paper in PAPERS}

    def _fixture(self, source: str, doi: str) -> dict[str, Any]:
        paper = self._papers[doi]
        if source == "europe_pmc" and doi in {
            "10.18653/v1/N19-1423",
            "10.1109/CVPR.2016.90",
        }:
            return _record(source, doi)
        title: str | None = paper.title
        year: int | None = paper.year
        author: str | None = paper.first_author
        venue: str | None = paper.venue
        if doi == "10.18653/v1/N19-1423" and source in {"crossref", "openalex"}:
            title = None
        if source == "europe_pmc":
            parts = paper.first_author.split()
            author = f"{parts[-1]} {''.join(part[0] for part in parts[:-1])}"
        return _record(source, doi, title=title, year=year, first_author=author, venue=venue)

    async def crossref(self, doi: str) -> dict[str, Any]:
        return self._fixture("crossref", doi)

    async def openalex(self, doi: str) -> dict[str, Any]:
        return self._fixture("openalex", doi)

    async def open_citations(self, doi: str) -> dict[str, Any]:
        return self._fixture("open_citations", doi)

    async def europe_pmc(self, doi: str) -> dict[str, Any]:
        return self._fixture("europe_pmc", doi)
