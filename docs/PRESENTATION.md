# Presentation script

Two scripts that follow a staffing manager's year, from the question Google asks to the last decision of the month:

* **The video script** below is read aloud while the screen is recorded. As written it runs about 3 minutes 20 seconds (about 440 words at 145 words a minute, with short pauses for clicks); the three cuts under "If it runs long" bring it to the 3 minutes the brief asks for. The brief asks the video to show the product, the architecture and the part we are most proud of: the architecture is scene 6, the proudest part is scene 8.
* **The ten minute talk** further down has one slide per question, for a live presentation.

## Video script

### Before you record

* Start the app with `python -m staffpilot app`, open http://127.0.0.1:7860 in a window of about 1440 by 900, and sign in as `kevin`.
* In **Settings**, keep **Offline**: it is free and answers at once. A paid model takes 8 to 12 seconds per answer, which a three minute video cannot spare.
* On **Plan**, keep **All countries** with the recommended goal and click **Approve this plan**, so This year shows the approval and the decision log has your name.
* Run each slow step once, so it answers at once while you record: on **Scenario**, the example "Sign ups in the USA rise 20% in Q4", then **Run the scenario**; on **Monthly update**, USA, March and 20 percent (the defaults), then **Update the plan**; on **Memo**, Vietnam, then **Write the memo**. Then click **New chat** on Assistant and go back to **This year**.
* In a second browser tab, open the README on GitHub at **How it works**, so the diagram is already drawn.
* Turn on Do Not Disturb, hide the bookmarks bar, and record only the browser window.
* Read the script aloud once with a timer. If it runs past 3:30, use the cuts at the end of this section.

### 1. The problem (0:00)

**Do:** stay on **This year**.

> Hi, we are the Seven Team, and this is StaffPilot. Google gives every eligible new advertiser a support agent for 60 days, and 22 countries must decide how many agents to employ each month. Too many waste salary; too few make advertisers wait.

### 2. The answer (0:18)

**Do:** point at the net value tile, then the agents tile, then January in the month strip (Hire 11, Notice 4,741).

> The first screen gives the answer for the year: 479.7 million dollars of net value, 109 million or 29.5 percent more than keeping the January team. The team goes from 6,474 agents to about 2,220 a month, and everyone is still served. Most notices go out in January.

### 3. The data (0:39)

**Do:** click **Data**. Point at "Is demand seasonal?", "Does demand jump from day to day?" and "Is the January team the right size?".

> Why cut so much? Demand is seasonal: November is 1.8 times June. It jumps from day to day, so we simulate the waiting pool daily. And the January team is 2.8 times what the busiest 60 days need.

### 4. The proof (0:57)

**Do:** click **Plan**, then the tab **Check the plan**. Scroll slowly down the eight checks.

> Is the plan right? A day by day simulator replays it against every rule of the brief, and eight of eight checks pass. The solver proved it optimal in all 22 countries, and on a year it never saw, it reaches 99.3 percent of hindsight.

### 5. The service goal (1:17)

**Do:** click the tab **Overview** and open **Every service goal**. Point at the row "within 7 days".

> The manager also picks the service goal: serving everyone within a week costs 3.6 million dollars more.

### 6. The architecture (1:26)

**Do:** switch to the GitHub tab. Point at the left box of the diagram, then the right box.

> Under the hood, the planning core has no language model: a forecast, one integer program per country, and a simulator behind every number. The GenAI side reads questions with structured output, calls LangChain tools on the planner, and finds rules with RAG.

### 7. The scenario (1:45)

**Do:** back to the app. Click **Scenario**, click the example "Sign ups in the USA rise 20% in Q4", click **Read the scenario** (the "Understood as" line appears), then **Run the scenario**.

> If the market moves, I describe it in one sentence. The app turns it into parameters I can check, then rebuilds the plan: USA net value goes from 117.6 to 126.9 million.

