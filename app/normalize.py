import re, unicodedata
from pathlib import Path

FEATURE_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+", re.I)

def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())

def safe_filename(value: str, max_len: int = 180) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = value[:max_len].rstrip(" .")
    return value or "onbekend"
