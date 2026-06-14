from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from anki_cli import __version__
from anki_cli.backends.detect import DetectionError, detect_backend
from anki_cli.backends.factory import BackendFactoryError, create_backend_from_context
from anki_cli.config_runtime import ConfigError, resolve_runtime_config
from anki_cli.core.sessions import SessionStore, compute_streak

type JsonScalar  = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

class RPCRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class RPCMethodError(Exception):
    code: int
    message: str
    data: dict[str, JsonValue] | None = None

@dataclass(slots=True)
class UISession:
    ctx_obj: dict[str, Any]
    backend: Any
    deck_context: str | None = None
    session_store: SessionStore = field(default_factory=SessionStore)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> UISession:
        runtime = resolve_runtime_config(
            cli_backend=args.backend,
            cli_backend_set=args.backend != "auto",
            cli_output_format=args.format,
            cli_output_set=args.format != "table",
            cli_no_color=args.no_color,
            cli_no_color_set=args.no_color,
            cli_collection_path=args.col,
            cli_collection_set=args.col is not None,
        )

        detection = detect_backend(
            forced_backend=runtime.backend,
            col_override=runtime.collection_override,
            ankiconnect_url=runtime.app.backend.ankiconnect_url,
        )

        ctx_obj: dict[str, Any] = {
            "format": runtime.output_format,
            "no_color": runtime.no_color,
            "requested_backend": runtime.backend,
            "backend": detection.backend,
            "backend_reason": detection.reason,
            "collection_path": detection.collection_path,
            "collection_override": runtime.collection_override,
            "config_path": runtime.config_path,
            "app_config": runtime.app,
        }

        backend = create_backend_from_context(ctx_obj)
        return cls(ctx_obj=ctx_obj, backend=backend)

    def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if callable(close):
            close()

    def handle(self, request: RPCRequest) -> JsonValue:
        method = request.method

        if method == "system.ping":
            return {
                "version": __version__,
                "protocol": "line-jsonrpc",
                "backend": str(self.ctx_obj.get("backend", "unknown"))
            }

        if method == "home.state":
            return self.home_state()
        
        if method == "app.set_deck_context":
            return self.set_deck_context(request.params)
        
        if method == "app.run_command":
            return self.run_command(request.params)
        
        raise RPCMethodError(
            code=32601,
            message=f"unknown method: {method}"
        )

    def home_state(self) -> dict[str, JsonValue]:
        due = self._coerce_due_counts(self.backend.get_due_counts(deck=self.deck_context))
        decks = self._top_decks(limit=4)
        recent_sessions = self._recent_sessions(limit=5)

        return {
            "version": __version__,
            "backendName": str(self.ctx_obj.get("backend", "unknown")),
            "format": str(self.ctx_obj.get("format", "table")),
            "deckContext": self.deck_context or "everything",
            "due": due,
            "decks": decks,
            "recentSessions": recent_sessions,
            "streak": compute_streak(self.backend),
            "sync": {
                "state": "up_to_date",
                "label": "up to date"
            }
        }

    def set_deck_context(self, params: dict[str, Any]) -> dict[str, JsonValue]:
        raw_deck = params.get("deck")
        if raw_deck is None:
            self.deck_context = None
            return self.home_state()
        if not isinstance(raw_deck, str):
            raise RPCMethodError(
                code=-32602,
                message="'deck' must be a string or null",
            )
        deck = raw_deck.strip()
        self.deck_context = deck or None
        return self.home_state()

    def run_command(self, params: dict[str, Any]) -> dict[str, JsonValue]:
        raw_line = params.get("line")
        if not isinstance(raw_line, str):
            raise RPCMethodError(
                code=-32602,
                message="'line' must be a string",
            )
        normalized = raw_line.lstrip("/").strip()
        lowered = normalized.lower()
        routes: dict[tuple[str, ...], str] = {
            ("study", "review", "rs"): "review",
            ("browse", "cards", "c"): "browse",
            ("add", "na"): "add",
            ("stats",): "stats",
        }
        for aliases, target in routes.items():
            if lowered in aliases:
                return {
                    "statusMessage": f"navigate -> {target}",
                    "navigate": target,
                    "home": None,
                }
        if lowered == "home" or lowered == "refresh":
            return {
                "statusMessage": "home refreshed",
                "navigate": None,
                "home": self.home_state(),
            }
        if lowered == "use":
            self.deck_context = None
            return {
                "statusMessage": "deck context cleared",
                "navigate": None,
                "home": self.home_state(),
            }
        if lowered.startswith("use "):
            deck = normalized[4:].strip()
            self.deck_context = deck or None
            return {
                "statusMessage": f"deck -> {self.deck_context or 'everything'}",
                "navigate": None,
                "home": self.home_state(),
            }
        return {
            "statusMessage": f"unknown command: {raw_line}",
            "navigate": None,
            "home": None,
        }

    def _top_decks(self, limit: int) -> list[dict[str, JsonValue]]:
        raw_decks = self.backend.get_decks()
        items: list[dict[str, JsonValue]] = []
        for raw in raw_decks:
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            due = self._coerce_due_counts(self.backend.get_due_counts(deck=name))
            deck_id = raw.get("id")
            normalized_id = int(deck_id) if isinstance(deck_id, int) else None
            items.append(
                {
                    "id": normalized_id,
                    "name": name,
                    "due": due,
                    "totalDue": due["total"],
                }
            )
        items.sort(key=lambda item: (-int(item["totalDue"]), str(item["name"]).lower()))
        return items[:limit]

    def _recent_sessions(self, limit: int) -> list[dict[str, JsonValue]]:
        out: list[dict[str, JsonValue]] = []
        for record in self.session_store.recent(limit=limit):
            out.append(
                {
                    "deck": record.deck,
                    "label": record.label,
                    "cardCount": record.card_count,
                    "durationSeconds": record.duration_seconds,
                    "timestampEpoch": record.timestamp_epoch,
                }
            )
        return out

    @staticmethod
    def _coerce_due_counts(raw: dict[str, Any]) -> dict[str, int]:
        new_count = int(raw.get("new", 0))
        learn_count = int(raw.get("learn", 0))
        review_count = int(raw.get("review", 0))
        total_count = int(raw.get("total", new_count + learn_count + review_count))
        return {
            "new": new_count,
            "learn": learn_count,
            "review": review_count,
            "total": total_count,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="anki-cli OpenTUI RPC server")
    parser.add_argument(
        "--backend",
        choices=["auto", "ankiconnect", "direct", "standalone"],
        default="auto",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "md", "csv", "plain"],
        default="table",
    )
    parser.add_argument("--col", type=Path, default=None)
    parser.add_argument("--no-color", action="store_true")
    return parser.parse_args(argv)


def emit_success(request_id: int | str | None, result: JsonValue) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def emit_error(
    request_id: int | str | None,
    *,
    code: int,
    message: str,
    data: dict[str, JsonValue] | None = None,
) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
            "data": data or {},
        },
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def serve_forever(session: UISession) -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = RPCRequest.model_validate_json(line)
        except ValidationError as exc:
            emit_error(
                None,
                code=-32600,
                message="Invalid JSON-RPC request",
                data={"details": str(exc)},
            )
            continue
        try:
            result = session.handle(request)
        except RPCMethodError as exc:
            emit_error(
                request.id,
                code=exc.code,
                message=exc.message,
                data=exc.data,
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            emit_error(
                request.id,
                code=-32000,
                message="Internal server error",
                data={"details": str(exc)},
            )
        else:
            emit_success(request.id, result)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        session = UISession.from_args(args)
    except (BackendFactoryError, ConfigError, DetectionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        return serve_forever(session)
    finally:
        session.close()
if __name__ == "__main__":
    raise SystemExit(main())