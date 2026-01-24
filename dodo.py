"""
Doit build file for Treasury-SF Basis pipeline.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import chartbook

sys.path.insert(1, "./src/")


# Bloomberg Terminal check - runs at module load time
def _check_bloomberg_terminal():
    """Check Bloomberg Terminal availability.

    Supports:
    - SKIP_BLOOMBERG=1 env var to skip pull without prompt (for batch/CI use)
    - BLOOMBERG_TERMINAL_OPEN=1 env var to enable pull without prompt
    - Interactive prompt: Enter=skip, y=pull, n/quit=exit
    """
    # Check environment variables first (for non-interactive use)
    if os.environ.get("SKIP_BLOOMBERG", "").lower() in ("true", "1", "yes"):
        print("SKIP_BLOOMBERG detected, skipping Bloomberg pull...")
        return False  # Skip pull, no prompt
    if os.environ.get("BLOOMBERG_TERMINAL_OPEN", "").lower() in ("true", "1", "yes"):
        print("BLOOMBERG_TERMINAL_OPEN=True detected, enabling Bloomberg pull...")
        return True  # Pull enabled, no prompt

    # Interactive prompt
    response = input("Bloomberg terminal open? [y/N/quit]: ").lower().strip()
    if response in ('n', 'no', 'q', 'quit'):
        raise SystemExit("Exiting.")
    if response in ('y', 'yes'):
        return True  # Pull enabled
    # Default (Enter): skip pull but continue
    print("Skipping Bloomberg pull, using existing data...")
    return False


BLOOMBERG_AVAILABLE = _check_bloomberg_terminal()

BASE_DIR = chartbook.env.get_project_root()
DATA_DIR = BASE_DIR / "_data"
OUTPUT_DIR = BASE_DIR / "_output"
NOTEBOOK_BUILD_DIR = OUTPUT_DIR / "_notebook_build"
OS_TYPE = "nix" if platform.system() != "Windows" else "windows"


def jupyter_execute_notebook(notebook):
    """Execute a notebook and convert to HTML."""
    subprocess.run(
        [
            "jupyter",
            "nbconvert",
            "--execute",
            "--to",
            "html",
            "--output-dir",
            str(OUTPUT_DIR),
            str(notebook),
        ],
        check=True,
    )


def task_config():
    """Create directories for data and output."""

    def create_dirs():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        NOTEBOOK_BUILD_DIR.mkdir(parents=True, exist_ok=True)

    return {
        "actions": [create_dirs],
        "targets": [DATA_DIR, OUTPUT_DIR, NOTEBOOK_BUILD_DIR],
        "verbosity": 2,
    }


def task_pull():
    """Pull Treasury yields and SF rates from Bloomberg."""
    if not BLOOMBERG_AVAILABLE:
        # Skip pull task when Bloomberg is not available
        return {
            "actions": [],
            "verbosity": 2,
            "task_dep": ["config"],
        }
    return {
        "actions": ["python src/pull_bbg_treasury_sf.py"],
        "file_dep": ["src/pull_bbg_treasury_sf.py"],
        "targets": [
            DATA_DIR / "treasury_yields.parquet",
            DATA_DIR / "sf_rates.parquet",
        ],
        "verbosity": 2,
        "task_dep": ["config"],
    }


def task_calc():
    """Calculate Treasury-SF basis."""
    return {
        "actions": ["python src/calc_treasury_sf_basis.py"],
        "file_dep": [
            "src/calc_treasury_sf_basis.py",
            DATA_DIR / "treasury_yields.parquet",
            DATA_DIR / "sf_rates.parquet",
        ],
        "targets": [DATA_DIR / "treasury_sf_basis.parquet"],
        "verbosity": 2,
        "task_dep": ["pull"],
    }


def task_format():
    """Create FTSFR standardized datasets."""
    return {
        "actions": ["python src/create_ftsfr_datasets.py"],
        "file_dep": [
            "src/create_ftsfr_datasets.py",
            DATA_DIR / "treasury_sf_basis.parquet",
        ],
        "targets": [DATA_DIR / "ftsfr_treasury_sf_basis.parquet"],
        "verbosity": 2,
        "task_dep": ["calc"],
    }


def task_run_notebooks():
    """Execute summary notebook and convert to HTML."""
    notebook_py = BASE_DIR / "src" / "summary_treasury_sf_basis_ipynb.py"
    notebook_ipynb = OUTPUT_DIR / "summary_treasury_sf_basis.ipynb"

    def run_notebook():
        # Convert py to ipynb
        subprocess.run(
            ["ipynb-py-convert", str(notebook_py), str(notebook_ipynb)],
            check=True,
        )
        # Execute the notebook
        jupyter_execute_notebook(notebook_ipynb)

    return {
        "actions": [run_notebook],
        "file_dep": [
            notebook_py,
            DATA_DIR / "ftsfr_treasury_sf_basis.parquet",
        ],
        "targets": [
            notebook_ipynb,
            OUTPUT_DIR / "summary_treasury_sf_basis.html",
        ],
        "verbosity": 2,
        "task_dep": ["format"],
    }


def task_generate_pipeline_site():
    """Generate chartbook documentation site."""
    return {
        "actions": ["chartbook build -f"],
        "file_dep": [
            "chartbook.toml",
            OUTPUT_DIR / "summary_treasury_sf_basis.ipynb",
        ],
        "targets": [BASE_DIR / "docs" / "index.html"],
        "verbosity": 2,
        "task_dep": ["run_notebooks"],
    }
