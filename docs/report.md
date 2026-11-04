# StaffPilot: analysis report

Seven Team-5374

IE5374 Module 7 Hackathon, Topic 3, Dynamic Agent Staffing Optimization. All numbers come from `notebooks/StaffPilot_Topic3.ipynb` run on the public copy of the data (sign ups for 2024 and 2025, planning year 2026). With the official IE5374 file the same code plans 2025; rerun before submission.

*AI assisted: drafted with an AI coding assistant; every number was copied from an executed cell and checked by the team.*

Each method in detail: [METHODS.md](METHODS.md). The evaluation in full: [EVALUATION.md](EVALUATION.md).

## 1. Problem and headline

Google supports eligible new advertisers with dedicated agents for 60 days. Each agent holds at most ten advertisers, eligible advertisers wait at most 60 days, new hires need a month of ramp up, and a notice costs 40 percent of annual salary plus a month of pay. The task is a monthly headcount per country that balances cost, timely support and the ability to adjust.

On 1 January the 22 countries employ 6,474 agents, while the busiest 60 days of demand need about 2,333 and the plan keeps 2,220 in an average month. Only Vietnam is short (59 agents for a need of about 107). The recommended plan raises expected net value for the year from $370.4M (keep January headcount) to $479.7M, a gain of $109.3M or 30 percent, serves every eligible advertiser, and keeps the average wait at 1.1 days.

## 2. Key decisions

**Model the rules exactly, then optimize on a close approximation.** A day by day simulator implements the brief (60 day support, 60 day wait limit, ten per agent, ramp up, notice) and is the only source of reported numbers. A slot counts as free only if it exists for the whole support period, so an agent under notice takes no new advertisers. The optimizer is a mixed integer program per country: monthly hires and notices, weekly advertiser flows, and three months of lookahead so December is not cut only because the model ends there.

**What we got wrong first.** Our first simulator filled free slots greedily, and every plan that cut headcount then broke the ten advertiser rule. We blamed the optimizer's monthly flows and rebuilt them weekly. The real fix was the dispatch rule above. With it, a monthly flow model is feasible too and earns $1.4M more, but advertisers wait almost twice as long (2.0 versus 1.1 days). We keep weekly flows for timely support and report the trade.

**Count value for the sign up cohort.** Uplift is attributed to advertisers who sign up in the planning year, including December sign ups served in January. Counting it in the month of service instead made a plan rebuilt for lower demand look worse than the plan it replaced, an accounting artefact at the year boundary.

**Cut early, hire back a little.** In every overstaffed country the plan gives most notices in January and hires a few agents back in August to October for the fourth quarter peak (Germany: 602 agents, 516 notices, back to 102 by October). A notice costs about 4.8 months of salary plus the notice month, while keeping an idle agent from February to August costs seven months.

**Grow Vietnam now.** From 59 to 95 agents, with the first hires decided in January.

**Serve the UAE anyway.** In the UAE one agent's yearly uplift is below its salary, so the pure value plan lets all 309 agents go and serves no one. The recommended plan adds a 98 percent service floor; it keeps about 40 agents there and costs $0.03M in total.

**Profit only or profit with a service level.** The service goal is a choice for the manager, not a hidden setting. Profit only already serves 99.1 percent; the 98 percent floor costs $0.03M. Speed is the real trade: 98 percent served within 7 days costs $3.6M (0.75 percent of net value) and about 87 more agents, and raises the share served within a week from 92.1 to 100.0 percent. The goal is a soft constraint that counts only on time service, so an impossible goal still gives a plan.

**Plan again every month.** The forecast will be wrong, so the plan is updated with actual numbers: the months done keep their decisions, the rest of the forecast is scaled by the recent error, and only the remaining months are solved again. If Germany's January sign ups come in 40 percent above forecast, keeping the plan serves 87.7 percent with a 32 day wait; the update hires 31 agents in February, serves everyone within about 2 days and adds $5.5M.

**Let the manager check it.** The Plan page tests the plan against every brief rule with its numbers, rebuilds net value from its inputs and scores any headcount the manager types with the same simulator. It also reports the one place the plan is not the cheapest: 5 percent fewer agents would still keep every rule and earn $1.8M more, at the cost of the average wait going from 1.1 to 2.1 days, because the model prefers early service.

