# Demo guide

A presenter's guide to StaffPilot for an audience that has never seen it. It explains the problem, how the product is built, and then walks through every page in the order a staffing manager would use them, with the numbers the app shows on the public copy of the data (planning year 2026). A three minute version for the video is at the end.

Start the app with no paid model: `STAFFPILOT_OFFLINE=1 python -m staffpilot app`, open http://127.0.0.1:7860 in a wide window, and wait about 15 seconds the first time. Sign in before the audience arrives (for example as `kevin`, choosing a new password at the first sign in), or start with `STAFFPILOT_LOGIN=0` to skip sign in. To show a language model instead, pick one in Settings before the Assistant step.

## 1. The story in one minute

**The problem (from the brief).** Google's advertiser support team has agents in 22 countries. Each new advertiser whose projected budget is above the country's threshold gets an agent for 60 days; an agent holds at most 10 advertisers; an advertiser waits at most 60 days in a pool; a new hire needs a month of ramp up; a notice takes a month and costs 40 percent of a year's salary. The question: how many agents should each country have in each month of the year?

**The answer the app gives.** The January team (6,474 agents) is about 2.8 times what the busiest weeks need. Give notice early, hire a few agents back before the fourth quarter peak, and grow Vietnam. That earns $479.7M of net value, $109.3M more than keeping the January team, while every eligible advertiser is served after about a day.

**What makes it a GenAI product.** A manager can ask about the plan in plain English, describe a change in a sentence, and get a memo per country. A language model reads the words and writes the sentences, but every number comes from the planner and is checked before it is shown.

## 2. How it is built, for a beginner

Think of two layers: a calculator that is always right about the rules, and an assistant that talks about it.

**The planning core (no language model).**

1. **Data.** About 500,000 sign ups from 2024 and 2025, the salary and threshold of each country, and the January headcount. Impossible dates such as 29 February 2025 are repaired, and each sign up is marked eligible or not.
2. **Forecast.** Eligible sign ups per country and month for the planning year, from the seasonal pattern of the two years.
3. **Optimizer.** One mathematical program per country (a mixed integer program solved by CBC) chooses hires and notices month by month to earn the most: the uplift from served advertisers minus salaries and notice costs.
4. **Simulator.** Replays the plan day by day under the exact rules of the brief. Every number in the app comes from here, so a shortcut inside the optimizer can never leak into a result.
5. **Planner.** Uses the two to compare policies, run what if scenarios, update the plan during the year and score any plan a manager types in.

**The assistant (GenAI).**

1. **Route.** A language model, or a free keyword reader when there is no API key, turns the question into a typed request: what kind of question, which countries, which months, what change.
2. **Tools.** The matching planner tool runs and returns facts, such as Germany's hires.
3. **Write.** The model writes the answer with placeholders like `{{Germany.hires}}` instead of numbers.
4. **Check.** The placeholders are filled from the facts, and any number that did not come from a tool, or belongs to another country, is rejected. A rejected answer is retried once, then replaced by a template.

All six course techniques are used: API calls, prompt engineering, structured output, LangChain, retrieval (BM25 over the rules) and agents.

## 3. The walkthrough

The sidebar starts with the **Assistant**, which serves any moment, and **This year**; then it follows the manager's year: **Before the year starts** (Data, Plan, Scenario, Memo), **Every month** (Monthly update, Decision log) and **Behind the numbers** (Evaluation). **New chat** sits above the conversation on the Assistant page. Every page ends with a button to the next step, so the demo can follow those buttons.

Each step below says what to click, what the screen shows, what to say, and which brief requirement or advanced feature it proves. Tags: **[Brief]** is something the brief asks for; **[Advanced]** goes beyond it.

### Step 1. This year: the answer first

