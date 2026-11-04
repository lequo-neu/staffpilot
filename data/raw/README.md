# Input data

Put the IE5374 workbook from Canvas here as `IE5374_Hackathon_Google_Data.xlsx`, the name in `config/staffpilot.toml`. It is not committed because it is course material.

* Another file: save it in this folder and set `path` under `[data]` in `config/staffpilot.toml`.
* The code also reads a folder of three CSV files with the same columns.

Expected tables (sheet names can differ, columns are matched by name):

| Table | Columns |
|---|---|
| Salary and threshold | Country, Annual_Agent_Salary_USD, Advertiser_Eligibility_Threshold_USD |
| Sign ups | Advertiser_ID, Country, Sign_Up_Date, Projected_Annual_Budget |
| Existing staffing | Country, Existing_Agent_Count |

The planning year is the year after the last sign up year, so a file covering 2023 and 2024 plans 2025 and a file covering 2024 and 2025 plans 2026. No code change is needed.
