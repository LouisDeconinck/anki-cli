from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

import anki_cli.db.anki_direct as direct_mod
from anki_cli.db.anki_direct import AnkiDirectReadStore
from tests.integration.conftest import COL_TABLE_SQL, insert_col_row


def _make_store_with_cards_revlog(tmp_path: Path) -> tuple[AnkiDirectReadStore, Path]:
    db_path = tmp_path / "collection.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            did INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            type INTEGER NOT NULL,
            queue INTEGER NOT NULL,
            due INTEGER NOT NULL,
            ivl INTEGER NOT NULL,
            factor INTEGER NOT NULL,
            reps INTEGER NOT NULL,
            lapses INTEGER NOT NULL,
            left INTEGER NOT NULL,
            flags INTEGER NOT NULL,
            data TEXT NOT NULL,
            mod INTEGER NOT NULL DEFAULT 0,
            usn INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE revlog (
            id INTEGER PRIMARY KEY,
            cid INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            ease INTEGER NOT NULL,
            ivl INTEGER NOT NULL,
            lastIvl INTEGER NOT NULL,
            factor INTEGER NOT NULL,
            time INTEGER NOT NULL,
            type INTEGER NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO cards (
            id, did, ord, type, queue, due, ivl, factor, reps, lapses, left, flags, data, mod, usn
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (100, 1, 0, 2, 2, 30, 15, 2500, 20, 1, 0, 3, '{"x":1}', 111, 7),
    )
    conn.executescript(COL_TABLE_SQL)
    insert_col_row(conn, crt=0)
    conn.commit()
    conn.close()

    return AnkiDirectReadStore(db_path), db_path


def _card_row(db_path: Path, card_id: int) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT id, did, ord, type, queue, due, ivl, factor,
               reps, lapses, left, flags, data, mod, usn
        FROM cards
        WHERE id = ?
        """,
        (card_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    return dict(row)


def _revlog_rows(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, cid, usn, ease, ivl, lastIvl, factor, time, type FROM revlog ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _insert_revlog_row(db_path: Path, *, row_id: int, cid: int, ease: int = 3) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type)
        VALUES (?, ?, -1, ?, 10, 5, 2500, 0, 1)
        """,
        (row_id, cid, ease),
    )
    conn.commit()
    conn.close()


def test_snapshot_card_state_returns_expected_fields(tmp_path: Path) -> None:
    store, _db_path = _make_store_with_cards_revlog(tmp_path)

    snap = store.snapshot_card_state(100)

    created_at = snap.pop("created_at_epoch_ms")
    assert isinstance(created_at, int) and created_at > 0
    assert snap == {
        "id": 100,
        "did": 1,
        "ord": 0,
        "type": 2,
        "queue": 2,
        "due": 30,
        "ivl": 15,
        "factor": 2500,
        "reps": 20,
        "lapses": 1,
        "left": 0,
        "flags": 3,
        "data": '{"x":1}',
    }


def test_snapshot_card_state_missing_card_raises_lookup(tmp_path: Path) -> None:
    store, _db_path = _make_store_with_cards_revlog(tmp_path)

    with pytest.raises(LookupError, match="Card not found"):
        store.snapshot_card_state(999)


def test_restore_card_state_updates_card_and_deletes_newer_revlog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store, db_path = _make_store_with_cards_revlog(tmp_path)

    monkeypatch.setattr(direct_mod.time, "time", lambda: 1234.567)

    # Older revlog row from before the snapshot; must be preserved.
    _insert_revlog_row(db_path, row_id=1000, cid=100)
    # Rows written by the review being undone (after the snapshot); deleted.
    _insert_revlog_row(db_path, row_id=5000, cid=100)
    _insert_revlog_row(db_path, row_id=6000, cid=100)
    # Row for a different card; untouched even though it is newer.
    _insert_revlog_row(db_path, row_id=7000, cid=200)

    snapshot = {
        "id": 100,
        "did": 9,
        "ord": 2,
        "type": 1,
        "queue": 3,
        "due": 98765,
        "ivl": 42,
        "factor": 1900,
        "reps": 33,
        "lapses": 4,
        "left": 2002,
        "flags": 1,
        "data": '{"restored":true}',
        "created_at_epoch_ms": 2000,
    }

    result = store.restore_card_state(snapshot)

    assert result == {"card_id": 100, "restored": True, "revlog_deleted": 2}

    row = _card_row(db_path, 100)
    assert row["did"] == 9
    assert row["ord"] == 2
    assert row["type"] == 1
    assert row["queue"] == 3
    assert row["due"] == 98765
    assert row["ivl"] == 42
    assert row["factor"] == 1900
    assert row["reps"] == 33
    assert row["lapses"] == 4
    assert row["left"] == 2002
    assert row["flags"] == 1
    assert row["data"] == '{"restored":true}'
    assert row["mod"] == 1234  # int(time.time())
    assert row["usn"] == -1

    revlog = _revlog_rows(db_path)
    assert [r["id"] for r in revlog] == [1000, 7000]
    assert all(r["type"] == 1 for r in revlog)


def test_restore_card_state_without_snapshot_timestamp_leaves_revlog(
    tmp_path: Path,
) -> None:
    store, db_path = _make_store_with_cards_revlog(tmp_path)

    _insert_revlog_row(db_path, row_id=1000, cid=100)
    _insert_revlog_row(db_path, row_id=5000, cid=100)

    result = store.restore_card_state(
        {
            "id": 100,
            "did": 1,
            "ord": 0,
            "type": 2,
            "queue": 2,
            "due": 30,
            "ivl": 15,
            "factor": 2500,
            "reps": 20,
            "lapses": 1,
            "left": 0,
            "flags": 0,
            "data": "",
        }
    )

    assert result == {"card_id": 100, "restored": True, "revlog_deleted": 0}
    assert [r["id"] for r in _revlog_rows(db_path)] == [1000, 5000]


def test_restore_card_state_missing_id_type_raises_value_error(tmp_path: Path) -> None:
    store, _db_path = _make_store_with_cards_revlog(tmp_path)

    with pytest.raises(ValueError, match=r"snapshot.id must be an int"):
        store.restore_card_state({"id": "100"})


def test_restore_card_state_missing_target_card_returns_restored_false(
    tmp_path: Path,
) -> None:
    store, db_path = _make_store_with_cards_revlog(tmp_path)

    result = store.restore_card_state(
        {
            "id": 999,  # does not exist
            "did": 1,
            "ord": 0,
            "type": 0,
            "queue": 0,
            "due": 0,
            "ivl": 0,
            "factor": 0,
            "reps": 0,
            "lapses": 0,
            "left": 0,
            "flags": 0,
            "data": "",
            "created_at_epoch_ms": 2000,
        }
    )

    assert result == {"card_id": 999, "restored": False, "revlog_deleted": 0}
    assert _revlog_rows(db_path) == []
