from __future__ import annotations

from dataclasses import dataclass
import re


EXTRACTION_VERSION = "serial-v3"


@dataclass(frozen=True)
class SerialCandidate:
    value: str
    confidence: float
    context: str
    reason: str


_SERIAL_VALUE = (
    r"((?:[A-Z]\s+\d{4,8})|"
    r"(?:[^\s,;|()\[\]{}]{3,32}))"
)


LABEL_PATTERNS = [
    (
        re.compile(
            r"\bserial\s*"
            r"(?:number|no\.?|#)?\s*"
            r"[:#-]?\s*"
            + _SERIAL_VALUE,
            re.I,
        ),
        0.95,
        "serial-label",
    ),
    (
        re.compile(
            r"\bser\.?\s*"
            r"(?:no\.?|#)?\s*"
            r"[:#-]?\s*"
            + _SERIAL_VALUE,
            re.I,
        ),
        0.92,
        "ser-label",
    ),
    (
        re.compile(
            r"\bS\s*/\s*N\s*"
            r"[:#-]?\s*"
            + _SERIAL_VALUE,
            re.I,
        ),
        0.92,
        "s-n-label",
    ),
    (
        re.compile(
            r"\bSN\s*[:#-]\s*"
            + _SERIAL_VALUE,
            re.I,
        ),
        0.88,
        "sn-label",
    ),
]


NEGATIVE_WORDS = {
    "pot",
    "potentiometer",
    "neck date",
    "pickup",
    "patent",
    "price",
    "item number",
    "item #",
    "sku",
    "weight",
    "phone",
    "fon",
    "factory order",
}


TRAILING_LABELS = {
    "WEIGHT",
    "COLOR",
    "COLOUR",
    "CASE",
    "CONDITION",
    "FINISH",
    "MODEL",
    "YEAR",
    "PRICE",
    "SKU",
    "MADE",
    "ORIGINAL",
    "WITH",
    "INCLUDES",
    "HEADSTOCK",
    "NOTES",
    "NOTE",
}


PROSE_MARKERS = {
    "THAT",
    "DATES",
    "DATED",
    "DATESTO",
    "DATESIT",
    "DATEBACK",
    "HEADSTOCK",
    "YOUR",
}


