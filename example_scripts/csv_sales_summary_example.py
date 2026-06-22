#!/usr/bin/env python3
"""Summarize sales data from an in-memory CSV string."""

from collections import defaultdict
import csv
from io import StringIO


SALES_CSV = """region,product,quantity,unit_price
North,Notebook,4,3.50
South,Pencil,10,0.80
North,Pencil,6,0.80
West,Notebook,2,3.50
South,Notebook,1,3.50
"""


def summarize_sales(csv_text):
    """Return total revenue grouped by region."""
    totals = defaultdict(float)
    reader = csv.DictReader(StringIO(csv_text))
    for row in reader:
        quantity = int(row["quantity"])
        unit_price = float(row["unit_price"])
        totals[row["region"]] += quantity * unit_price
    return dict(totals)


def main():
    for region, total in sorted(summarize_sales(SALES_CSV).items()):
        print(f"{region}: ${total:.2f}")


if __name__ == "__main__":
    main()
