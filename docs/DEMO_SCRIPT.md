# Demo script (about 3 minutes)

Start the app offline so nothing calls a paid model: `STAFFPILOT_OFFLINE=1 python -m staffpilot app`, then open http://127.0.0.1:7860 in a wide window. Every number below comes from the public copy of the data (planning year 2026).

The story follows a staffing manager's year: plan it, check it, test it, update it with real numbers, and see who changed what.

| Time | Where | What to do | What to say | Brief item |
|---|---|---|---|---|
| 0:00 | This year | Nothing; it opens here | "The year in one screen: $479.7M of net value, $109.3M more than keeping the January team; 6,474 agents in January settle to about 2,220; every eligible advertiser is served in about a day. The strip shows each month's decision: 4,741 notices in January in red, hires before the fourth quarter." | agents per country and month, hiring and notice timing, cost and timely support |
| 0:25 | Plan, Overview | Pick the service goal `Profit, 98% served within 7 days` | "Service is a business choice. Serving everyone within a week costs $3.6M and about 87 agents; the chart shows each goal against profit only." | timely support, other considerations |
| 0:45 | Plan, Check the plan | Read the list | "8 of 8 checks pass: every brief rule, the solver's proof of optimality for 22 of 22 countries, a gain over every simple rule, and a backtest at 99.3 percent of hindsight. The note is honest: 5 percent fewer agents would earn $1.8M more with waits of 2.1 days instead of 1.1." | analysis and justification |
| 1:05 | Plan, Try your own plan | Pick Germany, click Score my plan | "A manager can type any headcount; the same simulator scores it. Fewer agents earn a little more by making advertisers wait longer; more agents always earn less." | |
| 1:20 | Scenario | Click `Hiring in Brazil is capped at 5 agents a month` | "A sentence becomes typed scenario parameters through structured output; the manager can check and edit them before the run. The chart shades the months that change." | scenario explorer, GenAI techniques |
| 1:40 | Assistant | Click `What if sign ups in Brazil drop 30% in Q3?`, then type `And Mexico?` | "The follow up keeps the scenario and changes the country. On the right: the tool that ran, and how many numbers were checked against planner facts. The language model writes no number." | assistant, insights, GenAI techniques |
| 2:05 | This year, then Monthly update | Pick `Start of March`, click `Open Monthly update`, then Update the plan | "Sign ups ran 20 percent above forecast in January and February. January and February stay as they were; the update hires 39 agents in March where the plan said none. The input check reads every typed number back against the forecast." | sensitivity to sign up volume |
| 2:30 | Monthly update | Click Approve the update | "The approval is saved as a file named by country, month and time." | |
| 2:40 | Decision log | Click `Only changes` | "Every decision keeps apart what was proposed, by the optimizer or a language model, what changed it, and what was applied." | |
| 2:50 | Memo | Read the memo | "Each country manager gets a one page memo; every number in it matches the planner." | staffing memo |

If a model key is set, pick a model in Settings before the Assistant step; the line under the chat box names the model that answers.
