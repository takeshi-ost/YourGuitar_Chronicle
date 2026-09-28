"""Conservative extraction of explicitly labeled guitar specifications."""

import re
from html import unescape


FIELDS = {
    "body": "body", "body material": "body", "bridge": "bridge",
    "fingerboard": "fingerboard", "fretboard": "fingerboard",
    "frets": "frets", "neck": "neck", "neck material": "neck",
    "nut": "nut", "pickups": "pickups", "pickup": "pickups",
    "pickguard": "pickguard", "potentiometers": "potentiometers",
    "pots": "potentiometers", "tuners": "tuners", "tuning machines": "tuners",
    "wiring": "wiring", "weight": "weight", "finish": "finish",
}


def extract_specifications(detail: dict) -> dict[str, str]:
    """Accept explicit fields and labeled description lines; never infer from prose."""
    result: dict[str, str] = {}

    def add(label: str, value: object) -> None:
        field = FIELDS.get(str(label).strip().lower())
        if field is None or not isinstance(value, (str, int, float)):
            return
        cleaned = re.sub(r"\s+", " ", unescape(str(value))).strip(" :;,-")
        if (cleaned and len(cleaned) <= 500 and cleaned.lower() not in
                {"unknown", "n/a", "none", "not specified", "other"}):
            result.setdefault(field, cleaned)

    for key in FIELDS:
        if key in detail:
            add(key, detail[key])
    for container_key in ("specifications", "specs", "attributes"):
        container = detail.get(container_key)
        if isinstance(container, dict):
            for key, value in container.items():
                add(key, value)
        elif isinstance(container, list):
            for item in container:
                if isinstance(item, dict):
                    add(item.get("name") or item.get("key") or "", item.get("value"))

    description = detail.get("description")
    if isinstance(description, str):
        lines = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li)>", "\n", description)
        lines = re.sub(r"<[^>]+>", "", lines)
        for line in unescape(lines).splitlines():
            match = re.fullmatch(r"\s*([\w ]{2,32})\s*:\s*(.{1,500}?)\s*", line)
            if match:
                add(match.group(1), match.group(2))
    return result
