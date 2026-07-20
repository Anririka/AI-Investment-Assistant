"""ReportSink抽象クラス（layer6_report_generation_design.md §11）。

すべてのSinkは同一の`PresentationModel`を入力とし、`render`（媒体固有の出力生成）と
`save`（実際の保存先への書き込み）の2段階に分離する。1つのSinkの失敗が他のSinkの実行を
妨げてはならない（§3手順5・§10）ため、呼び出し側（main.py）が例外を捕捉する。
"""

from __future__ import annotations

import abc
from typing import Any


class ReportSink(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def render(self, presentation_model: dict) -> Any:
        """PresentationModelから、この媒体固有の出力（Sheets行データ、Markdown文字列等）を生成する。"""

    @abc.abstractmethod
    def save(self, rendered_content: Any) -> str:
        """生成した内容を実際の保存先へ送り、保存先パス（または識別子）を返す。"""

    def render_and_save(self, presentation_model: dict) -> str:
        rendered = self.render(presentation_model)
        return self.save(rendered)
