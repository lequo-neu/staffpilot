# Testing StaffPilot: a guide for first time testers

This guide walks you through checking StaffPilot before a commit or a submission. You do not need to know Python. Follow the parts in order and tick each check. The whole run takes about an hour; Part A alone takes five minutes and is the minimum before any commit.

The expected numbers below come from the public data file `DADS5250_Hackathon_Google_Data.xlsx`. With the official IE5374 file the numbers change, but the behaviour described here stays the same.

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
| A1 | `python -m pytest -q` | the last line says `105 passed` |
| A2 | `python -m compileall -q src tests scripts` | no output at all |
| A3 | `ruff check .` | `All checks passed!` |
| A4 | `python scripts/check_style.py` | `0 finding(s)` |

If A1 reports a failure, stop here and report it; the rest of the guide assumes the tests pass.

## Part B: the command line (10 minutes)

| Step | Command | Expected |
|---|---|---|
| B1 | `python -m staffpilot --version` | `StaffPilot 0.1.0, Copyright © 2026 Seven Team-5374, Trio Intelligence` |
| B2 | `python -m staffpilot plan` | a summary line `Net value $479.7M, service 100.0%, average active agents 2,220 (January 6,474)`, a table of five policies, `Wrote outputs/plan.csv, kpis.csv and policy_comparison.csv`, then a list of alerts starting with `[critical] This file plans 2026, but the brief asks for 2025` |
| B3 | `python -m staffpilot ask "How many agents does Germany need in March and why?"` | a plain English answer that starts `Germany should start the year with 602 agents and finish it with 102`, mentions `In March, 86 agents are working`, and ends with `every number checked against the planner` and `Chart saved to outputs/answers/...png` |
| B4 | `python -m staffpilot ask "What is the weather tomorrow?"` | `That is outside what I can help with.` |
| B5 | `python -m staffpilot ask "What if sign ups in Atlantis rise 20%?"` | `I do not have data for Atlantis.` followed by the list of 22 countries |
| B6 | `python -m staffpilot ask "What if sign ups in Brazil drop 150%?"` | a message that the change is outside the accepted range (between 0.1 and 3), not an error screen |
| B7 | `python -m staffpilot memo Vietnam` | a memo headed `### Staffing memo: Vietnam, 2026` that says Vietnam moves from 59 to 95 agents |
| B8 | `python -m staffpilot eda` | ends with `Wrote outputs/eda/eda_report.md and 6 charts`; open that file in VS Code and check the charts show |
| B9 | `python -m staffpilot history` | a table with one row per `plan` run; the newest row shows `$479.7M`, `100.0%`, `2,220` and a short git commit code |
| B10 | `python -m staffpilot chat`, then type `What if sign ups in Brazil drop 30% in Q3?`, then `And Mexico?`, then press Enter on an empty line | the second answer talks about **Mexico** with the same 30 percent drop from July to September, and the note under it says `Kept the kind of question, months and scenario from your last question` |
| B11 | open the `logs/` folder | a new file for each command you ran, each starting with `Run '<command>' started` |

## Part C: the web app (20 minutes)

Start it with `python -m staffpilot app` and open the address it prints (normally http://127.0.0.1:7860). The first start of the day takes about 15 seconds; later starts take about 5. Stop it at the end by clicking the terminal and pressing Control and C.

### C1. First look

| Step | What to do | Expected |
|---|---|---|
| C1.1 | Look at the browser tab | the title is `StaffPilot` and the icon is a teal square with a white curve, the same as the logo at the top of the sidebar |
| C1.2 | Look at the left sidebar | New chat, then Assistant, Plan, Scenario, Memo, Data and Evaluation, then Recent chats (with `Your chats in this tab appear here.`), Settings, and the copyright line with `Seven Team-5374` on one line |
| C1.3 | Hover over each sidebar item | a short explanation appears for each |
| C1.4 | Look at the top of the page | the page title and one line explaining it; there is **no** line naming the data file or the planning year |

### C2. Assistant

| Step | What to do | Expected |
|---|---|---|
| C2.1 | Read the empty chat | `What do you want to know about the plan?` and six example questions in two columns |
| C2.2 | Click the example `What if sign ups in Brazil drop 30% in Q3?` | the answer says net value goes from `$44.9M` to `$41.7M`, and a sharp chart appears inside the answer |
| C2.3 | Look at the right panel | `How this answer was built` with a green `Numbers checked` chip, the intent, the time, the tool `run_scenario` and the model `offline` |
| C2.4 | Type `And Mexico?` and press Enter | the answer is about Mexico, and the right panel says `This was a follow up, so it kept the kind of question, months and scenario from your last question.` |
| C2.5 | Look at Recent chats | one entry starting `What if sign ups in Brazil drop`; hover shows the full question |
| C2.6 | Click New chat, then ask `How long can an advertiser wait in the pool?` | the chat starts empty, the answer quotes the waiting pool rule, and Recent chats now has two entries |
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
| C3.7 | Click Approve this plan | a message `Approved. 12 rows saved to approved_plan.csv`, and the file exists in `outputs/` |

### C4. Scenario, Memo, Data and Evaluation

| Step | What to do | Expected |
|---|---|---|
| C4.1 | Scenario: click Read the scenario | `Understood as: If sign ups fall 30% from July to September in Germany, ...` and the parameters below |
| C4.2 | Change `"demand_multiplier": 0.7` to `0.5` in the parameters, then click Run the scenario | a summary, a chart and a one row table; the change in net value is larger than at 0.7 |
| C4.3 | Memo: pick Vietnam and click Write the memo | the memo from step B7 with `Every number matches the planner.` and a chart |
| C4.4 | Data: open the page | a list of findings, four charts and a data quality table; the charts are sharp |
| C4.5 | Evaluation: open the page | three tables: assistants, retrieval and runs |

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

## Part F: before you commit

Run these and check the results; nothing private may go into the repository.

| Step | Command | Expected |
|---|---|---|
| F1 | `git status --short` | only files you meant to change |
| F2 | `git ls-files \| grep -E "\.env$\|\.xlsx$\|^\.cache/\|^logs/"` | no output |
| F3 | `python -m pytest -q` | `105 passed` |

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
Part F  F1 [ ]  F2 [ ]  F3 [ ]
```
