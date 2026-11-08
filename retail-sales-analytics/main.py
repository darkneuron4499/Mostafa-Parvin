"""
Retail Sales Analytics
======================
End-to-end data analysis project using NumPy, Pandas and Matplotlib.

Pipeline:
    1. Generate a realistic synthetic sales dataset      (NumPy)
    2. Clean the data and engineer new features          (Pandas)
    3. Analyze: KPIs, trends, rankings, correlations     (Pandas + NumPy)
    4. Forecast the next months with a linear trend      (NumPy)
    5. Visualize everything in a dashboard + charts      (Matplotlib)

Run:
    python main.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # render to files, no GUI window needed
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SEED = 42
N_ROWS = 5000
OUTPUT_DIR = Path("outputs")

PRODUCTS = {
    # name: (category, base price)
    "Laptop": ("Electronics", 900),
    "Phone": ("Electronics", 650),
    "Headphones": ("Electronics", 120),
    "T-Shirt": ("Clothing", 25),
    "Jeans": ("Clothing", 60),
    "Sneakers": ("Clothing", 90),
    "Coffee Beans": ("Grocery", 15),
    "Olive Oil": ("Grocery", 12),
    "Desk Lamp": ("Home", 35),
    "Chair": ("Home", 140),
}
REGIONS = ["North", "South", "East", "West"]


# ----------------------------------------------------------------------------
# 1. Data generation
# ----------------------------------------------------------------------------
def generate_data(n_rows: int = N_ROWS, seed: int = SEED) -> pd.DataFrame:
    """Create a synthetic sales dataset with trend, seasonality and noise."""
    rng = np.random.default_rng(seed)

    dates = pd.to_datetime("2024-01-01") + pd.to_timedelta(
        rng.integers(0, 730, n_rows), unit="D"
    )
    names = rng.choice(list(PRODUCTS), n_rows)
    categories = [PRODUCTS[p][0] for p in names]
    base_prices = np.array([PRODUCTS[p][1] for p in names])

    # Price varies a little (discounts / price changes)
    unit_price = base_prices * rng.normal(1.0, 0.08, n_rows)

    # More sales near the end of the year (seasonality) + slow growth (trend)
    day_of_year = dates.dayofyear.to_numpy()
    seasonality = 1 + 0.35 * np.sin((day_of_year - 250) / 365 * 2 * np.pi)
    trend = 1 + 0.0006 * (dates - dates.min()).days.to_numpy()
    quantity = np.maximum(1, rng.poisson(2 * seasonality * trend))

    df = pd.DataFrame(
        {
            "date": dates,
            "product": names,
            "category": categories,
            "region": rng.choice(REGIONS, n_rows),
            "unit_price": unit_price.round(2),
            "quantity": quantity,
        }
    )

    # Introduce a few missing values / duplicates so cleaning is meaningful
    df.loc[rng.choice(n_rows, 40, replace=False), "region"] = np.nan
    df.loc[rng.choice(n_rows, 25, replace=False), "unit_price"] = np.nan
    df = pd.concat([df, df.sample(30, random_state=seed)], ignore_index=True)
    return df


# ----------------------------------------------------------------------------
# 2. Cleaning & feature engineering
# ----------------------------------------------------------------------------
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop_duplicates().copy()
    df["region"] = df["region"].fillna("Unknown")
    # Fill missing prices with the median price of the same product
    df["unit_price"] = df["unit_price"].fillna(
        df.groupby("product")["unit_price"].transform("median")
    )
    df["revenue"] = (df["unit_price"] * df["quantity"]).round(2)
    df["month"] = df["date"].dt.to_period("M")
    df["weekday"] = df["date"].dt.day_name()
    return df.sort_values("date").reset_index(drop=True)


# ----------------------------------------------------------------------------
# 3. Analysis
# ----------------------------------------------------------------------------
def analyze(df: pd.DataFrame) -> dict:
    monthly = df.groupby("month")["revenue"].sum()
    return {
        "total_revenue": df["revenue"].sum(),
        "orders": len(df),
        "avg_order_value": df["revenue"].mean(),
        "monthly": monthly,
        "monthly_ma3": monthly.rolling(3).mean(),
        "by_category": df.groupby("category")["revenue"].sum().sort_values(),
        "top_products": df.groupby("product")["revenue"].sum().nlargest(5),
        "by_region": df.groupby("region")["revenue"].sum().sort_values(),
        "by_weekday": df.groupby("weekday")["revenue"]
        .sum()
        .reindex(
            ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]
        ),
        "corr": df[["unit_price", "quantity", "revenue"]].corr(),
    }


# ----------------------------------------------------------------------------
# 4. Forecast (linear regression with NumPy)
# ----------------------------------------------------------------------------
def forecast(monthly: pd.Series, periods: int = 3) -> pd.Series:
    x = np.arange(len(monthly))
    slope, intercept = np.polyfit(x, monthly.to_numpy(), deg=1)
    future_x = np.arange(len(monthly), len(monthly) + periods)
    future_idx = pd.period_range(monthly.index[-1] + 1, periods=periods, freq="M")
    return pd.Series(slope * future_x + intercept, index=future_idx)


# ----------------------------------------------------------------------------
# 5. Visualization
# ----------------------------------------------------------------------------
def make_dashboard(res: dict, pred: pd.Series, path: Path) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("Retail Sales Dashboard", fontsize=20, fontweight="bold")

    # Monthly revenue + moving average + forecast
    ax = axes[0, 0]
    m = res["monthly"]
    ax.plot(m.index.to_timestamp(), m.values, marker="o", label="Revenue")
    ax.plot(m.index.to_timestamp(), res["monthly_ma3"].values,
            linestyle="--", label="3-month avg")
    ax.plot(pred.index.to_timestamp(), pred.values, marker="x",
            color="red", label="Forecast")
    ax.set_title("Monthly Revenue & Forecast")
    ax.legend()
    ax.tick_params(axis="x", rotation=45)

    # Category share
    ax = axes[0, 1]
    wedges, _ = ax.pie(res["by_category"], startangle=90)
    shares = res["by_category"] / res["by_category"].sum() * 100
    ax.legend(wedges,
              [f"{c} ({s:.1f}%)" for c, s in shares.items()],
              loc="center left", bbox_to_anchor=(0.9, 0.5), frameon=False)
    ax.set_title("Revenue Share by Category")

    # Top products
    ax = axes[0, 2]
    res["top_products"].sort_values().plot.barh(ax=ax, color="teal")
    ax.set_title("Top 5 Products by Revenue")

    # Region
    ax = axes[1, 0]
    res["by_region"].plot.bar(ax=ax, color="orange")
    ax.set_title("Revenue by Region")
    ax.tick_params(axis="x", rotation=0)

    # Weekday
    ax = axes[1, 1]
    res["by_weekday"].plot.bar(ax=ax, color="purple")
    ax.set_title("Revenue by Weekday")
    ax.tick_params(axis="x", rotation=45)

    # Correlation heatmap
    ax = axes[1, 2]
    corr = res["corr"]
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.grid(False)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=45)
    ax.set_yticks(range(len(corr)), corr.columns)
    for i in range(len(corr)):
        for j in range(len(corr)):
            val = corr.iloc[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    color="white" if abs(val) > 0.6 else "black",
                    fontweight="bold")
    ax.set_title("Correlation Matrix")
    fig.colorbar(im, ax=ax, fraction=0.046)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    raw = generate_data()
    print(f"Raw rows: {len(raw)} | missing values: {int(raw.isna().sum().sum())}")

    df = clean_data(raw)
    print(f"Clean rows: {len(df)}")
    df.to_csv(OUTPUT_DIR / "clean_sales.csv", index=False)

    res = analyze(df)
    pred = forecast(res["monthly"])

    print("\n=== KPIs ===")
    print(f"Total revenue   : ${res['total_revenue']:,.0f}")
    print(f"Orders          : {res['orders']:,}")
    print(f"Avg order value : ${res['avg_order_value']:,.2f}")
    print("\nTop products:\n", res["top_products"].round(0).to_string())
    print("\nForecast (next 3 months):\n", pred.round(0).to_string())

    make_dashboard(res, pred, OUTPUT_DIR / "dashboard.png")
    print(f"\nDashboard saved to {OUTPUT_DIR / 'dashboard.png'}")


if __name__ == "__main__":
    main()
