"""PersistenceRepository抽象クラス（layer4_persistence_design.md §11）。

保存系メソッド（`save_snapshot`／`save_completion_flag`／`save_execution_log`／
`save_history_index`）のみを定義する。読み込み系メソッドは一切含めない
（読み込みはLayer5の責務であり、Layer4のRepositoryに依存させない設計、§11）。
"""

from __future__ import annotations

import abc


class PersistenceRepository(abc.ABC):
    @abc.abstractmethod
    def save_snapshot(self, date_str: str, content: dict) -> str:
        """market_snapshot_{date_str}.jsonを保存し、保存先パス（相対パス）を返す。"""

    @abc.abstractmethod
    def save_completion_flag(self, date_str: str, content: dict) -> str:
        """layer4_completed_{date_str}.jsonを保存し、保存先パスを返す。"""

    @abc.abstractmethod
    def save_execution_log(self, date_str: str, content: dict) -> str:
        """execution_log_{date_str}.jsonを保存し、保存先パスを返す。"""

    @abc.abstractmethod
    def save_history_index(self, year_month: str, entry: dict) -> str:
        """history/index_{year_month}.jsonに`entry`を追記し、保存先パスを返す。"""