* **Shows:** four tiles: **$479.7M** net value, $109.3M (+29.5%) more than keeping the January team; **6,474 → 2,220** agents (65.7% fewer); **100.0%** served after 1.1 days, longest wait 35 days against the 60 day limit, at most 10.0 advertisers per agent against the limit of 10; **Not approved**. Below, a strip of the twelve months: January 6,474 agents with **Hire 11, Notice 4,741** (the notice in red), September Hire 213, October Hire 108. On the right, four alerts with their numbers, such as "Vietnam has 59 agents and the plan needs up to 95 by October: hire 36", each with an **Open Plan** button where the manager acts on it.
* **Say:** "This is the year in one screen. The big decision is in January: 4,741 notices, because the team is far larger than demand. A few agents are hired back before the fourth quarter peak."
* **Proves:** **[Brief]** agents per country and month, with the hiring and notice timing. **[Advanced]** a home page organised around the manager's year.
* **Then:** keep "Where are you in the year?" on *Before the year starts* and click **Open Data**.

### Step 2. Data: what the plan stands on

* **Shows:** six questions with their answers: **42.5%** of 499,644 sign ups qualify; demand is seasonal, **1.8 times** (24,267 in November divided by 13,814 in June); it jumps from day to day, **CV 0.69**, so the waiting pool is simulated day by day; it is not growing, **-1.8%**; weekdays barely differ, Saturday 1.05 and Thursday 0.93; the January team is **2.8 times too many**, and only Vietnam is short (59 for 107). Four charts, then **3 of 3 checks pass** for data quality, with notes on 920 repaired dates and 13 budgets exactly on a threshold.
* **Say:** "Before trusting a plan, check the data. It is clean, demand is seasonal with a November peak, and day to day swings are large, which is why the waiting pool matters."
* **Proves:** **[Brief]** use of the dataset, exploratory analysis. Click a chart to show it full size.

### Step 3. Plan: choose, check, approve

Open **Plan** (the button at the end of Data).

* **Overview.** Five cards: net value $479.7M (+29.5% against keeping the January team), agents at work 2,220 (-65.7%), served 100.0%, utilization 68.9% (+44.9 points), total cost $178.5M (-37.6%). The headcount chart, then **Profit against service level**.
  * **Do:** set **Service goal** to *Profit, at least 98% served within 7 days*.
  * **Say:** "Profit only already serves 99.1 percent. Serving 98 percent within a week gives up $3.6M, 0.75 percent of net value, and needs about 101 more agents than profit only. It is a business choice, so the manager makes it here." Set the goal back to the recommended one.
  * **Proves:** **[Brief]** cost against timely support. **[Advanced]** the SLA as a choice with its price.
* **Check the plan.** "8 of 8 checks pass": no agent above 10 advertisers on any day; nobody served after more than 60 days (longest wait 35); hires and notices respect ramp up and notice; costs match the brief to the dollar; the service goal holds; CBC proved the plan optimal in 22 of 22 countries; $11.3M better than the best simple rule; on 2025's real sign ups, a plan made from 2024 reaches **99.3%** of hindsight. One note: 5 percent fewer agents would earn $1.8M more, with waits of 2.1 days instead of 1.1.
  * **Say:** "The app proves the plan rather than asking us to trust it, and it is honest about the one trade it makes."
  * **Proves:** **[Brief]** analysis and justification. **[Advanced]** verifiable optimality.
* **How it is calculated.** "106,182 advertisers served times a $45,911 average budget times 13.5 percent uplift = $658.1M; minus 26,992 paid agent months ($91.7M) and 4,741 notices at 40 percent of salary ($86.7M) = $479.7M."
  * **Say:** "Anyone can redo this with a calculator; the month by month table downloads as a CSV."
* **Try your own plan.** Pick **Germany**, keep the slider at -5, click **Score my plan**: "Your plan earns $106k more by making advertisers wait longer", 1.9 days instead of 1.3. Move the slider to +5 and score again: "$230k less".
  * **Say:** "A manager can challenge the optimizer with their own numbers. More agents always lose money; fewer agents save a little by making people wait."
* **Approve.** Set Country back to *All countries* and click **Approve this plan**. The message names the file, for example `approved_plan_all_service_98_<date>_<time>.csv`.

### Step 4. Scenario: test before the year starts

Open **Scenario**. It opens with an example already run: Germany sign ups 30% lower in Q3 move Germany's net value from $24.0M to $21.1M.