def _strip_htmlish_spacing(
    value: str,
) -> str:
    value = value.replace(
        "\r",
        " ",
    )

    value = value.replace(
        "\n",
        " ",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def _trim_trailing_labels(
    raw: str,
) -> str:
    """
    Serial直後に本文や次の見出しが接続されたケースを切る。

    例:
        524436WEIGHT
            -> 524436

        L53450.HEADSTOCK
            -> L53450

        73178142--YOUR
            -> 73178142
    """

    value = (
        raw.strip()
        .upper()
        .strip(
            "\"'"
        )
    )

    value = value.rstrip(
        ".,:;!?)]}"
    )

    value = re.split(
        r"--+|—|–",
        value,
        maxsplit=1,
    )[0]

    dotted_suffix = re.fullmatch(
        r"(.+?)[._/-]"
        r"([A-Z]{3,})",
        value,
    )

    if dotted_suffix:
        prefix = dotted_suffix.group(
            1
        )

        suffix = dotted_suffix.group(
            2
        )

        if (
            any(
                ch.isdigit()
                for ch in prefix
            )
            and (
                suffix
                in TRAILING_LABELS
                or suffix
                in PROSE_MARKERS
            )
        ):
            value = prefix

    for label in sorted(
        TRAILING_LABELS,
        key=len,
        reverse=True,
    ):
        if not value.endswith(
            label
        ):
            continue

        candidate = value[
            : -len(label)
        ].rstrip(
            "._/- "
        )

        if (
            len(candidate) >= 3
            and any(
                ch.isdigit()
                for ch in candidate
            )
        ):
            value = candidate
            break

    return value.rstrip(
        ".,:;!?)]}"
    )


def _normalize_candidate(
    raw: str,
) -> str:
    value = _strip_htmlish_spacing(
        raw
    )

    if not value:
        return ""

    value = re.sub(
        r"^([A-Z])\s+"
        r"(\d{4,8})$",
        r"\1\2",
        value,
        flags=re.I,
    )

    return _trim_trailing_labels(
        value
    )


def _looks_masked(
    value: str,
) -> bool:
    upper = value.upper()

    return bool(
        re.search(
            r"X{2,}"
            r"|\?{2,}"
            r"|\*{2,}"
            r"|#{2,}",
            upper,
        )
    )


def _looks_like_prose(
    value: str,
) -> bool:
    upper = value.upper()

    return any(
        marker in upper
        for marker
        in PROSE_MARKERS
    )


def _looks_like_serial(
    value: str,
) -> bool:
    """
    Phase 0用の保守的なSerial妥当性チェック。

    v3では抽出率よりPrecisionを優先する。
    """

    if not value:
        return False

    value = value.upper()

    if len(value) < 4:
        return False

    if len(value) > 18:
        return False

    if _looks_masked(
        value
    ):
        return False

    if _looks_like_prose(
        value
    ):
        return False

    if value.isalpha():
        return False

    if value.isdigit():
        if re.fullmatch(
            r"(19|20)\d{2}",
            value,
        ):
            return False

        return (
            4
            <= len(value)
            <= 10
        )

    has_alpha = any(
        ch.isalpha()
        for ch in value
    )

    has_digit = any(
        ch.isdigit()
        for ch in value
    )

    if not (
        has_alpha
        and has_digit
    ):
        return False

    if not re.fullmatch(
        r"[A-Z0-9._/-]+",
        value,
    ):
        return False

    if re.search(
        r"[._/-][A-Z]{3,}$",
        value,
    ):
        return False

    return True


def _score_candidate(
    value: str,
    base_confidence: float,
    context: str,
) -> float:
    confidence = (
        base_confidence
    )

    lower_context = (
        context.lower()
    )

    for negative in (
        NEGATIVE_WORDS
    ):
        if (
            negative
            not in lower_context
        ):
            continue

        if (
            "serial"
            in lower_context
            or "s/n"
            in lower_context
            or "sn:"
            in lower_context
        ):
            confidence -= 0.05
        else:
            confidence -= 0.35

    if not _looks_like_serial(
        value
    ):
        confidence -= 0.95

    return max(
        0.0,
        min(
            1.0,
            confidence,
        ),
    )


def extract_serial_candidates(
    text: str | None,
) -> list[SerialCandidate]:
    if not text:
        return []

    candidates: list[
        SerialCandidate
    ] = []

    for (
        pattern,
        base_confidence,
        reason,
    ) in LABEL_PATTERNS:

        for match in pattern.finditer(
            text
        ):
            raw = match.group(
                1
            )

            value = (
                _normalize_candidate(
                    raw
                )
            )

            if not value:
                continue

            start = max(
                0,
                match.start() - 80,
            )

            end = min(
                len(text),
                match.end() + 80,
            )

            context = (
                text[
                    start:end
                ]
                .replace(
                    "\n",
                    " ",
                )
            )

            confidence = (
                _score_candidate(
                    value,
                    base_confidence,
                    context,
                )
            )

            if confidence <= 0:
                continue

            candidates.append(
                SerialCandidate(
                    value=value,
                    confidence=(
                        confidence
                    ),
                    context=context,
                    reason=reason,
                )
            )

    best: dict[
        str,
        SerialCandidate,
    ] = {}

    for candidate in (
        candidates
    ):
        existing = best.get(
            candidate.value
        )

        if (
            existing is None
            or candidate.confidence
            > existing.confidence
        ):
            best[
                candidate.value
            ] = candidate

    return sorted(
        best.values(),
        key=lambda candidate: (
            candidate.confidence
        ),
        reverse=True,
    )


def select_serial(
    text: str | None,
    threshold: float = 0.70,
) -> SerialCandidate | None:
    candidates = (
        extract_serial_candidates(
            text
        )
    )

    if not candidates:
        return None

    best = candidates[0]

    if (
        best.confidence
        < threshold
    ):
        return None

    return best
