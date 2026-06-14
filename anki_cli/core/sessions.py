from __future__ import annotations

import datetime
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    d = base / "anki-cli"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sessions_path() -> Path:
    return _data_dir() / "sessions.json"


@dataclass(frozen=True, slots=True)
class SessionRecord:
    deck: str
    label: str
    card_count: int
    duration_seconds: int
    timestamp_epoch: float

    @property
    def duration_minutes(self) -> int:
        return max(1, self.duration_seconds // 60)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionRecord:
        return cls(
            deck=str(data.get("deck", "")),
            label=str(data.get("label", "")),
            card_count=int(data.get("card_count", 0)),
            duration_seconds=int(data.get("duration_seconds", 0)),
            timestamp_epoch=float(data.get("timestamp_epoch", 0.0)),
        )


class SessionStore:
    def __init__(self, path: Path | None = None, *, max_items: int = 10) -> None:
        self._path = path or _sessions_path()
        self._max_items = max_items

    def save(self, record: SessionRecord) -> None:
        items = self._load_raw()
        items.insert(0, record.to_dict())
        items = items[: self._max_items]
        self._write_raw(items)

    def recent(self, limit: int = 5) -> list[SessionRecord]:
        items = self._load_raw()
        result: list[SessionRecord] = []
        for raw in items[:limit]:
            try:
                result.append(SessionRecord.from_dict(raw))
            except (TypeError, ValueError, KeyError):
                continue
        return result

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _write_raw(self, items: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(items, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError:
            tmp.unlink(missing_ok=True)


def make_session_record(deck: str, card_count: int, start_epoch: float) -> SessionRecord:
    elapsed = time.time() - start_epoch
    label = f"{deck} review" if deck else "full review"
    return SessionRecord(
        deck=deck or "everything",
        label=label,
        card_count=card_count,
        duration_seconds=int(elapsed),
        timestamp_epoch=time.time(),
    )


def compute_streak(backend: Any) -> int:
    if not hasattr(backend, "name") or backend.name != "direct":
        return 0
    if not hasattr(backend, "_store"):
        return 0

    store = backend._store
    conn_method = getattr(store, "_connect", None)
    if conn_method is None:
        return 0

    try:
        with conn_method() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT date(id / 1000, 'unixepoch', 'localtime') AS d
                FROM revlog
                ORDER BY d DESC
                """,
            ).fetchall()
    except Exception:
        return 0

    if not rows:
        return 0

    today = datetime.date.today()
    streak = 0

    for row in rows:
        try:
            review_date = datetime.date.fromisoformat(row["d"])
        except (ValueError, TypeError, KeyError):
            continue

        expected = today - datetime.timedelta(days=streak)
        if review_date == expected:
            streak += 1
        elif review_date < expected:
            break

    return streak