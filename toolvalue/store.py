from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Protocol

from .types import CaseProfile, RunRecord


class Store(Protocol):
    def save_run(self, run: RunRecord) -> None: ...
    def save_profile(self, profile: CaseProfile) -> None: ...
    def profile_payloads(self, task: str) -> list[dict]: ...


class InMemoryStore:
    def __init__(self) -> None:
        self.runs: list[RunRecord] = []
        self.profiles: list[CaseProfile] = []

    def save_run(self, run: RunRecord) -> None:
        self.runs.append(run)

    def save_profile(self, profile: CaseProfile) -> None:
        self.profiles.append(profile)

    def profile_payloads(self, task: str) -> list[dict]:
        return [profile.to_dict(include_content=False) for profile in self.profiles if profile.task == task]


class SQLiteStore:
    """Local metadata store. Raw content is opt-in through ``capture_content``."""

    def __init__(self, path: str | Path = ".toolvalue/profiles.db", *, capture_content: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.capture_content = capture_content
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                task TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute("CREATE INDEX IF NOT EXISTS artifacts_task_kind ON artifacts(task, kind)")
        self._connection.commit()

    def _save(self, identifier: str, kind: str, task: str, payload: dict) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO artifacts(id, kind, task, payload_json) VALUES (?, ?, ?, ?)",
                (identifier, kind, task, json.dumps(payload, separators=(",", ":"))),
            )
            self._connection.commit()

    def save_run(self, run: RunRecord) -> None:
        self._save(run.id, "run", run.task, run.to_dict(include_content=self.capture_content))

    def save_profile(self, profile: CaseProfile) -> None:
        self._save(profile.id, "profile", profile.task, profile.to_dict(include_content=self.capture_content))

    def profile_payloads(self, task: str) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM artifacts WHERE task = ? AND kind = 'profile' ORDER BY created_at",
                (task,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
