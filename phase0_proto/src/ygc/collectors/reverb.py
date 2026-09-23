from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

import httpx


log = logging.getLogger(__name__)


class ReverbAPICollector:
    """
    Reverb公式APIを利用するRead-only Collector。

    高速化方針:
    - 一覧APIでは詳細を取得しない
    - 一覧データを呼び出し側でフィルタする
    - Vintage候補のみ詳細APIを取得する
    - 詳細取得は少数並列で行う
    - 429 / 一時的な5xxはバックオフして再試行する
    """

    def __init__(
        self,
        token: str,
        api_base: str = "https://api.reverb.com/api",
        timeout: float = 20.0,
        delay: float = 0.15,
        max_workers: int = 6,
        max_retries: int = 3,
    ):
        if not token:
            raise ValueError(
                "REVERB_API_TOKEN is required"
            )

        self.api_base = api_base.rstrip("/")
        self.delay = max(
            0.0,
            delay,
        )

        self.max_workers = max(
            1,
            max_workers,
        )

        self.max_retries = max(
            0,
            max_retries,
        )

        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": (
                    f"Bearer {token}"
                ),
                "Accept": (
                    "application/hal+json"
                ),
                "Content-Type": (
                    "application/hal+json"
                ),
                "Accept-Version": "3.0",
                "User-Agent": (
                    "YourGuitarChronicle-"
                    "Phase0/0.2"
                ),
            },
            limits=httpx.Limits(
                max_connections=12,
                max_keepalive_connections=12,
            ),
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        self.close()

    def _get_json(
        self,
        url: str,
        params: dict | None = None,
    ) -> dict:
        """
        GET + retry/backoff。

        429および一時的な5xxを再試行する。
        """

        last_error: Exception | None = None

        for attempt in range(
            self.max_retries + 1
        ):
            try:
                log.info(
                    "GET %s params=%s",
                    url,
                    params,
                )

                response = self.client.get(
                    url,
                    params=params,
                )

                if response.status_code == 429:
                    retry_after = (
                        response.headers.get(
                            "Retry-After"
                        )
                    )

                    if retry_after:
                        try:
                            wait = float(
                                retry_after
                            )
                        except ValueError:
                            wait = (
                                1.0
                                * (2 ** attempt)
                            )
                    else:
                        wait = (
                            1.0
                            * (2 ** attempt)
                        )

                    log.warning(
                        "Rate limited. "
                        "Retrying in %.1fs",
                        wait,
                    )

                    time.sleep(wait)
                    continue

                if (
                    500
                    <= response.status_code
                    < 600
                ):
                    wait = (
                        0.5
                        * (2 ** attempt)
                    )

                    log.warning(
                        "Server error %s. "
                        "Retrying in %.1fs",
                        response.status_code,
                        wait,
                    )

                    time.sleep(wait)
                    continue

                response.raise_for_status()

                return response.json()

            except httpx.HTTPError as exc:
                last_error = exc

                if attempt >= self.max_retries:
                    raise

                wait = (
                    0.5
                    * (2 ** attempt)
                )

                log.warning(
                    "HTTP error: %s. "
                    "Retrying in %.1fs",
                    exc,
                    wait,
                )

                time.sleep(wait)

        if last_error:
            raise last_error

        raise RuntimeError(
            "Unexpected Reverb API failure"
        )

    @staticmethod
    def _next_href(
        payload: dict,
    ) -> str | None:
        next_link = (
            payload.get("_links") or {}
        ).get("next")

        if isinstance(
            next_link,
            dict,
        ):
            return next_link.get(
                "href"
            )

        return None

    @staticmethod
    def _self_href(
        item: dict,
    ) -> str | None:
        links = (
            item.get("_links")
            or {}
        )

        for key in (
            "self",
            "listing",
        ):
            link = links.get(
                key
            )

            if (
                isinstance(
                    link,
                    dict,
                )
                and link.get(
                    "href"
                )
            ):
                return link[
                    "href"
                ]

        return None

    @staticmethod
    def listing_id(
        item: dict,
    ) -> str | None:
        value = (
            item.get("id")
            or item.get(
                "listing_id"
            )
            or item.get(
                "uuid"
            )
        )

        if value is None:
            return None

        return str(value)

    def iter_listing_summaries(
        self,
        query: str,
        limit: int,
    ) -> Iterable[dict]:
        """
        一覧APIだけを取得する。

        ここではListing詳細APIを呼ばない。
        """

        count = 0

        url = (
            f"{self.api_base}/listings"
        )

        params: dict | None = {
            "query": query,
        }

        while (
            url
            and count < limit
        ):
            payload = self._get_json(
                url,
                params=params,
            )

            params = None

            listings = (
                payload.get(
                    "listings"
                )
                or payload.get(
                    "_embedded",
                    {},
                ).get(
                    "listings"
                )
                or []
            )

            for item in listings:
                if count >= limit:
                    break

                yield item
                count += 1

            url = self._next_href(
                payload
            )

            if (
                url
                and count < limit
                and self.delay > 0
            ):
                time.sleep(
                    self.delay
                )

    def fetch_listing_detail(
        self,
        item: dict,
    ) -> dict:
        """
        1件のListing詳細を取得する。
        """

        detail_url = (
            self._self_href(
                item
            )
        )

        if not detail_url:
            return item

        try:
            return self._get_json(
                detail_url
            )

        except httpx.HTTPError as exc:
            log.warning(
                "Could not fetch "
                "listing detail %s: %s",
                detail_url,
                exc,
            )

            return item

    def fetch_listing_details(
        self,
        items: list[dict],
    ) -> Iterable[dict]:
        """
        Listing詳細を並列取得する。

        順序保証は不要。
        完了したものから返す。
        """

        if not items:
            return

        if self.max_workers <= 1:
            for item in items:
                yield (
                    self.fetch_listing_detail(
                        item
                    )
                )
            return

        with ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:

            futures = {
                executor.submit(
                    self.fetch_listing_detail,
                    item,
                ): item
                for item in items
            }

            for future in as_completed(
                futures
            ):
                original = futures[
                    future
                ]

                try:
                    yield future.result()

                except Exception as exc:
                    listing_id = (
                        self.listing_id(
                            original
                        )
                    )

                    log.warning(
                        "Detail fetch failed "
                        "for listing %s: %s",
                        listing_id,
                        exc,
                    )

                    yield original

    def probe(
        self,
        query: str = (
            "Fender Stratocaster"
        ),
    ) -> dict:
        return self._get_json(
            f"{self.api_base}/listings",
            params={
                "query": query,
            },
        )