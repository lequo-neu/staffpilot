"""Write a small synthetic workbook with the same sheets as the teaching team file.

CI uses it to run the command line tools end to end without the real data:

    python scripts/make_sample_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "sample" / "sample_staffing_data.xlsx"


def main() -> None:
    rng = np.random.default_rng(11)
    countries = pd.DataFrame(
        {
            "Country": ["Alpha", "Beta", "Gamma"],
            "Annual_Agent_Salary_USD": [60000, 30000, 45000],
            "Advertiser_Eligibility_Threshold_USD": [20000, 8000, 15000],
        }
    )
    staffing = pd.DataFrame({"Country": ["Alpha", "Beta", "Gamma"], "Existing_Agent_Count": [40, 5, 25]})
    rows = []
    for day in pd.date_range("2031-01-01", "2032-12-31", freq="D"):
        for country, rate in (("Alpha", 18), ("Beta", 9), ("Gamma", 6)):
            count = rng.poisson(rate * (1.4 if day.month >= 10 else 1.0))
            rows.extend((country, day, float(b)) for b in rng.lognormal(9.8, 0.8, size=count))
    signups = pd.DataFrame(rows, columns=["Country", "Sign_Up_Date", "Projected_Annual_Budget"])
    signups.insert(0, "Advertiser_ID", [f"S{i:06d}" for i in range(len(signups))])
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(TARGET) as writer:
        countries.to_excel(writer, sheet_name="Agent Salary and Threshold", index=False)
        signups.to_excel(writer, sheet_name="Advertiser Sign-ups", index=False)
        staffing.to_excel(writer, sheet_name="Existing Agent Staffing", index=False)
    print(f"Wrote {TARGET} with {len(signups)} sign ups")


if __name__ == "__main__":
    main()