### 8. The assistant, and the part we are most proud of (2:00)

**Do:** click **Assistant**. Click the example "What if sign ups in Brazil drop 30% in Q3?". When it answers, type `And Mexico?` and press Enter. Point at the panel **How this answer was built**: "6 numbers in the answer, each matched to one of 56 planner facts".

> Or the manager just asks. What if sign ups in Brazil drop 30 percent in Q3? And Mexico? The follow up keeps the scenario. This panel is the part we are most proud of: six numbers, each matched to a planner fact. Even with Claude or GPT, the model writes only placeholders, the planner fills them in, and a number without a source is rejected.

### 9. The memo (2:29)

**Do:** click **Memo**; Vietnam is already written. Point at the last line, "Every number matches the planner."

> Each country gets a one page memo, and every number in it matches the planner.

### 10. The monthly update (2:36)

**Do:** click **Monthly update** (USA, March, 20 percent). Point at "Keep the approved plan ... 12.9 days", then "Decide in March: hire 39".

> Now it is March, and USA sign ups came in 20 percent above forecast. Keeping the plan, advertisers would wait 12.9 days. The update keeps the months already done and says: hire 39 now. The wait drops to 2.3 days.

### 11. The log and the evaluation (2:55)

**Do:** click **Decision log** and point at the user column. Then click **Evaluation** and point at the first line.

> Every decision is logged, with who approved it. And we measured the AI itself: on 32 questions in new wording, Claude Sonnet reads every one right. Keywords alone read 28 percent.

### 12. Close (3:10)

**Do:** click **This year** and stop moving the mouse.

> StaffPilot cuts the team by two thirds, keeps every advertiser served, and adds 109 million dollars. And every number the AI says comes from the model. Thank you.

The script ends at about 3:20 at 145 words a minute.

### If it runs long

* Drop scene 9 (the memo): 7 seconds.
* Drop scene 5 (the service goal): 8 seconds.
* In scene 4, stop after "eight of eight checks pass": 8 seconds.

All three together bring the video to about 3:00.

### What each scene proves

| Scene | Requirement of the brief | Beyond the brief |
|---|---|---|
| 2 The answer | agents per country and month, with the dates of hires and notices | a home page built around the manager's year |
| 3 The data | use of the provided data | six questions with their answers |
| 4 The proof | the staffing model and its rules | a day by day simulator that checks the optimizer; a backtest on an unseen year |
| 5 The service goal | cost against timely support | each service level is its own optimization |
| 6 The architecture | architecture diagram; two or more course techniques | the planning core never uses a language model |
| 7 The scenario | sensitivity analysis and a scenario explorer | the parameters are shown before the run |
| 8 The assistant | a planning assistant | follow ups that keep context; the number check |
| 9 The memo | the staffing memo generator | every number checked against the planner |
| 10 The monthly update | other considerations | a rolling update with input checks |
| 11 The log and the evaluation | | a decision log with the user; multi model evaluation with a holdout |

## Ten minute talk

Each slide opens with one sentence that leads in from the slide before, names the question the slide answers, and says what to show and what to say. Tags: **[Brief]** is a requirement of the brief; **[Advanced]** goes beyond it. Screenshots of every slide are in [`docs/Assets/`](Assets).

### 1. The problem

* **Lead in:** "Google gives every eligible new advertiser a support agent for 60 days, and each country has to decide how many agents to employ each month."
* **Question:** what decision does the manager face?
* **Show:** a title slide with the four rules in plain words: an advertiser is eligible above a budget threshold; an agent holds at most 10 advertisers; an advertiser waits at most 60 days; hiring takes a month and a notice costs 40% of a salary.
* **Say:** "Too many agents and we pay for idle people; too few and advertisers wait and spend less. The brief asks for a month by month plan for 22 countries, and a GenAI application that puts it in a manager's hands."
* **Proves:** **[Brief]** the problem as stated.

### 2. The answer in one screen

