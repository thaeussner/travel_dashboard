"""Costs: CHF amounts by date, category and country. No conversion and no assumptions.

The page aggregates the rows itself (simple sums), so it can include entries made on the phone
before the next build. This module only normalises the rows and adds a summary.
"""

from __future__ import annotations

import datetime as dt

from .tables import COST_CATEGORIES, Cost

CATEGORY_LABELS = {
    "groceries": "Groceries", "coffee": "Coffee", "treats": "Treats", "activities": "Activities",
    "accommodation": "Accommodation", "transport": "Transport", "restaurants": "Restaurants", "other": "Other",
}


def calendar_days(first: dt.date, last: dt.date, today: dt.date) -> int:
    """Days the averages are spread over: first entry until today (or the last entry if later)."""
    end = max(last, today) if today >= first else last
    return (end - first).days + 1


def build(costs: list[Cost], today: dt.date) -> dict:
    rows = sorted(costs, key=lambda c: (c.date, c.id))
    out: dict = {
        "categories": [{"id": c, "label": CATEGORY_LABELS[c]} for c in COST_CATEGORIES],
        "rows": [{"id": c.id, "date": c.date.isoformat(), "amount": c.amount, "category": c.category,
                  "country": c.country} for c in rows],
        "summary": None,
    }
    if rows:
        total = round(sum(c.amount for c in rows), 2)
        days = calendar_days(rows[0].date, rows[-1].date, today)
        out["summary"] = {
            "total": total,
            "first": rows[0].date.isoformat(),
            "last": rows[-1].date.isoformat(),
            "days": days,
            "entries": len(rows),
            "countries": len({c.country for c in rows}),
            "per_day": round(total / days, 2),
        }
    return out