* **Do:** click **Sign ups in the USA rise 20% in Q4**.
* **Shows:** "Understood as: If sign ups rise 20% from October to December in USA, and we rebuild the plan", net value **$117.6M to $126.9M**, a chart from February where the changed months are shaded and labelled.
* **Say:** "A sentence becomes typed parameters through structured output. The manager reads how it was understood, can open *Edit the parameters* to change a value, and only then runs it. The UK example shows another lever: a 20 percent lower threshold adds $3.4M by serving advertisers with idle agents."
* **Proves:** **[Brief]** scenario explorer, sensitivity to sign up volume, other considerations. GenAI technique: structured output.

### Step 5. Memo: brief each country

Open **Memo** (the memo for the first country is already written), pick **Vietnam**, click **Write the memo**: "move from 59 to 95 agents", hire 36, net value $10.0M, served 100.0%, and "Every number matches the planner."

* **Proves:** **[Brief]** the staffing memo.

### Step 6. Assistant: ask anything

Open **Assistant** at the top of the sidebar.

* **Do:** click the example **What if sign ups in Brazil drop 30% in Q3?**, then type **And Mexico?**
* **Shows:** Brazil net value $44.9M to $41.7M (-$3.2M); then Mexico $10.5M to $9.5M (-$1.0M), with "This was a follow up, so it kept the kind of question, months and scenario from your last question." The right panel: **Numbers checked**, the tool *run_scenario*, and "**6** numbers in the answer, each matched to one of **56** planner facts; the language model wrote none of them." Under the chat box: "Answered by Offline".
* **Say:** "This is the GenAI part. The question is routed, a planner tool runs, and the answer is written with placeholders, so every figure is checked. Follow ups keep their context."
* **Proves:** **[Brief]** the planning assistant and insights; GenAI techniques: routing with structured output, tools, retrieval for rule questions, memory. **[Advanced]** the number check that blocks invented numbers.

### Step 7. Monthly update: the forecast was wrong

Go back to **This year**, set "Where are you in the year?" to **Start of March**: January and February turn to *Carried out*, March says *Decide now*, and the steps change. Click **Open Monthly update**.

* **Shows:** USA, March, sign ups 20 percent above forecast. The input check reads each number back: January 1,229 against a forecast of 1,024 (+20%), February 1,195 against 996. The result: keeping the approved plan serves everyone but after **12.9 days**; the updated plan brings waits back to **2.3 days** for $2.9M, and says "**Decide in March: hire 39 (the plan said 0)**". The chart shows April at 252 agents instead of 213.
* **Do:** click **Approve the update**; the file is named `approved_update_USA_2026-03_<date>_<time>.csv`. Then pick **April**: January and February keep the counts just approved, and the April update starts from March's.
* **Say:** "A plan is a forecast, and forecasts miss. Each month the manager types what really happened; the months done keep their decisions and the rest of the year is planned again. That is the real time loop of a monthly decision."
* **Proves:** **[Brief]** sensitivity to sign up volume. **[Advanced]** rolling monthly update with input checks.

### Step 8. Decision log: who changed what

Open **Decision log** (the button at the end of Monthly update).

* **Shows:** tiles such as decisions logged, values changed after the first proposal, changed by you, answers where a GenAI guardrail acted. Click **Only changes**: the monthly update rows, with the changed values tinted amber.
* **Say:** "Every approval, scenario and answer is logged with who was signed in, what was proposed, by the optimizer, the forecast or a language model, what adjusted it, and what was applied. Nothing the language model does is hidden."
* **Proves:** **[Advanced]** transparency between GenAI and the model.

### Step 9. Evaluation: how good is the assistant

Open **Evaluation**.

* **Shows:** the first line says that on new wording (holdout) Claude Sonnet 5.5 reads 100% of questions right and the offline keywords 28%. A chart of five assistants (Claude Sonnet 5.5, Gemma, Llama, offline, GPT 5 nano): questions read right on the main set, the holdout and the follow ups, and seconds per answer. The table names the judges of each row. Retrieval: 7 of 8 rule questions find the right passage. Plan runs: 6 runs, 1 data fingerprint, the same result.
* **Say:** "We measure the assistant on labelled questions, including a holdout written in new words, and compare five assistants. Claude Sonnet reads every new question right for under two cents; the free keywords read 28 percent. The judges were checked against a person's grades."
* **Proves:** **[Brief]** multi LLM evaluation.

