# Testing StaffPilot: a guide for first time testers

This guide walks you through checking StaffPilot before a commit or a submission. You do not need to know Python. Follow the parts in order and tick each check. The whole run takes about an hour; Part A alone takes five minutes and is the minimum before any commit.

The expected numbers below come from the public data file `IE5374_Hackathon_Google_Data.xlsx`. With the official IE5374 file the numbers change, but the behaviour described here stays the same.

## Before you start

1. Finish the [setup guide](SETUP_GUIDE.md) up to Step 6, so StaffPilot is installed and the data file is in `data/raw/`.
2. Open a terminal and go to the project folder (the one that contains `README.md`).
3. Turn on the environment:
   * macOS: `source .venv/bin/activate`
   * Windows: `.venv\Scripts\Activate.ps1`
4. The prompt now starts with `(.venv)`. If it does not, every command below will fail; go back to step 3.

Copy the checklist at the end of this guide into a note or a spreadsheet and fill it in as you go.

### How to record a result

* **Pass**: what you saw matches "Expected".
* **Fail**: anything else, even a small thing such as wrong wording, text cut off or a slow page. Write down the steps, what you expected, what you saw, a screenshot, and the newest file in `logs/` (each run writes its own file, named after the time and the command, for example `logs/20261103_145757_plan.log`).

Nothing in Parts A to D costs money. Part E uses paid language models and needs the team's permission first.

## Part A: automatic checks (5 minutes)

These run the project's own tests. Run each command and compare the last line.

| Step | Command | Expected |
|---|---|---|
| A1 | `python -m pytest -q` | the last line says `140 passed` |
| A2 | `python -m compileall -q src tests scripts` | no output at all |
| A3 | `ruff check .` | `All checks passed!` |
| A4 | `python scripts/check_style.py` | `0 finding(s)` |

If A1 reports a failure, stop here and report it; the rest of the guide assumes the tests pass.

## Part B: the command line (10 minutes)

| Step | Command | Expected |
|---|---|---|
| B1 | `python -m staffpilot --version` | `StaffPilot 0.1.0, Copyright © 2026 Seven Team-5374` |
| B2 | `python -m staffpilot plan` | a summary line `Net value $479.7M, service 100.0%, average active agents 2,220 (January 6,474)`, a table of five policies, `Profit against service level:` with five goals (the last, `within 7 days`, gives up about `$3.61M` and serves `100.0%` within 7 days), `Wrote outputs/plan.csv, kpis.csv, policy_comparison.csv and service_tradeoff.csv`, then a list of alerts starting with `[critical] This file plans 2026, but the brief asks for 2025` |
| B3 | `python -m staffpilot ask "How many agents does Germany need in March and why?"` | a plain English answer that starts `Germany should start the year with 602 agents and finish it with 102`, mentions `In March, 86 agents are working`, and ends with `every number checked against the planner` and `Chart saved to outputs/answers/...png` |
| B4 | `python -m staffpilot ask "What is the weather tomorrow?"` | `That is outside what I can help with.` |
| B5 | `python -m staffpilot ask "What if sign ups in Atlantis rise 20%?"` | `I do not have data for Atlantis.` followed by the list of 22 countries |
| B6 | `python -m staffpilot ask "What if sign ups in Brazil drop 150%?"` | a message that the change is outside the accepted range (between 0.1 and 3), not an error screen |
| B7 | `python -m staffpilot memo Vietnam` | a memo headed `### Staffing memo: Vietnam, 2026` that says Vietnam moves from 59 to 95 agents |
| B8 | `python -m staffpilot eda` | ends with `Wrote outputs/eda/eda_report.md and 6 charts`; open that file in VS Code and check the charts show |
| B9 | `python -m staffpilot history` | a table with one row per `plan` run; the newest row shows `$479.7M`, `100.0%`, `2,220` and a short git commit code |
| B10 | `python -m staffpilot chat`, then type `What if sign ups in Brazil drop 30% in Q3?`, then `And Mexico?`, then press Enter on an empty line | the second answer talks about **Mexico** with the same 30 percent drop from July to September, and the note under it says `Kept the kind of question, months and scenario from your last question` |
| B11 | `python -m staffpilot update Germany --month 2 --percent 40` | four bullets: sign ups `40% above the forecast`; keeping the plan serves `87.7%` after `32.4 days`; the updated plan serves `100.0%` and `adds $5.5M`; `Decide in February: hire 31 (the plan said 0)`; then `Wrote outputs/update_Germany_02.csv` |
| B12 | open the `logs/` folder | a new file for each command you ran, each starting with `Run '<command>' started` |

