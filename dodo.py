"""
Doit build file for the Treasury cash-futures basis pipeline.

Pipeline stages:
1. pull_bbg: Bloomberg futures + OIS data (requires a Bloomberg Terminal;
   skipped when unavailable, in which case cached files in _data are used)
2. pull_crsp: CRSP daily Treasury data for CTD bonds (requires WRDS)
3. format_bbg: combine per-tenor futures files; build last-day mapping
4. calc_bbg: basis using Bloomberg's implied repo (old method)
5. calc_adj: basis using delivery-timing-adjusted implied repo (corrected
   method, following Lord and Zhalilo)
6. format_ftsfr: FTSFR standardized long-format datasets (both methods)
7. generate_charts, run_notebooks, generate_pipeline_site
"""

import os
import platform
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
    if os.environ.get("SKIP_BLOOMBERG", "").lower() in ("true", "1", "yes"):
        print("SKIP_BLOOMBERG detected, skipping Bloomberg pull...")
        return False
    if os.environ.get("BLOOMBERG_TERMINAL_OPEN", "").lower() in ("true", "1", "yes"):
        print("BLOOMBERG_TERMINAL_OPEN=True detected, enabling Bloomberg pull...")
        return True

    response = input("Bloomberg terminal open? [y/N/quit]: ").lower().strip()
    if response in ("n", "no", "q", "quit"):
        raise SystemExit("Exiting.")
    if response in ("y", "yes"):
        return True
    print("Skipping Bloomberg pull, using existing data...")
    return False


BLOOMBERG_AVAILABLE = _check_bloomberg_terminal()

BASE_DIR = chartbook.env.get_project_root()
DATA_DIR = BASE_DIR / "_data"
OUTPUT_DIR = BASE_DIR / "_output"
OS_TYPE = "nix" if platform.system() != "Windows" else "windows"

TENORS = [2, 5, 10, 20, 30]
FUTURES_FILES = [
    DATA_DIR / f"treasury_{tenor}y_{leg}.parquet" for tenor in TENORS for leg in (1, 2)
]