**The optimizer versus a good heuristic.** Matching last month's demand reaches $468.3M. Almost all of the value comes from removing excess agents; the optimizer adds $11.3M and, unlike the heuristics, handles service floors, hiring caps and scenarios in one model.

## 3. Results

| Policy | Net value | Uplift | Salary | Firing | Service | Avg agents | Mean wait |
|---|---|---|---|---|---|---|---|
| Keep January headcount | $370.4M | $656.6M | $286.2M | $0 | 99.3% | 6,474 | 1.1 days |
| Match last month's demand | $468.3M | $658.1M | $91.7M | $98.0M | 100.0% | 2,133 | 1.7 days |
| One cut to peak plus 10 percent | $464.1M | $658.1M | $121.7M | $72.3M | 100.0% | 2,978 | 0.0 days |
| Optimized for net value | $479.7M | $657.6M | $90.8M | $87.1M | 99.1% | 2,206 | 1.1 days |
| **Recommended (98 percent floor)** | **$479.7M** | **$658.1M** | **$91.7M** | **$86.7M** | **100.0%** | **2,220** | **1.1 days** |

Uplift is almost identical under every policy, because nearly every eligible advertiser is served either way. The whole gain is lower cost.

**Backtest on real sign ups.** Planning 2025 from 2024 data only and simulating on the actual 2025 sign ups, the plan reaches $470.9M, 99.3 percent of the $474.2M a hindsight plan achieves with the same optimizer, against $365.9M for keeping January headcount. The January headcount table is reused for 2025, which is an assumption.

## 4. Assumptions and their impact

| Assumption | Default | If changed |
|---|---|---|
| A1 Uplift base | annual budget, once, for the sign up cohort | 60 day window only: hold $-178.3M, reactive $-81.6M, optimized $-67.0M |
| A3 Pool on 1 January | empty | last 60 days of history waiting: $606.3M, 2,576 agents, mean wait 8 days |
| A8 Pool order | first in, first out | highest budget first: $478.7M |
| A9 Preference for early service | 1 percent of uplift per week waited, optimizer only | none: $482.8M, mean wait 3.0 days instead of 1.1 |

A1 is the decision that matters most. If uplift counts only during the 60 days of support, every policy loses money. The optimized plan still beats holding headcount by $111M and gives even more notices (4,962 against 4,756), so the case for cutting gets stronger, not weaker. What changes is whether new advertiser support pays for itself at all, which only Google can answer; we would raise that before any notices are given.

A9 shows the price of timely support: the preference for early service costs about $3M of simulated value and cuts the average wait to a third.

## 5. Sensitivity

Sign ups scaled from 70 to 130 percent of forecast, comparing the unchanged plan with a plan rebuilt for each level:

| Sign ups vs forecast | Net value, current plan | Net value, replanned | Mean wait, current plan | Mean wait, replanned |
|---|---|---|---|---|
| 70% | $281.1M | $293.1M | 0.0 days | 1.1 days |
| 80% | $347.5M | $355.5M | 0.0 days | 1.1 days |
| 90% | $413.0M | $417.1M | 0.2 days | 1.1 days |
| 100% | $479.7M | $479.7M | 1.1 days | 1.1 days |
| 110% | $545.2M | $541.1M | 3.4 days | 1.1 days |
| 120% | $609.8M | $602.1M | 12.0 days | 1.1 days |
| 130% | $644.8M | $663.1M | 22.2 days | 1.1 days |

When demand falls, replanning earns more because surplus agents leave. When it rises 10 to 20 percent, the unchanged plan earns slightly more on paper only because advertisers wait longer (up to 12 days on average); replanning spends about $4M to $8M to keep waits at a day. At 130 percent the unchanged plan starts losing advertisers (95 percent served) and replanning is $18M better. The plan should be refreshed monthly; one month of ramp up is short enough to react.

Monte Carlo (20 runs, daily sign ups resampled from the same calendar month in history, uplift drawn per advertiser) gives a mean net value of $479.8M, with a 10th to 90th percentile range of $477.4M to $482.0M. Service is 99.1 percent for the value plan in every run. Day to day noise is large (coefficient of variation near 0.7), but the 60 day pool absorbs it.

