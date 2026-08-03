from pathlib import Path
import os

APP_DIR = Path(os.getenv("TOP40_APP_DIR", "/opt/top40-archiver"))
DATA_DIR = Path(os.getenv("TOP40_DATA_DIR", "/var/lib/top40-archiver"))
DB_PATH = Path(os.getenv("TOP40_DB_PATH", DATA_DIR / "top40.sqlite3"))
DEFAULT_DOWNLOAD_DIR = os.getenv("TOP40_DOWNLOAD_DIR", str(DATA_DIR / "downloads"))
TOP40_BASE_URL = "https://www.top40.nl/top40"
