from __future__ import annotations

from datetime import datetime, timezone
import html
import re
from typing import Any

from ygc.extractors.serial import (
    EXTRACTION_VERSION,
    select_serial,
)


VINTAGE_YEAR_MAX = 1980


MODERN_PRODUCT_PATTERNS = [
    r"\bcustom\s+shop\b",
    r"\bmasterbuilt\b",
    r"\bmaster\s+built\b",
    r"\bamerican\s+vintage\s+ii\b",
    r"\bamerican\s+vintage\b",
    r"\bultra\s+luxe\s+vintage\b",
    r"\bvintage\s+modified\b",
    r"\bvintage\s+reissue\b",
    r"\bvintera\b",
    r"\bre[- ]?issue\b",
    r"\btime\s+capsule\b",
    r"\bcloset\s+classic\b",
    r"\bjourneyman\b",
    r"\bhistoric\s+reissue\b",
    r"\bhistoric\s+collection\b",
    r"\banniversary\b",
    r"\btribute\b",
    r"\breplica\b",
]


TITLE_YEAR_NEGATIVE_CONTEXT = [
    "neck",
    "body",
    "pickup",
    "pickups",
    "pot",
    "pots",
    "potentiometer",
    "code",
    "serial",
    "case",
    "spec",
    "specs",
    "style",
    "styled",
    "reissue",
    "re-issue",
    "tribute",
    "anniversary",
    "inspired",
    "replica",
    "copy",
]


NON_GUITAR_CATEGORY_WORDS = [
    "amp",
    "amps",
    "amplifier",
    "amplifiers",
    "pedal",
    "pedals",
    "effects",
    "accessories",
    "parts",
    "cases",
    "strings",
    "pickups",
]


