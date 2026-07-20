"""データ品質ゲートblocked時・JSON異常時のエラーレポート生成
（layer6_report_generation_design.md §10）。

不完全なデータで見た目だけ整えたレポートを出さない（§10）。診断的な内容に限定する。
"""

from __future__ import annotations

DISCLAIMER = (
    "本提案は情報提供を目的としたものであり、投資成果を保証するものではありません。"
    "最終判断はご自身で行ってください。"
)


def build_missing_decision_report() -> str:
    """decision JSON自体が存在しない／読み込めない場合（§10）。"""
    return (
        "# AI投資アシスタント 日次レポート\n\n"
        "## エラー\n\n"
        "本日のレポート生成に失敗しました。Layer5の出力が確認できません。\n\n"
        f"---\n{DISCLAIMER}\n"
    )


def build_blocked_report(decision_document: dict) -> str:
    """`run_meta.data_quality_gate` が `blocked` の場合（§10）。

    `data_quality_gate_detail.blocking_errors_found`の内容をそのまま表示する
    （Layer6は原因を解釈・推測しない）。
    """
    run_meta = decision_document.get("run_meta", {})
    detail = run_meta.get("data_quality_gate_detail", {})
    blocking_errors = detail.get("blocking_errors_found", [])

    lines = [
        "# AI投資アシスタント 日次レポート",
        "",
        "## 本日は様子見（データ品質ゲートによりブロック）",
        "",
        "検知されたブロッキングエラー:",
        "",
    ]
    if blocking_errors:
        for error in blocking_errors:
            code = error.get("code")
            message = error.get("message", "")
            lines.append(f"- {code}: {message}" if message else f"- {code}")
    else:
        lines.append("（詳細情報なし）")

    lines.extend(["", "---", DISCLAIMER, ""])
    return "\n".join(lines)


def build_schema_violation_report(details: str) -> str:
    """decision JSONのトップレベルキー欠落等、契約違反が疑われる場合（§10）。

    Layer5の契約違反の可能性が高いため、診断的なエラーレポートを生成し、通常の
    フォーマット処理は行わない。
    """
    return (
        "# AI投資アシスタント 日次レポート\n\n"
        "## エラー：Layer5出力の契約違反の疑い\n\n"
        f"{details}\n\n"
        "通常のレポート生成は行わず、この診断情報のみを記録しました。\n\n"
        f"---\n{DISCLAIMER}\n"
    )
