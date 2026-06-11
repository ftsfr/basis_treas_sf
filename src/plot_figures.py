"""
Plot Treasury cash-futures basis figures (Plotly HTML).

Outputs (saved under OUTPUT_DIR):
- ``treasury_sf_basis.html``: delivery-adjusted basis by tenor
- ``treasury_sf_basis_bbg.html``: Bloomberg-method basis by tenor
- ``treasury_sf_basis_comparison.html``: both methods overlaid, one subplot
  per tenor
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from settings import config

DATA_DIR = Path(config("DATA_DIR"))
OUTPUT_DIR = Path(config("OUTPUT_DIR"))

TENOR_ORDER = ["2Y", "5Y", "10Y", "20Y", "30Y"]


def load_ftsfr_wide(file_path: Path) -> pd.DataFrame:
    """Load an FTSFR long-format parquet and pivot to wide (Date x series)."""
    df = pd.read_parquet(file_path)
    df_wide = df.pivot(index="ds", columns="unique_id", values="y")
    df_wide.index = pd.to_datetime(df_wide.index)
    return df_wide.sort_index()


def _tenor_columns(df_wide: pd.DataFrame) -> list[str]:
    return [
        f"Treasury_SF_{t}" for t in TENOR_ORDER if f"Treasury_SF_{t}" in df_wide.columns
    ]


def plot_basis_by_tenor(df_wide: pd.DataFrame, title: str, save_path: Path) -> go.Figure:
    """One line per tenor."""
    fig = go.Figure()
    for col in _tenor_columns(df_wide):
        s = df_wide[col].dropna()
        if s.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=s.index, y=s.values, mode="lines",
                name=col.replace("Treasury_SF_", ""),
            )
        )
    fig.add_hline(y=0.0, line_dash="dash", line_color="black")
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Basis (bps)",
        template="plotly_white",
        hovermode="x unified",
        legend_title="Tenor",
    )
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(save_path)
    return fig


def plot_method_comparison(
    df_adj: pd.DataFrame, df_bbg: pd.DataFrame, save_path: Path
) -> go.Figure:
    """Overlay the two methods, one subplot per tenor."""
    tenors = [t for t in TENOR_ORDER if f"Treasury_SF_{t}" in df_adj.columns]
    fig = make_subplots(
        rows=len(tenors), cols=1, shared_xaxes=True,
        subplot_titles=[f"{t} tenor" for t in tenors],
        vertical_spacing=0.04,
    )
    for i, tenor in enumerate(tenors, start=1):
        col = f"Treasury_SF_{tenor}"
        s_adj = df_adj[col].dropna() if col in df_adj.columns else pd.Series(dtype=float)
        s_bbg = df_bbg[col].dropna() if col in df_bbg.columns else pd.Series(dtype=float)
        fig.add_trace(
            go.Scatter(
                x=s_adj.index, y=s_adj.values, mode="lines",
                name="Delivery-adjusted", legendgroup="adj",
                line=dict(color="#1f77b4"), showlegend=(i == 1),
            ),
            row=i, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=s_bbg.index, y=s_bbg.values, mode="lines",
                name="Bloomberg implied repo", legendgroup="bbg",
                line=dict(color="#d62728"), showlegend=(i == 1),
            ),
            row=i, col=1,
        )
        fig.add_hline(y=0.0, line_dash="dash", line_color="black", row=i, col=1)
    fig.update_layout(
        title="Treasury Cash-Futures Basis: Delivery-Adjusted vs Bloomberg Method",
        template="plotly_white",
        height=250 * len(tenors),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="bps")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(save_path)
    return fig


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df_adj = load_ftsfr_wide(DATA_DIR / "ftsfr_treasury_sf_basis.parquet")
    df_bbg = load_ftsfr_wide(DATA_DIR / "ftsfr_treasury_sf_basis_bbg.parquet")

    plot_basis_by_tenor(
        df_adj,
        "Treasury Cash-Futures Basis (Delivery-Adjusted Implied Repo - OIS)",
        OUTPUT_DIR / "treasury_sf_basis.html",
    )
    plot_basis_by_tenor(
        df_bbg,
        "Treasury Cash-Futures Basis (Bloomberg Implied Repo - OIS)",
        OUTPUT_DIR / "treasury_sf_basis_bbg.html",
    )
    plot_method_comparison(
        df_adj, df_bbg, OUTPUT_DIR / "treasury_sf_basis_comparison.html"
    )
    print(">> Saved treasury_sf_basis.html, treasury_sf_basis_bbg.html, "
          "treasury_sf_basis_comparison.html")


if __name__ == "__main__":
    main()
