"""JSON Schemaバリデーション（layer4_persistence_design.md §3手順3・§8）。

`market_snapshot`はトップレベルの必須キーの存在のみを検証する（内部の詳細な妥当性—
スコアの範囲や配点の整合性等—はLayer2の責務でありLayer4は検証しない、§3）。
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

_SCHEMA_DIR = Path(__file__).resolve().parent / "schema"


class SchemaValidationError(Exception):
    """market_snapshotのトップレベル形式が不正な場合に送出する（§9のSNAPSHOT_SCHEMA_INVALID）。"""


def _load_schema(name: str) -> dict:
    with open(_SCHEMA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_market_snapshot(content: dict) -> None:
    schema = _load_schema("market_snapshot.schema.json")
    try:
        jsonschema.validate(instance=content, schema=schema)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(str(exc)) from exc


def validate_completion_flag(content: dict) -> None:
    schema = _load_schema("layer4_completed.schema.json")
    jsonschema.validate(instance=content, schema=schema)


def validate_execution_log(content: dict) -> None:
    schema = _load_schema("execution_log.schema.json")
    jsonschema.validate(instance=content, schema=schema)
