# How AI tools were used

The course allows AI tools if their use is explained and AI generated parts are marked. This page is that statement.

## Tools

* A coding assistant (Claude) was used to draft code, tests, the notebook builder and documentation, to research related work, and to review the work from a teaching assistant, tester and instructor point of view.
* The application itself calls OpenAI, Anthropic and Google models at run time; that is the product, not assistance.

## What was AI assisted

| Part | AI role | How the team checked it |
|---|---|---|
| Package code in `src/staffpilot/` | first drafts of modules | 190 unit tests, lint, runs on real data, a day by day simulator that checks every plan |
| Tests in `tests/` | drafted from the brief rules | each rule case is small enough to check by hand |
| Notebook text and `docs/report.md` | drafting of prose; every notebook section carries a marker | every number was copied from an executed cell and rechecked |
| README | drafting | commands were run on a fresh environment |
| `docs/METHODS.md`, `docs/EVALUATION.md`, `docs/PRESENTATION.md` | drafting and restructuring of the README text | every number was checked against the app, the results files or `docs/report.md`; the screenshots in `docs/Assets/` were taken by the team in the running app |
| Evaluation questions | drafted, then edited | Hamad Al Sulaimi and Khoa Tran checked every label in `eval/label_review.csv` on 3 November 2026 and Quoc Hung Le cross checked ten; no label needed a change and six unclear questions carry a comment; a separate holdout set was written in different words |
| Manager pages: Compare policies, Country inputs, Scenario step by step (`manager.py`) | written by Hamad Al Sulaimi with a coding assistant (Claude Code) | 9 tests compare every number with the planner's own outputs; Quoc Hung Le reviewed the pull request, ran it in the browser and corrected one assumption line that contradicted the report |

Every AI assisted part is listed in this table. Team members review each change before it is merged.

## What the review found that changed the work

AI assisted reviews from a teaching assistant, tester and instructor point of view (see `Review-skill/` in the course folder) led to these changes:

* Plans looked like they broke the ten advertiser rule when headcount was cut. The cause was a greedy dispatch rule in the simulator, not the optimizer; the simulator now lets agents under notice take no new advertisers.
* Uplift was counted in the month of service, which pushed December value out of the year and made replanning look worse than it was. It is now counted for the sign up cohort.
* Two conclusions in an early report draft contradicted the model (on assumption A1 and on the early service preference A9) and were rewritten from the outputs.
* A rough threshold estimate ($175M) was far above the model result (a few million dollars per country) and was dropped.
* Out of range scenarios, unknown countries and countries without eligible sign ups used to crash or be silently ignored; each now has a message and a test.
* The course dataset contains dates that do not exist (29 February 2025); the loader moves them to 28 February.

## What was not used

No code was copied from other teams or from other courses.
