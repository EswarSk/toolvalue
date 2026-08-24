from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubAPIError(RuntimeError):
    """A live GitHub request failed."""


class GitHubClient:
    """Minimal dependency-free client for public, read-only GitHub endpoints."""

    def __init__(
        self,
        *,
        token: str | None = None,
        timeout: float = 20.0,
        base_url: str = "https://api.github.com",
    ) -> None:
        self._token = token if token is not None else os.getenv("GITHUB_TOKEN")
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        self.network_calls = 0
        self.rate_limit_remaining: int | None = None

    @staticmethod
    def _validate_repository(repository: str) -> str:
        if not _REPOSITORY.fullmatch(repository):
            raise ValueError("repository must use the owner/name format")
        return repository

    def _request(self, path: str, *, accept: str = "application/vnd.github+json") -> bytes:
        headers = {
            "Accept": accept,
            "User-Agent": "toolvalue-live-github-sample/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(f"{self._base_url}{path}", headers=headers)
        self.network_calls += 1
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                remaining = response.headers.get("X-RateLimit-Remaining")
                self.rate_limit_remaining = int(remaining) if remaining is not None else None
                return response.read()
        except urllib.error.HTTPError as exc:
            remaining = exc.headers.get("X-RateLimit-Remaining")
            self.rate_limit_remaining = int(remaining) if remaining is not None else None
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                message = payload.get("message", str(exc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = str(exc)
            hint = " Set GITHUB_TOKEN for a higher rate limit." if exc.code in {403, 429} else ""
            raise GitHubAPIError(f"GitHub API returned {exc.code}: {message}.{hint}") from exc
        except urllib.error.URLError as exc:
            raise GitHubAPIError(f"Could not reach GitHub: {exc.reason}") from exc

    def _json(self, path: str) -> Any:
        try:
            return json.loads(self._request(path).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubAPIError(f"GitHub returned invalid JSON for {path}") from exc

    def repository_metadata(self, repository: str) -> dict[str, Any]:
        repository = self._validate_repository(repository)
        payload = self._json(f"/repos/{repository}")
        license_payload = payload.get("license") or {}
        return {
            "description": payload.get("description"),
            "primary_language": payload.get("language"),
            "homepage": payload.get("homepage"),
            "license": license_payload.get("spdx_id"),
            "archived": bool(payload.get("archived")),
        }

    def readme(self, repository: str) -> str:
        repository = self._validate_repository(repository)
        raw = self._request(
            f"/repos/{repository}/readme",
            accept="application/vnd.github.raw+json",
        )
        return raw.decode("utf-8", errors="replace")[:20_000]

    def topics(self, repository: str) -> list[str]:
        repository = self._validate_repository(repository)
        payload = self._json(f"/repos/{repository}/topics")
        return [str(topic) for topic in payload.get("names", [])]

    def languages(self, repository: str) -> dict[str, int]:
        repository = self._validate_repository(repository)
        payload = self._json(f"/repos/{repository}/languages")
        return {str(language): int(bytes_count) for language, bytes_count in payload.items()}
