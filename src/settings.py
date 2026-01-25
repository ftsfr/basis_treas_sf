"""
Stub settings module for test compatibility.

Provides config function that maps to chartbook environment.
"""

import chartbook

BASE_DIR = chartbook.env.get_project_root()


def config(key, default=None):
    """Return configuration values for backward compatibility."""
    if key == "DATA_DIR":
        return BASE_DIR / "_data"
    elif key == "OUTPUT_DIR":
        return BASE_DIR / "_output"
    elif key == "START_DATE":
        return "2018-01-01"
    elif key == "END_DATE":
        return "2025-06-01"
    return default
