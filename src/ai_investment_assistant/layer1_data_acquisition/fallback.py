"""FallbackChainRepository（layer1_data_acquisition_design.md 5章・6-2の確定仕様）。

同一インターフェースを実装する複数の具体Repositoryを優先順位付きリストとして保持し、
エラー種別に応じてフォールバックする（5-1のエラー分類表通り）。

  一時的エラー     : 指数バックオフで即時リトライ、上限回数超過で次候補へ
  レート制限超過   : 即座に次候補へ（このソースへの追加リトライはしない）
  認証・設定エラー : 次候補へフォールバックしつつ severity=critical としてログ
  データ不存在     : フォールバックしない（「対象外銘柄」として記録）
  全候補失敗       : AllSourcesFailedErrorを送出（呼び出し側は「取得不可」として扱う）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .exceptions import AllSourcesFailedError, AuthError, NotFoundError, RateLimitError, TransientError

logger = logging.getLogger(__name__)

MAX_TRANSIENT_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0


@dataclass
class ChainCandidate:
    """フォールバックチェーンの1候補。"""

    name: str
    repository: Any
    rate_limiter: Optional[Any] = None


class FallbackChainRepository:
    """優先順位付きのRepositoryチェーン。呼び出し時、先頭候補から順にフォールバックする。"""

    def __init__(
        self,
        candidates: list[ChainCandidate],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not candidates:
            raise ValueError("candidates must not be empty")
        self._candidates = candidates
        self._sleep = sleep
        # 直近のcall()で実際に使用した候補名（Layer3のsource_data_origin等、Repository
        # パターンの原則を崩さずに「どの候補が成功したか」を知りたい呼び出し元のための
        # 付加的な状態。戻り値の契約自体は変更しない、後方互換の拡張）。
        self.last_source_used: Optional[str] = None

    def call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """`method_name`を先頭候補から順に呼び出し、成功した結果をそのまま返す。

        使用したソース名等のメタ情報は、各Repository実装がモデルの`DataFetchMeta`に
        埋め込む前提（`source_used`等）とし、本メソッドはロジック分岐のみを担う。
        呼び出し元が「どの候補が成功したか」を知りたい場合は、呼び出し直後に
        `last_source_used`を参照できる（例：Layer3の`source_data_origin`記録用）。
        全候補失敗時はAllSourcesFailedErrorを送出する。
        データ不存在（NotFoundError）はフォールバックせず、そのまま呼び出し元に伝播する。
        """
        errors: list[Exception] = []
        for candidate in self._candidates:
            method = getattr(candidate.repository, method_name)
            attempt = 0
            while True:
                try:
                    if candidate.rate_limiter is not None:
                        candidate.rate_limiter.acquire()
                    result = method(*args, **kwargs)
                    self.last_source_used = candidate.name
                    return result
                except NotFoundError:
                    # データ不存在は次候補でも存在しない可能性が高いためフォールバックしない（5-1）
                    raise
                except RateLimitError as exc:
                    logger.warning(
                        "rate limit on source=%s, switching to next candidate", candidate.name
                    )
                    errors.append(exc)
                    break
                except AuthError as exc:
                    logger.error(
                        "severity=critical auth/config error on source=%s: %s",
                        candidate.name,
                        exc,
                    )
                    errors.append(exc)
                    break
                except TransientError as exc:
                    attempt += 1
                    errors.append(exc)
                    if attempt > MAX_TRANSIENT_RETRIES:
                        logger.warning(
                            "transient error on source=%s exceeded retry limit (%d), "
                            "switching to next candidate",
                            candidate.name,
                            MAX_TRANSIENT_RETRIES,
                        )
                        break
                    backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    self._sleep(backoff)
                    continue
        raise AllSourcesFailedError(
            f"all candidates failed for method='{method_name}'", errors=errors
        )