## 6. Other considerations

* **Lower the threshold instead of paying idle agents.** A 20 percent lower eligibility threshold adds the following, using agents that would otherwise be let go:

  | Country | Added net value |
  |---|---|
  | USA | $9.0M |
  | UK | $3.4M |
  | Germany | $3.4M |
  | France | $2.5M |
  | Mexico | $0.9M |

  A rough estimate before modelling suggested far more. The model respects capacity and timing, and gives these smaller and more credible numbers.
* **The UAE.** Support does not pay for itself at current salaries; we keep it because it costs very little and market presence matters.
* **People and law.** Cutting about two thirds of the workforce carries morale, legal and employer brand costs that the model does not price. Notice periods in several countries are longer than one month; the notice length is a setting.
* **Ramp up productivity.** New agents are assumed fully productive after one month. Partial capacity in the second month would raise the fourth quarter hires slightly.
* **Fairness of the pool.** Serving the highest budgets first changes value little but systematically delays small advertisers.

## 7. The GenAI application

StaffPilot gives a country manager the model without a spreadsheet.

How an answer is built:
1. A question is read into a typed `RoutedQuery`: intent, countries, months, and a `ScenarioParams` for what if questions.
2. The tool for that intent runs.
3. The answer is written with `{{fact}}` placeholders, which are filled from the tool output.
4. Any number that no tool produced, or that belongs to a different country, is rejected. The model gets one retry, and after that a template answer is used.

Other features:
* It writes a memo for each country.
* It answers questions about the rules with BM25 retrieval and citations.
* It remembers the last four turns of a chat, so "And Mexico?" after a Brazil scenario reruns that scenario for Mexico. On 10 labelled follow ups the offline router gets the intent right for 9.
* It gives the same tools to a LangChain `create_agent` chat, which has memory and chooses which tools to call.
* A manager approves a plan in the app before it is saved, and every approval, scenario and answer goes into a decision log. Each row separates what was proposed (by the optimizer, the forecast or a language model reading a sentence), what adjusted it (the simulator check, a monthly update, a GenAI guardrail such as the number check, or the manager) and what was applied, so nothing the model does is hidden.

The evaluation uses 40 labelled questions and a 32 question holdout:

| Holdout (32 questions in new words) | Intent | Scenario | Grounded | Seconds | Cost per question |
|---|---|---|---|---|---|
| Keyword router (offline) | 28% | 0% | 100% | 0.0 | free |
| Llama 3.1 8B (local) | 38% | 11% | 94% | 11 | free |
| Gemma 4 E4B (local) | 88% | 67% | 75% | 66 | free |
| GPT 5 nano | 84% | 100% | 84% | 12 | $0.001 |
| Claude Sonnet 5.5 | 100% | 100% | 100% | 8 | $0.016 |

The keyword router was written against the main set, where it scores 100%; the gap on the holdout is the case for a language model router. Claude Sonnet 5.5 reads every holdout question right and passes the number check on its first draft every time, for under two cents a question. The local models were run before the router repairs, the online ones after. BM25 retrieval finds the right rule passage in the top three for 7 of 8 labelled rule questions.

`python -m staffpilot eval` runs the online models (`--source local` the ones on this computer, `--keep` joins the two). Each answer is scored by judges from other providers, the run reports tokens and cost, and it writes a routing table that recommends the best model for each intent. Judge scores compare only between rows with the same judges, and a person's grades of 30 answers showed the small local judges to be lenient, so the structured accuracies are the evidence.

## 8. Limitations

* Two years of history cannot separate trend from noise; forecasts are seasonal averages.
* Revenue depends on A1, which the brief does not settle.
* The plan is deterministic; Monte Carlo tests it but does not optimize over scenarios.
* A monthly update scales the remaining forecast by the error of the last three months and spreads actual monthly counts over the days like the forecast; it is not yet backtested month by month on the second history year.
* The backtest reuses the January headcount table for the earlier year.
* The number check catches invented and misattributed numbers but not a wrong sign or a wrong small count.
* Language model results depend on the models and keys available at run time; cached replies make reruns reproducible once committed.
* Sign in only records who approved each decision. It has no roles yet, and passwords travel over plain HTTP on a laptop; a deployment would use the company sign in service.
