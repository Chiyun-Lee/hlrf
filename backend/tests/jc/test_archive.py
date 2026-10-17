"""Append-only archive behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from journal_club.archive import Archive, ArchiveLocked, Event


def _ev(step: str, type_: str, **payload: object) -> Event:
    """Event with seq 0."""
    return Event(round=1, step=step, type=type_, papers=[], payload=dict(payload), seq=0)


def test_seq_monotone_and_file_only_grows(tmp_archive: Archive) -> None:
    sizes = []
    for i in range(5):
        stored = tmp_archive.append(_ev("map", "pair_verdict", i=i))
        assert stored.seq == i + 1
        sizes.append(tmp_archive.path.stat().st_size)
    assert sizes == sorted(sizes) and len(set(sizes)) == 5
    assert tmp_archive.last_seq == 5
    assert [e.seq for e in tmp_archive.read()] == [1, 2, 3, 4, 5]


def test_by_step_and_has_step_with_label(tmp_archive: Archive) -> None:
    tmp_archive.append(_ev("map", "pair_verdict"))
    tmp_archive.append(_ev("debate", "dispute"))
    assert not tmp_archive.has_step("map")
    tmp_archive.append(_ev("map", "step_done", count=1, card_ids_sha="x", label=None))
    assert tmp_archive.has_step("map")
    assert not tmp_archive.has_step("debate")
    assert len(tmp_archive.by_step("map")) == 2
    tmp_archive.append(_ev("judge", "step_done", count=1, card_ids_sha="x", label="club"))
    assert tmp_archive.has_step("judge")
    assert tmp_archive.has_step("judge", "club")
    assert not tmp_archive.has_step("judge", "baseline")


def test_second_archive_on_same_path_is_locked(tmp_archive: Archive) -> None:
    with pytest.raises(ArchiveLocked):
        Archive(tmp_archive.path)


def test_read_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with Archive(path) as a:
        a.append(_ev("map", "run_started", agenda="x"))
        a.append(_ev("map", "pair_verdict"))
    with Archive(path) as b:
        assert b.last_seq == 2
        assert [e.type for e in b.read()] == ["run_started", "pair_verdict"]
        assert b.append(_ev("map", "step_done")).seq == 3


def test_event_rejects_unknown_step_and_extra_field() -> None:
    with pytest.raises(ValueError):
        Event(round=1, step="dinner", type="x", papers=[], payload={}, seq=0)
    with pytest.raises(ValueError):
        Event(round=1, step="map", type="x", papers=[], payload={}, seq=0, extra=1)
