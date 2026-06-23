"""
Sales Analysis Chart
Author: vamsi
Improved Python 3 version
"""

from pathlib import Path
import argparse

import pandas as pd
import matplotlib.pyplot as plt


def load_sales_data(csv_path: Path) -> pd.DataFrame:
    """Load, validate, and clean sales data from a CSV file."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    df = pd.read_csv(csv_path)

    required_columns = {"SalesID", "ProductPrice"}
    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required column(s): {', '.join(sorted(missing_columns))}"
        )

    df["SalesID"] = pd.to_numeric(df["SalesID"], errors="coerce")
    df["ProductPrice"] = pd.to_numeric(df["ProductPrice"], errors="coerce")

    df = df.dropna(subset=["SalesID", "ProductPrice"])
    df = df.sort_values("SalesID")

    if df.empty:
        raise ValueError("No valid SalesID and ProductPrice records were found.")

    return df


def create_chart(df: pd.DataFrame, output_path: Path | None = None) -> None:
    """Create a sales-price line chart."""
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.plot(
        df["SalesID"],
        df["ProductPrice"],
        marker="o",
        linewidth=2,
        markersize=5,
        label="Product Price",
    )

    ax.set_title("Sales Analysis", fontsize=16, fontweight="bold")
    ax.set_xlabel("Sales ID", fontsize=12)
    ax.set_ylabel("Product Price", fontsize=12)

    ax.grid(True, linestyle="--", alpha=0.6)
    ax.legend()
    fig.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=300)
        print(f"Chart saved to: {output_path}")

    plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a ProductPrice chart from a sales CSV file."
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=r"C:\Users\Test\Desktop\SalesData.csv",
        help="Path to SalesData.csv",
    )
    parser.add_argument(
        "--save",
        metavar="OUTPUT_FILE",
        help="Optional output image path, e.g. sales_chart.png",
    )

    args = parser.parse_args()

    try:
        df = load_sales_data(Path(args.csv_file))

        print("\nSales Summary")
        print("-" * 30)
        print(f"Records analysed: {len(df)}")
        print(f"Lowest price:  {df['ProductPrice'].min():.2f}")
        print(f"Highest price: {df['ProductPrice'].max():.2f}")
        print(f"Average price: {df['ProductPrice'].mean():.2f}")

        output_path = Path(args.save) if args.save else None
        create_chart(df, output_path)

    except (FileNotFoundError, ValueError, pd.errors.ParserError) as error:
        print(f"Error: {error}")


if __name__ == "__main__":
    main()