## 4. Where each requirement lives

| Brief asks for | Where to show it |
|---|---|
| Agents per country per month, with hiring and notice dates | This year strip; Plan, month by month detail |
| The rules: 10 per agent, 60 day support, 60 day pool, ramp up, notice, 40 percent cost | Plan, Check the plan |
| Cost, timely support | Plan cards; Profit against service level |
| Analysis and justification | Check the plan; How it is calculated; the report |
| Sensitivity to sign up volume | Scenario; Monthly update |
| Other considerations | Scenario (UK threshold); alerts (UAE, notice rules) |
| Easy dataset swap | `config/staffpilot.toml` (one line) |
| GenAI app with at least two techniques | Assistant, Scenario, Memo; all six techniques |
| Assistant, insights, scenario explorer, memo | Assistant, Data, Scenario, Memo |
| Executed notebook | `notebooks/StaffPilot_Topic3.ipynb` |

| Beyond the brief | Where |
|---|---|
| Profit only against an SLA, with its price | Plan, Service goal |
| Proof of optimality, a recalculation, a manager's own plan | Plan tabs |
| Rolling monthly update with input checks, chained month to month | Monthly update |
| Decision log of proposed, adjusted and applied | Decision log |
| Number check, follow up memory, model fallbacks | Assistant |
| Local and online model evaluation, judge checked by hand | Evaluation; README |

## 5. Questions to expect

* **Is the plan really optimal?** The solver proves it optimal for its model in 22 of 22 countries, and the plan beats every simple rule. Scored day by day, 5 percent fewer agents would earn $1.8M more with longer waits; the app shows that as a note, because how much a day of waiting is worth is the manager's call.
* **What if the forecast is wrong?** Use the Monthly update every month. With 20 percent more sign ups in the USA, keeping the plan stretches waits to 12.9 days; the update hires 39 in March.
* **Can the language model make up a number?** No number it writes reaches the screen unchecked. It writes placeholders; the planner fills them; anything else is rejected, and after one retry the answer is replaced by a template.
* **Does it need an API key?** No. Offline mode uses a keyword reader and templates with the same planner and the same checks; it is free and is what the tests use. A model reads new wording far better (88 percent against 28 on the holdout).
* **Why cut two thirds of the team?** The January team is 2.8 times what the busiest weeks need; every notice is paid back within the year. The alerts remind the manager about notice rules and communication, which the model does not price.
* **Why does the data plan 2026 when the brief says 2025?** The public copy covers 2024 and 2025, so the next year is 2026. With the official file the same code plans 2025; it is one line in `config/staffpilot.toml`.

## 6. If something goes wrong

* A page looks frozen after a restart: reload the browser tab.
* The first start is slow: the plans are being solved; later starts read them from `.cache/` in a few seconds.
* A model call fails: the app falls back to the offline reader and the template answer, and says so in the right panel.

## 7. The three minute version

| Time | Page | Do | Say in one line |
|---|---|---|---|
| 0:00 | This year | nothing | $479.7M, $109.3M more than keeping the team; 4,741 notices in January |
| 0:25 | Plan | Service goal: 98% within 7 days | Speed costs $3.6M; it is the manager's choice |
| 0:45 | Plan, Check the plan | read | 8 of 8 checks pass, optimal in 22 of 22, 99.3% of hindsight |
| 1:05 | Plan, Try your own plan | Germany, Score my plan | Fewer agents save $106k by making people wait; more agents lose |
| 1:20 | Scenario | Sign ups in the USA rise 20% in Q4 | A sentence becomes parameters: $117.6M to $126.9M |
| 1:40 | Assistant | Brazil example, then "And Mexico?" | Follow ups keep context; 6 numbers checked, none written by the model |
| 2:05 | This year, Monthly update | Start of March, Open Monthly update | 20% more sign ups: hire 39 in March instead of 0 |
| 2:30 | Monthly update | Approve the update | Saved by country, month and time |
| 2:40 | Decision log | Only changes | Proposed, adjusted, applied: nothing hidden |
| 2:50 | Memo | Vietnam | 59 to 95 agents; every number matches the planner |