## Part C: the web app (20 minutes)

Start it with `python -m staffpilot app` and open the address it prints (normally http://127.0.0.1:7860). The first start of the day takes about 15 seconds; later starts take about 5. Stop it at the end by clicking the terminal and pressing Control and C.

### C1. First look

| Step | What to do | Expected |
|---|---|---|
| C1.1 | Look at the browser tab | the title is `StaffPilot` and the icon is a teal square with a white curve, the same as the logo at the top of the sidebar |
| C1.2 | Look at the left sidebar | Assistant and This year at the top, then the groups Before the year starts (Data, Plan, Scenario, Memo), Every month (Monthly update, Decision log) and Behind the numbers (Evaluation), then Recent chats (with `Your chats in this tab appear here.`), Settings, and the copyright line with `Seven Team-5374` on one line; there is no separate New chat button |
| C1.3 | Hover over each sidebar item | a short explanation appears for each |
| C1.4 | Look at the top of the page | the page title and one line explaining it; there is **no** line naming the data file or the planning year |
| C1.5 | Read This year | four tiles: `$479.7M` with `$109.3M more than keeping the January team`, `6,474 → 2,220`, `100.0%` and `Not approved`; a strip of twelve months where January shows `6,474`, `Hire 11, Notice 4,741` (the notice in red) and `Decide now`; four steps start with `1. Check the data`; on the right the alerts that need action |
| C1.6 | Pick `Start of March` in Where are you in the year? | January and February say `Carried out`, March says `Decide now`, and the steps start with `1. Enter what happened` |
| C1.7 | Click `Open Monthly update` on the first step | the Monthly update page opens with `March` already picked, and Monthly update is marked in the sidebar |
| C1.8 | Scroll to the end of Data, Plan, Scenario, Memo, Monthly update and Decision log | each ends with a line saying what comes next and a button that opens it |
| C1.9 | Look at the sidebar and the page | the groups are teal bands in capitals, each page has an icon, panel titles, field names, tabs and buttons are in capitals, and every area has a clear edge |
| C1.10 | Click any chart | it opens at full size over the page; a click or Escape closes it |

### C2. Assistant

| Step | What to do | Expected |
|---|---|---|
| C2.1 | Read the empty chat | `What do you want to know about the plan?` and six example questions in two columns |
| C2.2 | Click the example `What if sign ups in Brazil drop 30% in Q3?` | the answer says net value goes from `$44.9M` to `$41.7M`, and a sharp chart appears inside the answer |
| C2.3 | Look at the right panel | `How this answer was built` with a green `Numbers checked` chip, the intent, the time, the tool `run_scenario` and the model `offline`, and a line saying how many numbers were matched to planner facts; under the chat box `Answered by Offline (free, no API key)` |
| C2.4 | Type `And Mexico?` and press Enter | the answer is about Mexico, and the right panel says `This was a follow up, so it kept the kind of question, months and scenario from your last question.` |
| C2.5 | Look at Recent chats | one entry starting `What if sign ups in Brazil drop`; hover shows the full question |
| C2.6 | Click New chat above the conversation, then ask `How long can an advertiser wait in the pool?` | the chat starts empty, the answer quotes the waiting pool rule, and Recent chats now has two entries |
| C2.7 | Click the first entry in Recent chats, then ask `What about 50 percent instead?` | the old conversation comes back and the answer uses a **50** percent drop for **Mexico** |
| C2.8 | Open Settings and click Save conversation | a Markdown file to download appears, listing the questions and answers |
| C2.9 | Send an empty message, then `thanks`, then `!!!` | nothing breaks; the last two get a polite answer that says what the assistant can help with |

### C3. Plan

| Step | What to do | Expected |
|---|---|---|
| C3.1 | Click Plan | five cards: Net value `$479.7M`, Agents at work `2,220`, Advertisers served `100.0%`, Agent utilization, Total cost `$178.5M`; each has a small line chart and a green or red change against keeping the January team |
| C3.2 | Hover over the small `i` next to each card title | a dark tooltip explains the number; it is not cut off at the edges of the screen |
| C3.3 | Check that these cards appear **only** on the Plan page | the Assistant, Scenario, Memo, Data and Evaluation pages do not show them |
| C3.4 | Open `5 items need attention, 1 of them critical` | the same alerts as in step B2 |
| C3.5 | Choose `Germany` in Country | the cards, the chart and the table switch to Germany; the chart title says Germany |
| C3.6 | Check the chart closely | text and lines are sharp, not blurry; labels do not sit on top of the line |
| C3.7 | Click Approve this plan | `Approved with the goal Profit, 98% served (recommended). Saved approved_plan_Germany_service_98_<date>_<time>.csv`; the file is in `outputs/`, and the decision log names it |
| C3.8 | Set Country back to `All countries`, scroll to `Profit against service level` | two bar charts: net value given up (`$0` for profit only, `$31k` for the recommended goal, `$3.6M` for 7 days) and advertisers served within 7 days (`91.4%` up to `100.0%`) |
| C3.9 | Pick the service goal `Profit, 98% served within 7 days` | the cards change (Net value `$476.1M`), the chart title names the goal, and the text says how much net value the goal gives up |

| C3.9b | Open `Month by month detail` at the end of the overview | the table, with hires in teal and notices and their cost in red |
| C3.10 | Click the tab Check the plan (Country: All countries) | `8 of 8 checks pass`, each with a line of numbers, and one `Note` saying that 5% fewer agents would earn about $1.8M more while the wait goes from 1.1 to 2.1 days |
| C3.11 | Click How it is calculated | uplift, salaries and notice cost written as sums of their inputs that add up to `$479.7M`; a month by month table and a CSV to download |
| C3.12 | Pick Germany, click Try your own plan, then Score my plan | the table holds the optimized headcount and a copy 5% lower; the result says your plan earns about `$106k more` by making advertisers wait longer (1.9 instead of 1.3 days) |
| C3.13 | Set the slider to `+5` and score again | your plan earns less than the optimized plan |
| C3.14 | Type a different number in January and score | the result says January is `Not possible as typed`, because decisions take a month |

### C3b. Monthly update

| Step | What to do | Expected |
|---|---|---|
| C3b.1 | Click Monthly update, pick `Germany` and the month `February` | the table `Actual eligible sign ups` shows January with its forecast and an actual count 20 percent higher |
| C3b.2 | Set the slider to `40`, click Update the plan | four bullets that match step B11, a chart of the approved and the updated headcount from February, and a table where changed cells read like `86 → 117` |
| C3b.3 | Type a different number in the Actual column, and `-2` in Agents on staff against the plan, then update again | the summary says `2 agents fewer than planned are on staff now` and the numbers change |
| C3b.4 | Click Approve the update | `Approved. Saved approved_update_Germany_2026-02_<date>_<time>.csv`, and rows are added to the decision log |
| C3b.5 | Pick the month `January` | not possible: the list starts in February, because January has no months done yet |
| C3b.6 | Look at `Input check` under the table | each month read back against its forecast; type a number three times the forecast and it says `Check this count` |
| C3b.7 | After approving, pick the month `April` | January keeps the count you approved, the input check says `Starts from the update approved in` the earlier month, and the update keeps that month's new hires as carried out |

### C4. Scenario, Memo, Data and Evaluation

| Step | What to do | Expected |
|---|---|---|
| C4.1 | Scenario: open the page | the Germany example is already read and run, with a chart from February where the changed months are shaded; click `Sign ups in the USA rise 20% in Q4` and it is read and run in one click: net value $117.6M to $126.9M |
| C4.2 | Open `Edit the parameters`, change `"demand_multiplier": 0.7` to `0.5`, then click Run the scenario | a summary, a chart and a one row table; the change in net value is larger than at 0.7 |
| C4.3 | Memo: open the page | a memo for the first country is already written; pick Vietnam and click Write the memo for the memo from step B7, with `Every number matches the planner.` and a chart |
| C4.4 | Data: open the page | seven fact tiles first (`2.8×` in red, `Vietnam` in amber), four sharp charts, then `Data quality` with `3 of 3 checks pass` and two notes; the table opens from `Every check, as a table` |
| C4.5 | Evaluation: open the page | one line on the holdout, a chart of questions read right and seconds per answer, then tiles for rule retrieval (`7 of 8`, `1` missed) and plan runs; each table opens below its tiles, with the best scores, the missed question and the latest run tinted |
| C4.6 | Decision log: open the page | four tiles (decisions, values changed, changed by you, answers where a guardrail acted) and filter buttons; the newest decisions first: the scenario from C4.2 with `demand_multiplier` proposed `0.7` by the reader and applied `0.5` after your edit (adjusted by `manager`), then the result rows marked as computed by the planner; the monthly update and plan approvals from C3; one `assistant answer` row per question with the guardrails that acted; a `decision_audit.csv` file to download | Click `Only changes`: only rows with an adjustment remain, tinted amber |

### C5. Settings and models

| Step | What to do | Expected |
|---|---|---|
| C5.1 | Open Settings | Language model shows `Offline (free, no API key)` |
| C5.2 | Open the list (only if API keys are set in `.env`) | Offline first, then models with the provider in brackets, cheapest first; one says `cheapest working`; retired models such as `gpt-4.1-nano` are not listed |
| C5.3 | Click Refresh models | the list reloads and Offline stays selected |

### C6. Look and size

| Step | What to do | Expected |
|---|---|---|
| C6.1 | Add `?__theme=dark` to the address and reload | a dark version where all text is readable |
| C6.2 | Make the window narrow, or in Chrome press Command Option I (Windows: F12) and pick a phone in the device toolbar | the sidebar is closed and opens from the arrow at the top left; it closes again after you pick a page; the Plan cards sit two per row; no text is cut off or overlapping; nothing scrolls sideways |
| C6.3 | With the sidebar closed on a wide window | the page title is not hidden behind the sidebar arrow |

## Part D: things that must not happen

Report any of these as a failure, wherever you see it:

* raw braces such as `{{5,343}}` or `{{Brazil.net_value}}` in an answer;
* a Python error or a stack trace in the browser or the terminal;
* an answer with a number that the right panel marks `Check failed`;
* text written in all capitals in the interface, or text that overlaps or is cut off;
* a page that takes more than a few seconds to answer on Offline.

## Part E (optional, costs money): language models

Only with the team's permission, and only with keys in `.env`.

1. `python -m staffpilot models --ping` lists the models and sends one tiny request to two of them; each should end in `ok`.
2. In the app, pick the model marked `cheapest working` and repeat steps C2.2 to C2.4. Answers may take a few seconds. They must still show `Numbers checked`, or fall back to the same text as Offline; they must never show braces.
3. Run `python -m staffpilot chat --agent --backend anthropic_fast`, ask `Which three countries give the most notices this year?`, then `For the first of those, what is its net value?`. Expected: Germany 516, UK 487, USA 439, then Germany's net value of about 24.0 million; the line under each answer names the tool and says every number was found in the tool output. Compare with [AGENT_LIVE_CHECK.md](AGENT_LIVE_CHECK.md).
4. Switch back to Offline when you finish.

## Part G (optional, free): the multi LLM evaluation with local models

This compares language models running on your own computer through LM Studio or Bionic, at no cost. It needs at least two chat models, each from a different family, and about 16 GB of free memory for two small models. Close other heavy apps first.

| Step | What to do | Expected |
|---|---|---|
| G1 | `~/.lmstudio/bin/lms ls` | your downloaded models, for example `google/gemma-4-e4b` |
| G2 | `~/.lmstudio/bin/lms server start` | `Success! Server is now running on port 1234` (the wording may differ slightly) |
| G3 | `python -m staffpilot models` | a `local:` section listing the same models |
| G4 | `python -m staffpilot ask "How many agents does Germany need in March?" --backend local_fast` | an answer about Germany, the same numbers as step B3, and a note naming the local model; the first call can take a minute while the model loads |
| G5 | `python -m staffpilot --log-level INFO eval --source local gemma llama --skip-agent` (use words that match two of your models) | first `Comparing 2 local models (no cost): ...`, then one `Answered as ...` line per question, and at the end a table with rows for `offline` and each local model on the main, holdout and followups splits |
| G6 | open `eval/results/summary.csv` | a `judge_score` for each local model (graded by the other one) and an empty cost column |
| G7 | `~/.lmstudio/bin/lms server stop` | the server stops and the memory is freed |

Leave out `--skip-agent` to include the agent chat; it takes about twice as long.

## Part H (free): grade answers by hand to check the AI judge

The judge score in the results comes from language models. This part checks it against people. Two graders each grade the same 30 answers alone, then the script compares them. It takes about 45 minutes per grader and calls no model.

| Step | What to do | Expected |
|---|---|---|
| H1 | `python scripts/judge_review.py sheet` (skip it when `eval/judge_review.xlsx` already exists; it never replaces one without `--force`) | `Wrote eval/judge_review.xlsx with 30 answers to grade`, then the rubric the AI judges use |
| H2 | open `eval/judge_review.xlsx` in Excel or Google Sheets; do not open `eval/judge_review_key.csv` | one row per answer: the question, the earlier question for a follow up, the facts the planner gave, and the answer |
| H3 | each grader renames one pair of columns to their own name, for example `Khoa score` and `Khoa reason`, then fills a whole number from 1 to 5 and a reason for every row, without looking at the other grader; save as Excel (.xlsx), not CSV | 30 scores in each column |
| H4 | `python scripts/judge_review.py compare` | a table comparing the two graders and the people with each AI judge, then the mean score per model from both |

How to grade one row:

1. Read the question and decide what a complete answer must contain, for example a headcount for one country and one month.
2. Check every number in the answer against the facts column. A number that is not there, or that belongs to another country or month, is wrong.
3. Give the score from the rubric: 5 exact and complete with nothing invented; 4 correct but missing a part or adding an unneeded detail; 3 one number attached to the wrong thing or the main point buried; 2 answers a different question or a key number is wrong; 1 wrong, invented, off topic or not readable text (for example raw code). A polite refusal of an out of scope question scores 5. A longer answer is not a better answer.
4. Write the reason in one sentence, naming the wrong number when there is one.

How to read the result:

* The row comparing the two graders is the ceiling: the judges cannot be expected to agree with people more than people agree with each other.
* `within one point` of 80% or more and a `rank correlation` of 0.7 or more mean the judge can be trusted to compare models.
* `bias` above 0 means the judge scores higher than people.
* If the people and the judges put the models in a different order, report the people's order.

Commit the filled sheet, the key and `eval/results/judge_agreement.csv`.

The grades must be your own: comparing AI written grades with AI judges checks nothing. If only one person grades, the comparison still works, and the report says it rests on one grader.

## Part F: before you commit

Run these and check the results; nothing private may go into the repository.

| Step | Command | Expected |
|---|---|---|
| F1 | `git status --short` | only files you meant to change |
| F2 | `git ls-files \| grep -E "\.env$\|\.xlsx$\|^\.cache/\|^logs/"` | no output |
| F3 | `python -m pytest -q` | `140 passed` |

Then commit as described in the README.

## If something goes wrong

| Problem | Try this |
|---|---|
| `Address already in use` when starting the app | another copy is running; stop it, or start on another port with `python -m staffpilot app --port 7861` |
| The app looks old after an update | reload with Command Shift R (Windows: Control Shift R) |
| Numbers look wrong after changing the data or settings | delete the `.cache` folder and start again; StaffPilot rebuilds it |
| `Data problem: Dataset not found` | the data file is missing from `data/raw/`; see Step 6 of the setup guide |
| The browser tab still shows an old icon | browsers keep icons for a while; reload with Command Shift R |

## Bug report template

```
Title: <one line, what is wrong>
Where: <command or app page>
Steps: 1. ... 2. ... 3. ...
Expected: <what this guide says>
Actual: <what you saw>
Screenshot: <attach>
Log file: <newest file in logs/>
Computer: <macOS or Windows, browser>
```

## Checklist

```
Part A  A1 [ ]  A2 [ ]  A3 [ ]  A4 [ ]
Part B  B1 [ ]  B2 [ ]  B3 [ ]  B4 [ ]  B5 [ ]  B6 [ ]  B7 [ ]  B8 [ ]  B9 [ ]  B10 [ ]  B11 [ ]
Part C  C1.1 [ ]  C1.2 [ ]  C1.3 [ ]  C1.4 [ ]
        C2.1 [ ]  C2.2 [ ]  C2.3 [ ]  C2.4 [ ]  C2.5 [ ]  C2.6 [ ]  C2.7 [ ]  C2.8 [ ]  C2.9 [ ]
        C3.1 [ ]  C3.2 [ ]  C3.3 [ ]  C3.4 [ ]  C3.5 [ ]  C3.6 [ ]  C3.7 [ ]
        C4.1 [ ]  C4.2 [ ]  C4.3 [ ]  C4.4 [ ]  C4.5 [ ]
        C5.1 [ ]  C5.2 [ ]  C5.3 [ ]
        C6.1 [ ]  C6.2 [ ]  C6.3 [ ]
Part D  none seen [ ]
Part E  (optional) E1 [ ]  E2 [ ]  E3 [ ]  E4 [ ]
Part G  (optional) G1 [ ]  G2 [ ]  G3 [ ]  G4 [ ]  G5 [ ]  G6 [ ]  G7 [ ]
Part F  F1 [ ]  F2 [ ]  F3 [ ]
```
