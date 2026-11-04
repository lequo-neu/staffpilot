# Presentation script

A talk of about ten minutes that follows a staffing manager's year, from the question Google asks to the last decision of the month. Each slide opens with one sentence that leads in from the slide before, names the question the slide answers, and says what to show and what to say. Tags: **[Brief]** is a requirement of the brief; **[Advanced]** goes beyond it. A three minute cut for the video is at the end.

Before the talk: start the app (`python -m staffpilot app`), sign in and change the first password, keep **Offline** in Settings, and open the pages once so they are ready. Screenshots of every slide are in [`docs/Assets/`](Assets).

## 1. The problem

* **Lead in:** "Google gives every eligible new advertiser a support agent for 60 days, and each country has to decide how many agents to employ each month."
* **Question:** what decision does the manager face?
* **Show:** a title slide with the four rules in plain words: an advertiser is eligible above a budget threshold; an agent holds at most 10 advertisers; an advertiser waits at most 60 days; hiring takes a month and a notice costs 40% of a salary.
* **Say:** "Too many agents and we pay for idle people; too few and advertisers wait and spend less. The brief asks for a month by month plan for 22 countries, and a GenAI application that puts it in a manager's hands."
* **Proves:** **[Brief]** the problem as stated.

## 2. The answer in one screen

* **Lead in:** "Let us start with the answer, the way a manager would open the tool on the first morning of the year."
* **Question:** what should we do this year?
* **Show:** This year ([R1](Assets/R1.png)).
* **Say:** "$479.7M of net value, $109.3M or 29.5% more than keeping the January team. The team goes from 6,474 to about 2,220 agents, everyone is still served, after 1.1 days on average. The big decision is in January: 4,741 notices. Vietnam is the one country that must hire, from 59 to 95."
* **Proves:** **[Brief]** agents per country and month with the dates of hires and notices. **[Advanced]** a home page organised around the manager's year, with alerts that name the numbers and open the page to act on.

## 3. What the data says

* **Lead in:** "Before trusting a plan, the manager wants to know what it stands on."
* **Question:** what does demand look like, and is the team the right size?
* **Show:** Data ([R2](Assets/R2.png)).
* **Say:** "Six questions, each with its answer. Demand is seasonal: November is 1.8 times June. It jumps from day to day, so we simulate the waiting pool day by day. It is not growing. And the January team is 2.8 times what the busiest 60 days need; only Vietnam is short."
* **Proves:** **[Brief]** use of the provided data and the reason the plan cuts.

## 4. The plan, and proof that it follows the rules

* **Lead in:** "So the team should shrink. The next question is whether the plan we propose is right."
* **Question:** does the plan keep every rule of the brief?
* **Show:** Plan ([R3](Assets/R3.png)), then **Check the plan** ([R5](Assets/R5.png)).
* **Say:** "Every rule is checked day by day by a simulator: no agent above 10 advertisers, nobody past 60 days, ramp up and notice respected, costs as in the brief. The solver proved the plan optimal in all 22 countries, and planned from one year and scored on the next, it reaches 99.3% of what hindsight would give."
* **Proves:** **[Brief]** the dynamic staffing model and the rules. **[Advanced]** an independent simulator that checks the optimizer, and a backtest.

## 5. Where each number comes from

* **Lead in:** "A manager will not sign off on a number they cannot trace."
* **Question:** how is net value calculated?
* **Show:** **How it is calculated** ([A6](Assets/A6.png)), and the architecture diagram in the README.
* **Say:** "Net value is uplift minus salaries minus notice cost. Uplift is the advertisers served times their budget times 13.5%, the expected value of the brief's distribution. Under the hood: a forecast, one integer program per country, and a day by day simulator that produces every number you see."
* **Proves:** **[Brief]** analysis and justification. **[Advanced]** every card rebuilt from its inputs.

## 6. Profit, or profit with a service level

* **Lead in:** "The plan maximizes value, but a manager may care how fast advertisers are served."
* **Question:** how much does faster service cost?
* **Show:** Plan with the **Service goal** list ([A4](Assets/A4.png)).
* **Say:** "Serving at least 98% of advertisers costs almost nothing, $0.03M. Serving all of them within a week costs $3.6M and about 87 more agents. The model computes the price; the manager chooses."
* **Proves:** **[Brief]** cost against timely support. **[Advanced]** profit only against a service level agreement, each its own optimization.

## 7. What if I staff differently?

* **Lead in:** "Some managers will want to try their own numbers before they believe the model."
* **Question:** is my own headcount better or worse?
* **Show:** **Try your own plan** ([A7](Assets/A7.png)), Germany at 5% fewer agents.
* **Say:** "Any headcount is scored by the same simulator. Fewer agents save a little money but make advertisers wait longer; more agents always earn less. The tool says which trade it is, in numbers."
* **Proves:** **[Advanced]** the manager can test the plan instead of taking it on trust.

## 8. What if the market changes?

