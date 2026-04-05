from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
