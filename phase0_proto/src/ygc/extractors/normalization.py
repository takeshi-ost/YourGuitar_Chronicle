from __future__ import annotations
import re
KNOWN_MAKERS={'fender usa':'fender','fender musical instruments':'fender','fender':'fender','gibson':'gibson','gretsch':'gretsch','martin':'martin','c. f. martin':'martin','rickenbacker':'rickenbacker'}
def normalize_space(value):
    if value is None: return None
    value=re.sub(r"\s+"," ",value.strip()); return value or None
def normalize_manufacturer(value: str) -> str:
    v=normalize_space(value)
    if not v: return ''
    return KNOWN_MAKERS.get(v.lower(),v.lower())
def normalize_model(value):
    v=normalize_space(value); return v.lower() if v else None
def normalize_serial(value):
    if not value: return None
    v=value.strip().upper()
    v=re.sub(r"^(SERIAL(?:\s+NUMBER)?|S/N|SN)\s*[:#-]?\s*","",v,flags=re.I)
    v=re.sub(r"[\s./]+","",v)
    return v or None