* **Lead in:** "The plan rests on a forecast, so the next worry is a market that moves."
* **Question:** how does the plan hold up when sign ups change?
* **Show:** Scenario ([R8](Assets/R8.png)): type "Sign ups in the USA rise 20% in Q4", read, run.
* **Say:** "A language model turns the sentence into parameters, which the manager can check and edit before the run. The plan is rebuilt: USA net value goes from $117.6M to $126.9M, with about 28 more agents from October. Across all countries we tested 70% to 130% of forecast: replanning saves money when demand falls and keeps the wait at a day when it rises."
* **Proves:** **[Brief]** sensitivity analysis and a scenario explorer. **[Advanced]** the parameters are shown before the run.

## 9. Telling each country

* **Lead in:** "Once the plan is approved, 22 country managers need to hear what it means for them."
* **Question:** what does each country manager need to know?
* **Show:** Memo for Vietnam ([R10](Assets/R10.png)).
* **Say:** "One page each: the headcount change, when to hire or give notice, cost and value, why, and what to watch. The language model writes the words; every number in it is checked against the planner, as the last line says."
* **Proves:** **[Brief]** the staffing memo generator.

## 10. Asking anything, safely

* **Lead in:** "Between plans, a manager has questions, and the assistant answers them in plain English."
* **Question:** why is a number what it is, and can the AI be trusted with numbers?
* **Show:** Assistant ([R9](Assets/R9.png)): "What if sign ups in Brazil drop 30% in Q3?", then "And Mexico?"
* **Say:** "The follow up keeps the scenario and changes the country. The panel shows how the answer was built: six numbers, each matched to one of 56 planner facts. The model writes placeholders, the planner fills them, and a number with no source, or from the wrong country, is rejected. Twice rejected, a template answer is used."
* **Proves:** **[Brief]** a planning assistant with at least two course techniques (structured output, LangChain tools, RAG, agents, prompts, API calls). **[Advanced]** the number check.

## 11. The month the forecast was wrong

* **Lead in:** "Now it is March, and January and February did not go as forecast."
* **Question:** what should we change now that reality differs from the plan?
* **Show:** This year, pick **Start of March**, then Monthly update ([A11](Assets/A11.png)).
* **Say:** "The manager types the real sign ups and the agents really on staff. Each number is checked as it is typed. The months done keep their decisions; only the rest of the year is solved again. With 20% more sign ups in the USA, keeping the plan would make advertisers wait almost 13 days; the update says hire 39 in March instead of none."
* **Proves:** **[Brief]** other considerations. **[Advanced]** a rolling monthly update with input checks.

## 12. Who decided what

* **Lead in:** "When a plan cuts thousands of jobs, someone will ask who decided, and what the AI changed."
* **Question:** who approved each decision, and what did the model propose?
* **Show:** Decision log ([A12](Assets/A12.png)) and the sign in page ([A14](Assets/A14.png)).
* **Say:** "Every approval, scenario and answer is logged: what the optimizer, the forecast or a language model proposed, what a check or the manager changed, what was applied, and who was signed in."
* **Proves:** **[Advanced]** transparency between GenAI and the model, and traceable approvals.

## 13. How good is the assistant

* **Lead in:** "Last, the AI part itself has to be measured, not assumed."
* **Question:** which model should answer, and is it worth paying for?
* **Show:** Evaluation ([A13](Assets/A13.png)).
* **Say:** "82 labelled questions, including 32 in new words that the keywords never saw. Claude Sonnet reads all of them right for under two cents a question; a free local model reads 88%, the keywords 28%. The AI judges were checked against a person's grades, so we rank models on the labelled accuracy."
* **Proves:** **[Advanced]** multi LLM evaluation with a holdout, cross model judges and a human check.

## 14. Close

* **Lead in:** "To sum up the year in one sentence."
* **Say:** "StaffPilot cuts the team by two thirds, keeps every advertiser served and adds $109M, and every number the AI says comes from the model. What we are proudest of is that a manager can check each number instead of trusting it. The open question is how long uplift lasts, which only Google can answer; the plan holds either way."
* **Show:** the README.

## Three minute cut for the video

| Time | Slide | One line |
|---|---|---|
| 0:00 | 2 | $479.7M, $109.3M more than keeping the team; 4,741 notices in January |
| 0:25 | 4 | Every rule checked day by day; optimal in 22 of 22; 99.3% of hindsight |
| 0:50 | 6 | Serving everyone within a week costs $3.6M; the manager chooses |
| 1:10 | 8 | A sentence becomes parameters; USA Q4 plus 20%: $117.6M to $126.9M |
| 1:35 | 10 | Follow ups keep context; six numbers checked, none written by the model |
| 2:05 | 11 | March, 20% more sign ups: hire 39 instead of 0 |
| 2:30 | 12 | Proposed, changed, applied, and who approved |
| 2:45 | 13 | Claude 100% on new wording, keywords 28% |