## Helpers for handling Jupyter Notebook tasks
os.environ["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"


# fmt: off
def jupyter_execute_notebook(notebook_path):
    return f"jupyter nbconvert --execute --to notebook --ClearMetadataPreprocessor.enabled=True --inplace {notebook_path}"
def jupyter_to_html(notebook_path, output_dir=OUTPUT_DIR):
    return f"jupyter nbconvert --to html --output-dir={output_dir} {notebook_path}"
# fmt: on


def mv(from_path, to_path):
    from_path = Path(from_path)
    to_path = Path(to_path)
    to_path.mkdir(parents=True, exist_ok=True)
    if OS_TYPE == "nix":
        command = f"mv {from_path} {to_path}"
    else:
        command = f"move {from_path} {to_path}"
    return command


def task_config():
    """Create directories for data and output."""

    def create_dirs():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    return {
        "actions": [create_dirs],
        "targets": [DATA_DIR, OUTPUT_DIR],
        "verbosity": 2,
    }


def task_pull_bbg():
    """Pull Treasury futures and OIS data from Bloomberg."""
    if not BLOOMBERG_AVAILABLE:
        # Skip pull task when Bloomberg is not available; cached files in
        # _data (if present) are used by downstream tasks
        return {
            "actions": [],
            "verbosity": 2,
            "task_dep": ["config"],
        }
    return {
        "actions": ["python src/pull_bbg_basis_treas_sf.py"],
        "file_dep": ["src/pull_bbg_basis_treas_sf.py"],
        "targets": [DATA_DIR / "ois.parquet", *FUTURES_FILES],
        "verbosity": 2,
        "task_dep": ["config"],
    }


def task_pull_crsp():
    """Pull CRSP daily Treasury data for CTD bonds from WRDS."""
    return {
        "actions": ["python src/pull_crsp_treasury.py"],
        "file_dep": [
            "src/pull_crsp_treasury.py",
            *[f for f in FUTURES_FILES if "y_2" in f.name],
        ],
        "targets": [DATA_DIR / "crsp_treasury_ctd.parquet"],
        "verbosity": 2,
        "task_dep": ["pull_bbg"],
    }


def task_format_bbg():
    """Combine per-tenor futures files and build the last-day mapping."""
    return {
        "actions": ["python src/format_bbg_basis_treas_sf.py"],
        "file_dep": ["src/format_bbg_basis_treas_sf.py", *FUTURES_FILES],
        "targets": [
            DATA_DIR / "treasury_df.parquet",
            DATA_DIR / "last_day.parquet",
        ],
        "verbosity": 2,
        "task_dep": ["pull_bbg"],
    }


def task_calc_bbg():
    """Calculate the basis using Bloomberg's implied repo (old method)."""
    return {
        "actions": ["python src/calc_basis_bloomberg.py"],
        "file_dep": [
            "src/calc_basis_bloomberg.py",
            "src/format_bbg_basis_treas_sf.py",
            DATA_DIR / "treasury_df.parquet",
            DATA_DIR / "last_day.parquet",
            DATA_DIR / "ois.parquet",
        ],
        "targets": [DATA_DIR / "basis_treas_sf_bbg.parquet"],
        "verbosity": 2,
        "task_dep": ["format_bbg"],
    }


def task_calc_adj():
    """Calculate the basis using delivery-adjusted implied repo (corrected)."""
    return {
        "actions": ["python src/calc_basis_delivery_adjusted.py"],
        "file_dep": [
            "src/calc_basis_delivery_adjusted.py",
            "src/pull_crsp_treasury.py",
            DATA_DIR / "crsp_treasury_ctd.parquet",
            DATA_DIR / "ois.parquet",
            *[f for f in FUTURES_FILES if "y_2" in f.name],
        ],
        "targets": [
            DATA_DIR / "basis_treas_sf_adj.parquet",
            DATA_DIR / "implied_repo_delivery_adjusted.parquet",
            DATA_DIR / "holding_period_days.parquet",
            DATA_DIR / "ois_at_holding_period.parquet",
        ],
        "verbosity": 2,
        "task_dep": ["pull_crsp"],
    }


def task_format_ftsfr():
    """Create FTSFR standardized datasets (both methods)."""
    return {
        "actions": ["python src/create_ftsfr_datasets.py"],
        "file_dep": [
            "src/create_ftsfr_datasets.py",
            DATA_DIR / "basis_treas_sf_adj.parquet",
            DATA_DIR / "basis_treas_sf_bbg.parquet",
        ],
        "targets": [
            DATA_DIR / "ftsfr_treasury_sf_basis.parquet",
            DATA_DIR / "ftsfr_treasury_sf_basis_bbg.parquet",
        ],
        "verbosity": 2,
        "task_dep": ["calc_bbg", "calc_adj"],
    }


def task_generate_charts():
    """Generate charts for the Treasury cash-futures basis."""
    return {
        "actions": ["python src/plot_figures.py"],
        "file_dep": [
            "src/plot_figures.py",
            DATA_DIR / "ftsfr_treasury_sf_basis.parquet",
            DATA_DIR / "ftsfr_treasury_sf_basis_bbg.parquet",
        ],
        "targets": [
            OUTPUT_DIR / "treasury_sf_basis.html",
            OUTPUT_DIR / "treasury_sf_basis_bbg.html",
            OUTPUT_DIR / "treasury_sf_basis_comparison.html",
        ],
        "verbosity": 2,
        "task_dep": ["format_ftsfr"],
    }


notebook_tasks = {
    "summary_treasury_sf_basis_ipynb": {
        "path": "./src/summary_treasury_sf_basis_ipynb.py",
        "file_dep": [
            DATA_DIR / "ftsfr_treasury_sf_basis.parquet",
            DATA_DIR / "ftsfr_treasury_sf_basis_bbg.parquet",
            DATA_DIR / "implied_repo_delivery_adjusted.parquet",
            DATA_DIR / "holding_period_days.parquet",
        ],
        "targets": [],
    },
}
notebook_files = []
for notebook in notebook_tasks.keys():
    pyfile_path = Path(notebook_tasks[notebook]["path"])
    notebook_files.append(pyfile_path)


def task_run_notebooks():
    """Execute summary notebook and convert to HTML."""
    for notebook in notebook_tasks.keys():
        pyfile_path = Path(notebook_tasks[notebook]["path"])
        notebook_path = pyfile_path.with_suffix(".ipynb")
        yield {
            "name": notebook,
            "actions": [
                f"jupytext --to notebook --output {notebook_path} {pyfile_path}",
                jupyter_execute_notebook(notebook_path),
                jupyter_to_html(notebook_path),
                mv(notebook_path, OUTPUT_DIR),
            ],
            "file_dep": [
                pyfile_path,
                *notebook_tasks[notebook]["file_dep"],
            ],
            "targets": [
                OUTPUT_DIR / f"{notebook}.html",
                *notebook_tasks[notebook]["targets"],
            ],
            "clean": True,
            "task_dep": ["format_ftsfr"],
        }


def task_generate_pipeline_site():
    """Generate chartbook documentation site."""
    return {
        "actions": ["chartbook build -f"],
        "file_dep": [
            "chartbook.toml",
            "README.md",
            *notebook_files,
            OUTPUT_DIR / "treasury_sf_basis.html",
            OUTPUT_DIR / "treasury_sf_basis_bbg.html",
            OUTPUT_DIR / "treasury_sf_basis_comparison.html",
        ],
        "targets": [BASE_DIR / "docs" / "index.html"],
        "verbosity": 2,
        "task_dep": ["run_notebooks", "generate_charts"],
    }
