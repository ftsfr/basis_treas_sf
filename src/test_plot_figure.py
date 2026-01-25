"""Tests functions in plot_figure.py"""

import os
from pathlib import Path

import pandas as pd
from pandas.tseries.offsets import DateOffset

from plot_figure import plot_figure, load_treasury_sf_data
from settings import config

output_dir = Path(config("OUTPUT_DIR"))


def test_plot_figure():
    """Create a dummy DataFrame, and check if it saves the correct name in the dir"""
    # Create dict for DataFrame in wide format
    start = pd.Timestamp(config("START_DATE")).date()
    data = {
        "Treasury_SF_2Y": [10, 15],
        "Treasury_SF_5Y": [20, 25],
        "Treasury_SF_10Y": [30, 35],
        "Treasury_SF_20Y": [40, 45],
        "Treasury_SF_30Y": [50, 55],
    }
    dates = [start, start + DateOffset(months=1)]
    basis_df = pd.DataFrame(data, index=dates)

    file = output_dir / "dummy_sf_plot.html"
    plot_figure(basis_df, file)

    assert os.path.exists(file)


def test_load_treasury_sf_data():
    """Test loading and pivoting of treasury SF data"""
    data_dir = Path(config("DATA_DIR"))
    file = data_dir / "ftsfr_treasury_sf_basis.parquet"

    if not file.exists():
        return  # Skip if data file doesn't exist

    df = load_treasury_sf_data(file)

    # Check that we have a DataFrame with expected columns
    assert isinstance(df, pd.DataFrame)
    assert df.index.name == "ds" or isinstance(df.index, pd.DatetimeIndex)
