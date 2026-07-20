"""market_snapshot_YYYYMMDD.jsonの書き込み（layer4_persistence_design.md §5-1）。

Layer2の出力を一切加工せず保存する（キーの追加・削除・改名・値の変換のいずれも行わない）。
"""

from __future__ import annotations

from .repository.base import PersistenceRepository


def write_snapshot(repository: PersistenceRepository, date_str: str, layer2_output: dict) -> str:
    return repository.save_snapshot(date_str, layer2_output)
