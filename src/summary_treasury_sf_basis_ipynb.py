# %%
"""
# Treasury-Secured Financing Basis Summary

Treasury-SF basis measuring the spread between Treasury yields and SOFR-based secured financing rates.
"""

# %%
import sys
sys.path.insert(0, "./src")

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

import chartbook

BASE_DIR = chartbook.env.get_project_root()
DATA_DIR = BASE_DIR / "_data"

# %%
"""
## Methodology

The Treasury-SF basis is calculated as:

$$
\\text{Basis} = (\\text{Treasury Yield} - \\text{SOFR OIS Rate}) \\times 100
$$

Results are expressed in basis points.

### Interpretation

- **Basis > 0**: Treasuries yield more than SOFR-based financing
- **Basis < 0**: SOFR-based financing yields more than Treasuries
- **Basis = 0**: No spread

### Data Sources

- Bloomberg Treasury constant maturity yields (USGG series)
- Bloomberg SOFR OIS swap rates (USOSFR series)
"""

# %%
"""
## Data Overview
"""

# %%
df = pd.read_parquet(DATA_DIR / "ftsfr_treasury_sf_basis.parquet")
print(f"Shape: {df.shape}")
print(f"Columns: {df.columns.tolist()}")
print(f"\nDate range: {df['ds'].min()} to {df['ds'].max()}")
print(f"Number of series: {df['unique_id'].nunique()}")

# %%
print("\nSeries:")
for series in sorted(df['unique_id'].unique()):
    print(f"  {series}")

# %%
"""
### Summary Statistics
"""

# %%
basis_wide = df.pivot(index='ds', columns='unique_id', values='y')
basis_stats = basis_wide.describe().T
basis_stats['skewness'] = basis_wide.skew()
basis_stats['kurtosis'] = basis_wide.kurtosis()
print(basis_stats[['mean', 'std', 'min', 'max', 'skewness', 'kurtosis']].round(2).to_string())

# %%
"""
### Treasury-SF Basis Time Series
"""

# %%
fig, ax = plt.subplots(figsize=(14, 8))

for col in basis_wide.columns:
    ax.plot(basis_wide.index, basis_wide[col], label=col, alpha=0.8, linewidth=1)

ax.axhline(y=0, color='black', linestyle='--', alpha=0.5)
ax.set_xlabel('Date')
ax.set_ylabel('Basis (bps)')
ax.set_title('Treasury-SF Basis (Treasury Yield - SOFR OIS Rate)')
ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.1), ncol=5)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(DATA_DIR.parent / "_output" / "treasury_sf_basis.png", dpi=150, bbox_inches='tight')
plt.show()

# %%
"""
### Term Structure of Treasury-SF Basis
"""

# %%
# Plot most recent term structure
fig, ax = plt.subplots(figsize=(10, 6))

# Get most recent values
latest = basis_wide.iloc[-1]
tenors = [2, 5, 10, 20, 30]
values = [latest.get(f'Treasury_SF_{t}Y', None) for t in tenors]

ax.plot(tenors, values, 'o-', linewidth=2, markersize=8)
ax.axhline(y=0, color='black', linestyle='--', alpha=0.5)
ax.set_xlabel('Tenor (Years)')
ax.set_ylabel('Basis (bps)')
ax.set_title(f'Treasury-SF Basis Term Structure ({basis_wide.index[-1].strftime("%Y-%m-%d")})')
ax.set_xticks(tenors)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(DATA_DIR.parent / "_output" / "treasury_sf_basis_term.png", dpi=150, bbox_inches='tight')
plt.show()

# %%
"""
### Correlation Matrix
"""

# %%
fig, ax = plt.subplots(figsize=(10, 8))
corr = basis_wide.corr()
sns.heatmap(corr, annot=True, fmt='.2f', cmap='RdBu_r', center=0, ax=ax)
ax.set_title('Treasury-SF Basis Correlations')
plt.tight_layout()
plt.savefig(DATA_DIR.parent / "_output" / "treasury_sf_basis_correlation.png", dpi=150, bbox_inches='tight')
plt.show()

# %%
"""
## Data Definitions

### Treasury-SF Basis (ftsfr_treasury_sf_basis)

| Variable | Description |
|----------|-------------|
| unique_id | Tenor identifier (e.g., Treasury_SF_2Y, Treasury_SF_10Y) |
| ds | Date |
| y | Basis spread in basis points |

### Series

| Code | Description |
|------|-------------|
| Treasury_SF_2Y | 2-Year Treasury-SF basis |
| Treasury_SF_5Y | 5-Year Treasury-SF basis |
| Treasury_SF_10Y | 10-Year Treasury-SF basis |
| Treasury_SF_20Y | 20-Year Treasury-SF basis |
| Treasury_SF_30Y | 30-Year Treasury-SF basis |
"""
