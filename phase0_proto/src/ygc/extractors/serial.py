from __future__ import annotations

from dataclasses import dataclass
import re


EXTRACTION_VERSION = "serial-v2"


@dataclass(frozen=True)
class SerialCandidate:
    value: str
    confidence: float
    context: str
    reason: str


LABEL_PATTERNS = [
    (
        re.compile(
            r"\bserial\s*(?:number|no\.?)?\s*[:#-]?\s*"
            r"([A-Z0-9][A-Z0-9 ./_-]{2,24})",
            re.I,
        ),
        0.95,
        "serial-label",
    ),
    (
        re.compile(
            r"\bS\s*/\s*N\s*[:#-]?\s*"
            r"([A-Z0-9][A-Z0-9 ./_-]{2,24})",
            re.I,
        ),
        0.92,
        "s-n-label",
    ),
    (
        re.compile(
            r"\bSN\s*[:#-]\s*"
            r"([A-Z0-9][A-Z0-9 ./_-]{2,24})",
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
}


def _strip_htmlish_spacing(value: str) -> str:
    value = value.replace("\r", " ")
    value = value.replace("\n", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _trim_trailing_labels(raw: str) -> str:
    """
    Serialの直後に続く見出し語や文章用の末尾記号を除去する。

    例:
    524436WEIGHT -> 524436
    N056062.     -> N056062
    E556368,     -> E556368
    """

    value = raw.strip().upper()

    # 文章用の末尾記号を除去
    # Serial内部で使われる可能性のある記号は途中なら保持する
    value = value.rstrip(
        ".,:;!?)]}"
    )

    for label in sorted(
        TRAILING_LABELS,
        key=len,
        reverse=True,
    ):
        if value.endswith(label):
            candidate = value[: -len(label)].strip()

            if len(candidate) >= 3:
                value = candidate

                value = value.rstrip(
                    ".,:;!?)]}"
                )

                break

    return value


def _split_candidate(raw: str) -> str:
    """
    Serial候補の後ろに本文が吸い込まれないようにする。
    """

    raw = _strip_htmlish_spacing(raw)

    raw = re.split(
        r"[,;|()\[\]{}]",
        raw,
        maxsplit=1,
    )[0]

    parts = raw.split()

    if not parts:
        return ""

    if len(parts) == 1:
        return _trim_trailing_labels(
            parts[0]
        )

    if all(
        re.fullmatch(
            r"[A-Z0-9./_-]+",
            part,
            re.I,
        )
        for part in parts
    ):
        joined = "".join(parts)

        if len(joined) <= 18:
            return _trim_trailing_labels(
                joined
            )

    return _trim_trailing_labels(
        parts[0]
    )


def _looks_like_serial(
    value: str,
) -> bool:
    """
    Phase 0用の簡易妥当性チェック。
    """

    if not value:
        return False

    value = value.upper()

    if len(value) < 4:
        return False

    if len(value) > 18:
        return False

    # 英字だけはSerialとして扱わない
    if value.isalpha():
        return False

    # 数字だけなら4〜10桁程度
    if value.isdigit():
        return 4 <= len(value) <= 10

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

    return True


def _score_candidate(
    value: str,
    base_confidence: float,
    context: str,
) -> float:
    confidence = base_confidence

    lower_context = (
        context.lower()
    )

    for negative in NEGATIVE_WORDS:
        if negative in lower_context:
            if (
                "serial" in lower_context
                or "s/n" in lower_context
                or "sn:" in lower_context
            ):
                confidence -= 0.05
            else:
                confidence -= 0.35

    # 年式単体をSerialとして扱わない
    if re.fullmatch(
        r"(19|20)\d{2}",
        value,
    ):
        confidence -= 0.50

    if not _looks_like_serial(
        value
    ):
        confidence -= 0.60

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
            raw = match.group(1)

            value = _split_candidate(
                raw
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
                text[start:end]
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
                    confidence=confidence,
                    context=context,
                    reason=reason,
                )
            )

    best: dict[
        str,
        SerialCandidate,
    ] = {}

    for candidate in candidates:
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