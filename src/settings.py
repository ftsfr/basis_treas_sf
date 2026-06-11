"""
Settings module for the Treasury cash-futures basis pipeline.

Provides a ``config`` function that maps to the chartbook environment and
environment variables (optionally loaded from a ``.env`` file).
"""

import os
from datetime import date

import chartbook

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_DIR = chartbook.env.get_project_root()


def config(key, default=None):
    """Return configuration values for the pipeline."""
    if key == "BASE_DIR":
        return BASE_DIR
    elif key == "DATA_DIR":
        return BASE_DIR / "_data"
    elif key == "MANUAL_DATA_DIR":
        return BASE_DIR / "data_manual"
    elif key == "OUTPUT_DIR":
        return BASE_DIR / "_output"
    elif key == "START_DATE":
        return os.environ.get("START_DATE", "2004-01-01")
    elif key == "END_DATE":
        return os.environ.get("END_DATE", str(date.today()))
    elif key == "WRDS_USERNAME":
        return os.environ.get("WRDS_USERNAME", default)
    return default


if __name__ == "__main__":
    config("DATA_DIR").mkdir(parents=True, exist_ok=True)
    config("OUTPUT_DIR").mkdir(parents=True, exist_ok=True)