* **Lead in:** "Let us start with the answer, the way a manager would open the tool on the first morning of the year."
* **Question:** what should we do this year?
* **Show:** This year ([R1](Assets/R1.png)).
* **Say:** "$479.7M of net value, $109.3M or 29.5% more than keeping the January team. The team goes from 6,474 to about 2,220 agents, everyone is still served, after 1.1 days on average. The big decision is in January: 4,741 notices. Vietnam is the one country that must hire, from 59 to 95."
* **Proves:** **[Brief]** agents per country and month with the dates of hires and notices. **[Advanced]** a home page organised around the manager's year, with alerts that name the numbers and open the page to act on.

### 3. What the data says

* **Lead in:** "Before trusting a plan, the manager wants to know what it stands on."
* **Question:** what does demand look like, and is the team the right size?
* **Show:** Data ([R2](Assets/R2.png)).
* **Say:** "Six questions, each with its answer. Demand is seasonal: November is 1.8 times June. It jumps from day to day, so we simulate the waiting pool day by day. It is not growing. And the January team is 2.8 times what the busiest 60 days need; only Vietnam is short."
* **Proves:** **[Brief]** use of the provided data and the reason the plan cuts.

### 4. The plan, and proof that it follows the rules

* **Lead in:** "So the team should shrink. The next question is whether the plan we propose is right."
* **Question:** does the plan keep every rule of the brief?
* **Show:** Plan ([R3](Assets/R3.png)), then **Check the plan** ([R5](Assets/R5.png)).
* **Say:** "Every rule is checked day by day by a simulator: no agent above 10 advertisers, nobody past 60 days, ramp up and notice respected, costs as in the brief. The solver proved the plan optimal in all 22 countries, and planned from one year and scored on the next, it reaches 99.3% of what hindsight would give."
* **Proves:** **[Brief]** the dynamic staffing model and the rules. **[Advanced]** an independent simulator that checks the optimizer, and a backtest.

### 5. Where each number comes from

* **Lead in:** "A manager will not sign off on a number they cannot trace."
* **Question:** how is net value calculated?
* **Show:** **How it is calculated** ([A6](Assets/A6.png)), and the architecture diagram in the README.
* **Say:** "Net value is uplift minus salaries minus notice cost. Uplift is the advertisers served times their budget times 13.5%, the expected value of the brief's distribution. Under the hood: a forecast, one integer program per country, and a day by day simulator that produces every number you see."
* **Proves:** **[Brief]** analysis and justification. **[Advanced]** every card rebuilt from its inputs.

### 6. Profit, or profit with a service level

* **Lead in:** "The plan maximizes value, but a manager may care how fast advertisers are served."
* **Question:** how much does faster service cost?
* **Show:** Plan with the **Service goal** list ([A4](Assets/A4.png)).
* **Say:** "Serving at least 98% of advertisers costs almost nothing, $0.03M. Serving all of them within a week costs $3.6M and about 87 more agents. The model computes the price; the manager chooses."
* **Proves:** **[Brief]** cost against timely support. **[Advanced]** profit only against a service level agreement, each its own optimization.

### 7. What if I staff differently?

* **Lead in:** "Some managers will want to try their own numbers before they believe the model."
* **Question:** is my own headcount better or worse?
* **Show:** **Try your own plan** ([A7](Assets/A7.png)), Germany at 5% fewer agents.
* **Say:** "Any headcount is scored by the same simulator. Fewer agents save a little money but make advertisers wait longer; more agents always earn less. The tool says which trade it is, in numbers."
* **Proves:** **[Advanced]** the manager can test the plan instead of taking it on trust.

### 8. What if the market changes?

