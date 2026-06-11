# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.18.1
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Treasury Cash-Futures Basis Summary
#
# The Treasury cash-futures basis trade buys a deliverable Treasury (the
# cheapest-to-deliver, or CTD, bond), finances it in repo, and sells the
# corresponding Treasury futures contract, locking in the futures invoice
# price at delivery. The return earned by carrying the bond to delivery is
# the **implied repo rate (IRR)**. The arbitrage spread compares this
# implied repo to a maturity-matched OIS rate:
#
# $$\text{Basis} = \text{IRR} - \text{OIS} \quad \text{(bps)}$$
#
# This pipeline computes the basis two ways:
#
# 1. **Delivery-adjusted (corrected) method** — computes the IRR from CTD
#    bond prices (CRSP) and futures prices, *choosing the delivery date
#    optimally* within the delivery month, the way the short who owns the
#    timing option would. Implemented following George Lord and Max Zhalilo
#    (https://github.com/maxz073/p10_Siriwardane_et_al_2026).
# 2. **Bloomberg method** — uses Bloomberg's `FUT_IMPLIED_REPO_RT`, which
#    assumes a fixed delivery date. When carry is negative (financing cost
#    exceeds coupon income), the short prefers to deliver *early*, and the
#    fixed-date assumption understates the implied repo.

# %%
import matplotlib.pyplot as plt
import pandas as pd

from settings import config

DATA_DIR = config("DATA_DIR")
OUTPUT_DIR = config("OUTPUT_DIR")

# %% [markdown]
# ## Data Overview

# %%
df_adj = pd.read_parquet(DATA_DIR / "ftsfr_treasury_sf_basis.parquet")
df_bbg = pd.read_parquet(DATA_DIR / "ftsfr_treasury_sf_basis_bbg.parquet")

print("Delivery-adjusted method:")
print(f"  Records: {len(df_adj):,}")
print(f"  Date range: {df_adj['ds'].min().date()} to {df_adj['ds'].max().date()}")
print(f"  Series: {sorted(df_adj['unique_id'].unique())}")
print("Bloomberg method:")
print(f"  Records: {len(df_bbg):,}")
print(f"  Date range: {df_bbg['ds'].min().date()} to {df_bbg['ds'].max().date()}")

# %%
adj_wide = df_adj.pivot(index="ds", columns="unique_id", values="y")
bbg_wide = df_bbg.pivot(index="ds", columns="unique_id", values="y")

# %% [markdown]
# ### Summary Statistics (bps)

# %%
stats = pd.concat(
    {
        "Delivery-adjusted": adj_wide.describe().T[["count", "mean", "std", "min", "max"]],
        "Bloomberg": bbg_wide.describe().T[["count", "mean", "std", "min", "max"]],
    },
    axis=1,
)
stats.round(2)

# %% [markdown]
# The delivery-adjusted basis is systematically *above* the Bloomberg-method
# basis. This is the delivery option at work: the corrected IRR maximizes
# over candidate delivery dates, so it is weakly greater than an IRR computed
# at any fixed delivery date.

# %%
diff = (adj_wide - bbg_wide).dropna(how="all")
diff.describe().T[["count", "mean", "std", "min", "max"]].round(2)

# %% [markdown]
# ### Basis Time Series: Both Methods by Tenor

# %%
tenors = ["2Y", "5Y", "10Y", "20Y", "30Y"]
fig, axes = plt.subplots(len(tenors), 1, figsize=(14, 18), sharex=True)
for ax, tenor in zip(axes, tenors):
    col = f"Treasury_SF_{tenor}"
    if col in adj_wide.columns:
        ax.plot(adj_wide.index, adj_wide[col], label="Delivery-adjusted",
                color="C0", linewidth=0.9)
    if col in bbg_wide.columns:
        ax.plot(bbg_wide.index, bbg_wide[col], label="Bloomberg implied repo",
                color="C3", linewidth=0.9, alpha=0.7)
    ax.axhline(0, color="black", linestyle="--", alpha=0.5)
    ax.set_title(f"{tenor} tenor")
    ax.set_ylabel("Basis (bps)")
    ax.legend(loc="lower left")
    ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "treasury_sf_basis_comparison.png", dpi=150,
            bbox_inches="tight")
plt.show()

# %% [markdown]
# ### Optimal Holding Period
#
# The corrected method records the holding period implied by the winning
# delivery date. Sawtooth jumps between the start and the end of the
# delivery window are the delivery option switching between early delivery
# (negative carry) and late delivery (positive carry).

# %%
holding = pd.read_parquet(DATA_DIR / "holding_period_days.parquet").set_index("Date")
fig, ax = plt.subplots(figsize=(14, 5))
for tenor in tenors:
    if tenor in holding.columns:
        ax.plot(holding.index, holding[tenor], label=tenor, linewidth=0.8)
ax.set_ylabel("Holding period (days)")
ax.set_title("Optimal Holding Period by Tenor (settlement to optimal delivery)")
ax.legend(title="Tenor")
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Method Difference: Delivery-Adjusted Minus Bloomberg

# %%
fig, ax = plt.subplots(figsize=(14, 5))
for tenor in tenors:
    col = f"Treasury_SF_{tenor}"
    if col in diff.columns:
        ax.plot(diff.index, diff[col].rolling(21).mean(), label=tenor, linewidth=0.9)
ax.axhline(0, color="black", linestyle="--", alpha=0.5)
ax.set_ylabel("Difference (bps, 21-day MA)")
ax.set_title("Delivery-Adjusted Basis Minus Bloomberg-Method Basis")
ax.legend(title="Tenor")
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Data Definitions
#
# ### ftsfr_treasury_sf_basis / ftsfr_treasury_sf_basis_bbg
#
# | Variable | Description |
# |----------|-------------|
# | unique_id | Tenor identifier (e.g., Treasury_SF_2Y, Treasury_SF_10Y) |
# | ds | Date |
# | y | Basis spread in basis points |
#
# ### Series
#
# | Code | Futures contract | Description |
# |------|------------------|-------------|
# | Treasury_SF_2Y | TU (2Y note) | 2-Year cash-futures basis |
# | Treasury_SF_5Y | FV (5Y note) | 5-Year cash-futures basis |
# | Treasury_SF_10Y | TY (10Y note) | 10-Year cash-futures basis |
# | Treasury_SF_20Y | US (classic bond) | 20-Year cash-futures basis |
# | Treasury_SF_30Y | WN (Ultra Bond) | 30-Year cash-futures basis |

# %%