def _strip_html(
    value: str | None,
) -> str:
    if not value:
        return ""

    text = html.unescape(
        str(value)
    )

    text = re.sub(
        r"<br\s*/?>",
        "\n",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"</p\s*>",
        "\n",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = text.replace(
        "\xa0",
        " ",
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n\s*\n+",
        "\n",
        text,
    )

    return text.strip()


def _text(
    value: Any,
) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _category_text(
    item: dict,
) -> str:
    categories = (
        item.get("categories")
        or []
    )

    values: list[str] = []

    for category in categories:
        if isinstance(
            category,
            dict,
        ):
            for key in (
                "full_name",
                "name",
                "slug",
            ):
                value = category.get(
                    key
                )

                if value:
                    values.append(
                        str(value)
                    )

        elif category:
            values.append(
                str(category)
            )

    category = item.get(
        "category"
    )

    if isinstance(
        category,
        dict,
    ):
        for key in (
            "full_name",
            "name",
            "slug",
        ):
            value = category.get(
                key
            )

            if value:
                values.append(
                    str(value)
                )

    elif category:
        values.append(
            str(category)
        )

    return " ".join(
        values
    ).lower()


def _guitar_category_state(
    item: dict,
) -> bool | None:
    """
    True:
        ギター本体カテゴリーと判断できる

    False:
        アンプ、エフェクター、パーツなど
        明確に対象外

    None:
        カテゴリー情報不足
    """

    category_text = (
        _category_text(
            item
        )
    )

    if not category_text:
        return None

    for word in (
        NON_GUITAR_CATEGORY_WORDS
    ):
        if word in category_text:
            return False

    if "guitar" in category_text:
        return True

    return None


def _modern_product_marker(
    item: dict,
) -> str | None:
    """
    title / model / year のみから
    明確な現代製品・復刻系を検出する。

    descriptionは使用しない。
    """

    title = _text(
        item.get("title")
    )

    model = _text(
        item.get("model")
    )

    year = _text(
        item.get("year")
    )

    target = (
        f"{title} {model} {year}"
    )

    for pattern in (
        MODERN_PRODUCT_PATTERNS
    ):
        if re.search(
            pattern,
            target,
            flags=re.I,
        ):
            return pattern

    return None


def _extract_year_numbers(
    value: str,
) -> list[int]:
    if not value:
        return []

    current_year = (
        datetime.now(
            timezone.utc
        ).year
    )

    result: list[int] = []

    for match in re.finditer(
        r"(?<!\d)"
        r"(19\d{2}|20\d{2})"
        r"(?!\d)",
        value,
    ):
        year = int(
            match.group(1)
        )

        if (
            1930
            <= year
            <= current_year
        ):
            result.append(
                year
            )

    return result


def _parse_structured_year(
    value: Any,
) -> tuple[
    str,
    int | None,
    str,
]:
    """
    Reverbの構造化yearフィールドを解析する。

    戻り値:
        status
        estimated_year
        reason
    """

    text = _text(
        value
    )

    if not text:
        return (
            "unknown",
            None,
            "no_structured_year",
        )

    years = (
        _extract_year_numbers(
            text
        )
    )

    if not years:
        decade_match = re.search(
            r"\b(19\d)0s\b",
            text,
            flags=re.I,
        )

        if decade_match:
            decade = int(
                decade_match.group(1)
                + "0"
            )

            if (
                decade + 9
                <= VINTAGE_YEAR_MAX
            ):
                return (
                    "vintage",
                    decade,
                    (
                        "structured_year_"
                        f"decade:{text}"
                    ),
                )

            if (
                decade
                > VINTAGE_YEAR_MAX
            ):
                return (
                    "modern",
                    decade,
                    (
                        "structured_year_"
                        f"decade:{text}"
                    ),
                )

        return (
            "unknown",
            None,
            (
                "unparseable_"
                f"structured_year:{text}"
            ),
        )

    minimum = min(
        years
    )

    maximum = max(
        years
    )

    if (
        maximum
        <= VINTAGE_YEAR_MAX
    ):
        return (
            "vintage",
            minimum,
            (
                "structured_year:"
                f"{text}"
            ),
        )

    if (
        minimum
        > VINTAGE_YEAR_MAX
    ):
        return (
            "modern",
            minimum,
            (
                "structured_year:"
                f"{text}"
            ),
        )

    return (
        "unknown",
        minimum,
        (
            "structured_year_"
            f"crosses_cutoff:{text}"
        ),
    )


def _title_year_candidates(
    title: str,
) -> list[int]:
    """
    タイトル中の年式候補だけを見る。

    例:
        1974 Fender Stratocaster
            -> 1974

        with 1978 neck
            -> 除外

        1957 reissue
            -> 除外
    """

    if not title:
        return []

    current_year = (
        datetime.now(
            timezone.utc
        ).year
    )

    candidates: list[int] = []

    for match in re.finditer(
        r"(?<!\d)"
        r"(19\d{2}|20\d{2})"
        r"(?!\d)",
        title,
    ):
        year = int(
            match.group(1)
        )

        if not (
            1930
            <= year
            <= current_year
        ):
            continue

        start = max(
            0,
            match.start() - 22,
        )

        end = min(
            len(title),
            match.end() + 22,
        )

        context = (
            title[start:end]
            .lower()
        )

        rejected = False

        for word in (
            TITLE_YEAR_NEGATIVE_CONTEXT
        ):
            if word in context:
                rejected = True
                break

        if rejected:
            continue

        candidates.append(
            year
        )

    return candidates


def _parse_title_year(
    title: str,
) -> tuple[
    str,
    int | None,
    str,
]:
    candidates = (
        _title_year_candidates(
            title
        )
    )

    unique = sorted(
        set(
            candidates
        )
    )

    if not unique:
        return (
            "unknown",
            None,
            "no_reliable_title_year",
        )

    if len(unique) > 1:
        return (
            "unknown",
            None,
            (
                "multiple_title_years:"
                + ",".join(
                    str(value)
                    for value
                    in unique
                )
            ),
        )

    year = unique[0]

    if year <= VINTAGE_YEAR_MAX:
        return (
            "vintage",
            year,
            (
                "title_year:"
                f"{year}"
            ),
        )

    return (
        "modern",
        year,
        (
            "title_year:"
            f"{year}"
        ),
    )


def classify_vintage_listing(
    item: dict,
) -> dict:
    """
    Vintage自動収集用の保守的な分類。

    status:
        vintage
        modern
        unknown
        non_target

    description内の年号は
    製造年判定には使用しない。
    """

    category_state = (
        _guitar_category_state(
            item
        )
    )

    if category_state is False:
        return {
            "status": (
                "non_target"
            ),
            "estimated_year": None,
            "reason": (
                "non_guitar_category"
            ),
        }

    marker = (
        _modern_product_marker(
            item
        )
    )

    if marker:
        return {
            "status": "modern",
            "estimated_year": None,
            "reason": (
                "modern_product_marker:"
                f"{marker}"
            ),
        }

    (
        structured_status,
        structured_year,
        structured_reason,
    ) = _parse_structured_year(
        item.get("year")
    )

    if (
        structured_status
        != "unknown"
    ):
        return {
            "status": (
                structured_status
            ),
            "estimated_year": (
                structured_year
            ),
            "reason": (
                structured_reason
            ),
        }

    title = _text(
        item.get("title")
    )

    (
        title_status,
        title_year,
        title_reason,
    ) = _parse_title_year(
        title
    )

    if (
        title_status
        != "unknown"
    ):
        return {
            "status": (
                title_status
            ),
            "estimated_year": (
                title_year
            ),
            "reason": (
                title_reason
            ),
        }

    reason = (
        structured_reason
        if structured_reason
        != "no_structured_year"
        else title_reason
    )

    return {
        "status": "unknown",
        "estimated_year": None,
        "reason": reason,
    }


def _seller_name(
    item: dict,
) -> str | None:
    direct = item.get(
        "shop_name"
    )

    if direct:
        return str(
            direct
        )

    shop = item.get(
        "shop"
    )

    if isinstance(
        shop,
        dict,
    ):
        name = shop.get(
            "name"
        )

        if name:
            return str(
                name
            )

    return None


def _source_url(
    item: dict,
) -> str | None:
    links = (
        item.get("_links")
        or {}
    )

    web = links.get(
        "web"
    )

    if isinstance(
        web,
        dict,
    ):
        href = web.get(
            "href"
        )

        if href:
            return str(
                href
            )

    return None


def listing_image_url(
    item: dict,
) -> str | None:
    explicit = _text(
        item.get(
            "_ygc_image_url"
        )
    )

    if explicit:
        return explicit

    photos = (
        item.get("photos")
        or item.get("images")
        or []
    )

    if isinstance(
        photos,
        dict,
    ):
        photos = (
            photos.get("items")
            or photos.get("photos")
            or photos.get("images")
            or []
        )

    if isinstance(
        photos,
        list,
    ):
        for photo in photos:
            if isinstance(
                photo,
                str,
            ):
                value = photo.strip()
                if value:
                    return value

            if not isinstance(
                photo,
                dict,
            ):
                continue

            for key in (
                "url",
                "href",
            ):
                value = photo.get(
                    key
                )
                if value:
                    return str(
                        value
                    )

            links = (
                photo.get("_links")
                or {}
            )

            for key in (
                "large_crop",
                "full",
                "supersize",
                "large",
                "small_crop",
            ):
                link = links.get(
                    key
                )

                if isinstance(
                    link,
                    dict,
                ):
                    href = link.get(
                        "href"
                    )
                    if href:
                        return str(
                            href
                        )

    links = (
        item.get("_links")
        or {}
    )

    for key in (
        "photo",
        "image",
    ):
        link = links.get(
            key
        )

        if isinstance(
            link,
            dict,
        ):
            href = link.get(
                "href"
            )
            if href:
                return str(
                    href
                )

    return None


def _serial_text(
    item: dict,
) -> str:
    title = _text(
        item.get("title")
    )

    description = _strip_html(
        item.get("description")
    )

    return "\n".join(
        value
        for value in (
            title,
            description,
        )
        if value
    )


def to_observation(
    item: dict,
    serial_threshold: float = 0.70,
) -> dict:
    """
    Reverb Listing JSONを
    Phase 0 Observation形式へ変換する。

    Repository.upsert_observation() が
    必要とするDB列をすべて返す。
    """

    classification = (
        classify_vintage_listing(
            item
        )
    )

    raw_text = (
        _serial_text(
            item
        )
    )

    serial_candidate = (
        select_serial(
            raw_text,
            threshold=(
                serial_threshold
            ),
        )
    )

    source_listing_id = (
        item.get("id")
    )

    if source_listing_id is None:
        source_listing_id = (
            item.get(
                "listing_id"
            )
        )

    manufacturer = (
        _text(
            item.get("make")
        )
        or None
    )

    model = (
        _text(
            item.get("model")
        )
        or None
    )

    finish = (
        _text(
            item.get("finish")
        )
        or None
    )

    year = (
        _text(
            item.get("year")
        )
        or None
    )

    title = (
        _text(
            item.get("title")
        )
        or None
    )

    published_at = (
        item.get(
            "published_at"
        )
        or item.get(
            "created_at"
        )
    )

    now = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    return {
        "individual_id": None,

        "manufacturer": (
            manufacturer
        ),

        "model": (
            model
        ),

        "finish": (
            finish
        ),

        "year": (
            year
        ),

        "serial_number": (
            serial_candidate.value
            if serial_candidate
            else None
        ),

        "seller": (
            _seller_name(
                item
            )
        ),

        "source_site": (
            "reverb"
        ),

        "source_url": (
            _source_url(
                item
            )
        ),

        "image_url": (
            listing_image_url(
                item
            )
        ),

        "source_listing_id": (
            str(source_listing_id)
            if source_listing_id
            is not None
            else None
        ),

        "observed_at": (
            now
        ),

        "listing_date": (
            str(published_at)
            if published_at
            else None
        ),

        "title": (
            title
        ),

        "raw_text": (
            raw_text
        ),

        "serial_confidence": (
            serial_candidate.confidence
            if serial_candidate
            else None
        ),

        "extraction_version": (
            EXTRACTION_VERSION
        ),

        "created_at": (
            now
        ),

        # 以下はcrawl中だけ使用する
        # DB保存前にcli.py側でpopされる。
        "is_vintage_listing": (
            classification[
                "status"
            ]
            == "vintage"
        ),

        "vintage_status": (
            classification[
                "status"
            ]
        ),

        "vintage_reason": (
            classification[
                "reason"
            ]
        ),

        "estimated_year": (
            classification[
                "estimated_year"
            ]
        ),
    }