* **Lead in:** "The plan rests on a forecast, so the next worry is a market that moves."
* **Question:** how does the plan hold up when sign ups change?
* **Show:** Scenario ([R8](Assets/R8.png)): type "Sign ups in the USA rise 20% in Q4", read, run.
* **Say:** "The sentence is turned into parameters, which the manager can check and edit before the run. The plan is rebuilt: USA net value goes from $117.6M to $126.9M, with more agents from October. Across all countries we tested 70% to 130% of forecast: replanning saves money when demand falls and keeps the wait at a day when it rises."
* **Proves:** **[Brief]** sensitivity analysis and a scenario explorer. **[Advanced]** the parameters are shown before the run.

### 9. Telling each country

* **Lead in:** "Once the plan is approved, 22 country managers need to hear what it means for them."
* **Question:** what does each country manager need to know?
* **Show:** Memo for Vietnam ([R10](Assets/R10.png)).
* **Say:** "One page each: the headcount change, when to hire or give notice, cost and value, why, and what to watch. The language model writes the words; every number in it is checked against the planner, as the last line says."
* **Proves:** **[Brief]** the staffing memo generator.

### 10. Asking anything, safely

* **Lead in:** "Between plans, a manager has questions, and the assistant answers them in plain English."
* **Question:** why is a number what it is, and can the AI be trusted with numbers?
* **Show:** Assistant ([R9](Assets/R9.png)): "What if sign ups in Brazil drop 30% in Q3?", then "And Mexico?"
* **Say:** "The follow up keeps the scenario and changes the country. The panel shows how the answer was built: six numbers, each matched to one of 56 planner facts. The model writes placeholders, the planner fills them, and a number with no source, or from the wrong country, is rejected. Twice rejected, a template answer is used."
* **Proves:** **[Brief]** a planning assistant with at least two course techniques (structured output, LangChain tools, RAG, agents, prompts, API calls). **[Advanced]** the number check.

### 11. The month the forecast was wrong

* **Lead in:** "Now it is March, and January and February did not go as forecast."
* **Question:** what should we change now that reality differs from the plan?
* **Show:** This year, pick **Start of March**, then Monthly update ([A11](Assets/A11.png)).
* **Say:** "The manager types the real sign ups and the agents really on staff. Each number is checked as it is typed. The months done keep their decisions; only the rest of the year is solved again. With 20% more sign ups in the USA, keeping the plan would make advertisers wait almost 13 days; the update says hire 39 in March instead of none."
* **Proves:** **[Brief]** other considerations. **[Advanced]** a rolling monthly update with input checks.

### 12. Who decided what

* **Lead in:** "When a plan cuts thousands of jobs, someone will ask who decided, and what the AI changed."
* **Question:** who approved each decision, and what did the model propose?
* **Show:** Decision log ([A12](Assets/A12.png)) and the sign in page ([A14](Assets/A14.png)).
* **Say:** "Every approval, scenario and answer is logged: what the optimizer, the forecast or a language model proposed, what a check or the manager changed, what was applied, and who was signed in."
* **Proves:** **[Advanced]** transparency between GenAI and the model, and traceable approvals.

### 13. How good is the assistant

* **Lead in:** "Last, the AI part itself has to be measured, not assumed."
* **Question:** which model should answer, and is it worth paying for?
* **Show:** Evaluation ([A13](Assets/A13.png)).
* **Say:** "82 labelled questions, including 32 in new words that the keywords never saw. Claude Sonnet reads all of them right for under two cents a question; a free local model reads 88%, the keywords 28%. A person graded the local judges' answers and found the judges too lenient, so we rank models on the labelled accuracy."
* **Proves:** **[Advanced]** multi LLM evaluation with a holdout, cross model judges, and a person's check of the local judges.

### 14. Close

* **Lead in:** "To sum up the year in one sentence."
* **Say:** "StaffPilot cuts the team by two thirds, keeps every advertiser served and adds $109M, and every number the AI says comes from the model. What we are proudest of is that a manager can check each number instead of trusting it. The open question is how long uplift lasts, which only Google can answer; the plan holds either way."
* **Show:** the README.
