from __future__ import annotations
import os
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("YGC_DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = Path(os.getenv("YGC_DB_PATH", DATA_DIR / "chronicle.db"))
LOG_DIR = Path(os.getenv("YGC_LOG_DIR", PROJECT_ROOT / "logs"))
REVERB_API_TOKEN = os.getenv("REVERB_API_TOKEN", "").strip()
REVERB_API_BASE = os.getenv("REVERB_API_BASE", "https://api.reverb.com/api").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("YGC_REQUEST_TIMEOUT", "20"))
REQUEST_DELAY = float(os.getenv("YGC_REQUEST_DELAY", "1.0"))
SERIAL_CONFIDENCE_THRESHOLD = float(os.getenv("YGC_SERIAL_CONFIDENCE_THRESHOLD", "0.70"))
