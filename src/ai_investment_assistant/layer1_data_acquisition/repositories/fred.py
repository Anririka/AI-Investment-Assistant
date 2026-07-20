"""FredRepository（MacroRepository実装、マクロ指標）。

layer1_data_acquisition_design.md 3-2確定仕様の`MacroRepository.get_series`を実装する。
FRED（セントルイス連銀）の公開API。欠測値（"."）はポイントを除外して扱う。
"""

from __future__ import annotations

import os
from datetime import date, datetime

import requests

from ..exceptions import AuthError, NotFoundError, RateLimitError, TransientError
from ..interfaces import MacroRepository
from ..models import DataFetchMeta, TimeSeries, TimeSeriesPoint

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
TIMEOUT_SECONDS = 30


class FredRepository(MacroRepository):
    """FRED API（マクロ指標）。"""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise AuthError("FRED_API_KEY is not set")
        self._api_key = api_key

    @classmethod
    def from_config(cls, entry: dict) -> "FredRepository":
        return cls(api_key=os.environ.get("FRED_API_KEY", ""))

    def get_series(self, series_id: str, start_date: date, end_date: date) -> TimeSeries:
        try:
            response = requests.get(
                BASE_URL,
                params={
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "observation_start": start_date.isoformat(),
                    "observation_end": end_date.isoformat(),
                },
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError(f"FRED rate limit: {response.text}")
        if response.status_code in (401, 403):
            raise AuthError(f"FRED auth error {response.status_code}: {response.text}")
        if response.status_code == 400:
            # FREDは不正なseries_idの場合400を返すことが多い（=対象外の系列ID）
            raise NotFoundError(f"FRED series not found or invalid request: {response.text}")
        if response.status_code >= 500:
            raise TransientError(f"FRED server error {response.status_code}")
        if response.status_code != 200:
            raise TransientError(f"FRED unexpected status {response.status_code}: {response.text}")

        payload = response.json()
        points = []
        for row in payload.get("observations", []):
            value_str = row.get("value")
            if value_str in (None, ".", ""):
                continue  # 欠測値はポイントから除外する
            points.append(
                TimeSeriesPoint(
                    date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    value=float(value_str),
                )
            )
        meta = DataFetchMeta(source_used="fred", fetched_at=datetime.utcnow())
        return TimeSeries(series_id=series_id, points=tuple(points), meta=meta)
