"""Layer5の入出力契約バリデーション（layer5_ai_judgment_design.md §4・§9・§12）。

§12「選択肢B移行を見据えた契約テスト」：layer5_input_schema.json／
layer5_output_schema.jsonに対するJSON Schemaバリデーションが、モデルによらず
一貫して通ることを検証する（将来モデル切替時の回帰防止）。
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

_CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"


class SchemaValidationError(Exception):
    pass


def _load_schema(name: str) -> dict:
    with open(_CONTRACTS_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_layer5_input(layer2_output: dict, portfolio_state: dict) -> None:
    schema = _load_schema("layer5_input_schema.json")
    instance = {"layer2_output": layer2_output, "portfolio_state": portfolio_state}
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(str(exc)) from exc


def validate_layer5_output(decision_document: dict) -> None:
    schema = _load_schema("layer5_output_schema.json")
    try:
        jsonschema.validate(instance=decision_document, schema=schema)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(str(exc)) from exc
