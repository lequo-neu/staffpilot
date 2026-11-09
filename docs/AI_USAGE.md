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
| Notebook text and `docs/REPORT.md` | drafting of prose; the notebook's last cell points to this page, and this table marks which parts were drafted with AI | every number was copied from an executed cell and rechecked |
| README | drafting | commands were run on a fresh environment |
| `docs/METHODS.md`, `docs/EVALUATION.md` | drafting and restructuring of the README text | every number was checked against the app, the results files or `docs/REPORT.md`; the screenshots in `docs/Assets/` were taken by the team in the running app |
| Evaluation questions | drafted, then edited | Hamad Al Sulaimi and Khoa Tran checked every label in `eval/label_review.csv` on 3 November 2026 and Quoc Hung Le cross checked ten; no label needed a change and six unclear questions carry a comment; a separate holdout set was written in different words |
| Slides (`docs/StaffPilot_Presentation.pdf`) and the video narration | first draft of the slides on the team's own template, and of the narration | the team edited the slides, checked every number in the app, and recorded both videos |
| Manager pages: Compare policies, Country inputs, Scenario step by step (`manager.py`) | written by Hamad Al Sulaimi with a coding assistant (Claude Code) | 9 tests compare every number with the planner's own outputs; Quoc Hung Le reviewed the pull request, ran it in the browser and corrected one assumption line that contradicted the report |

Every AI assisted part is listed in this table. Team members review each change before it is merged.

## What the team decided

The AI drafted code and text; these choices were the team's, and each one can be checked in the repository.

* **The problem and the data.** We chose Topic 3 and confirmed it by email with Ms. Niki on 3 November 2026. When the brief's years (2023 to 2025) did not match the course dataset (sign ups for 2024 and 2025), we asked the teaching team and plan 2026 as they confirmed.
* **Impossible dates.** 920 cells read 29 February 2025, a day that does not exist. We kept them on 28 February instead of dropping them, and measured what that choice is worth: $0.85M of net value, about 200 advertisers and 8.5 agents (`docs/REPORT.md`).
* **How to read the brief.** Where its words point one way we take the literal reading; otherwise the reading that makes the result look worse, so the headline is not inflated (eleven assumptions in `docs/METHODS.md`).
* **The recommended goal.** We recommend "at least 98% served" over profit only, because it serves every eligible advertiser for $0.03M of net value.
* **Offline first.** The app, notebook, tests and CI run with no API key, so anyone can check the work for free; language models are an option, not a requirement.
* **No patches for one model.** When a small local model misread some questions, we kept the router general and recorded the result in the evaluation instead of adding rules for that model.
* **Hamad's prototype.** Hamad Al Sulaimi built a separate scenario explorer; its hard questions became the 11 question edge set, and its ideas led to lists of changes and asking back instead of guessing. He then built the manager pages himself through a pull request that Quoc Hung Le reviewed.
* **Checking the labels and the judge.** Hamad Al Sulaimi and Khoa Tran checked all 82 evaluation labels (reviewer column in `eval/label_review.csv`); Quoc Hung Le graded 30 answers by hand, found the local judges too lenient, and the team decided that their scores should not be used to rank models (`docs/EVALUATION.md`).
* **Business sense.** Khoa Tran checked the plan against capacity planning practice and wrote the business recommendations in the report.

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
