from __future__ import annotations

import pytest

pytest.importorskip("textual")

import anki_cli.tui._utils as utils_mod

pytestmark = pytest.mark.tui

_NOW = 1_700_000_000


@pytest.mark.parametrize(
    ("delta_secs", "expected"),
    [
        (-60, "<1m"),      # past timestamps clamp to zero
        (0, "<1m"),
        (59, "<1m"),
        (60, "1m"),
        (3599, "59m"),
        (3600, "1h"),
        (86399, "23h"),
        (86400, "1d"),
        (36 * 3600, "2d"),  # pins the ceiling: 1.5d rounds up, not down
    ],
)
def test_relative_eta(
    monkeypatch: pytest.MonkeyPatch, delta_secs: int, expected: str
) -> None:
    monkeypatch.setattr(utils_mod.time, "time", lambda: _NOW)
    assert utils_mod.relative_eta(_NOW + delta_secs) == expected
