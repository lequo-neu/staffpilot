# Modeling assumptions

The brief leaves some points open. Each choice below is a setting in config/staffpilot.toml so its effect can be measured.

## A1 Uplift base

Uplift is applied to the projected annual budget and counted once, for the advertiser's sign up cohort. The alternative, counting only the 60 day support window, cuts the value of support by about a factor of six. Net value then turns negative under every policy, about minus 178 million dollars when January headcount is kept and minus 67 million dollars with the optimized plan, so cutting is even more clearly right; the open question becomes whether support pays for itself at all.

Why the annual budget: the data gives each advertiser a projected annual budget, and the brief states uplift as a share of ad spend without naming a shorter period. Support is onboarding, so campaigns set up with an agent keep running after the 60 days. The staffing decision does not depend on this choice: under both readings every notice is given in January and the plan beats keeping January headcount by about 110 million dollars.

## A2 Eligibility boundary

An advertiser is eligible only when its budget is strictly greater than the threshold, because the brief says "exceeds". Only a handful of sign ups sit exactly on a threshold.

## A3 Pool on 1 January

The pool starts empty. The brief only says agents start with no advertisers, and the history does not record who was still waiting on 31 December. Starting empty is also the conservative choice, because the carryover would raise net value from about 480 to about 606 million dollars. If the advertisers who signed up in the last 60 days of history were still waiting, about 21,500 people would be in the pool on day one, and the January plan would change a lot.

## A4 Pay during ramp up

Agents in their ramp up month are on payroll, as any employee in training is. Not paying them would add only about 1 million dollars and lead to more hiring, so paying them is the conservative choice.

## A5 Notice month

An agent who receives notice is paid for the notice month and keeps serving the advertisers already assigned, but takes no new ones, so nobody loses support halfway through. The 40 percent cost is charged in the month the notice is given. Every notice in the plan falls in January, so this timing does not change the year's firing cost.

## A6 Departing agents

Capacity is a shared pool per country. The plan never lets occupied slots exceed ten times the active agents, so nobody is left without an agent when someone leaves.

## A7 First decision

The first hiring or notice decision is made in January and takes effect in February. January capacity equals the existing headcount.

## A8 Pool order

Advertisers are assigned first in, first out. Serving high budgets first is offered as a scenario; in the simulator it changes net value by about one million dollars and shortens average waits, but it delays small advertisers.

## A9 Waiting and value

Waiting does not reduce uplift unless the 60 day limit is passed. The optimizer still prefers earlier service through a penalty of 1 percent of uplift per week waited, because the brief asks for timely support. That choice gives up about 3 million dollars of simulated value and cuts the average wait from about 3 days to about 1 day.

## A10 Hiring limits

The brief sets no limit on hires per month. A cap can be tested as a scenario.

## A11 End of horizon

The optimizer looks three months past December, so it does not cut staff at year end only because the model stops there. Only the twelve planning months are reported.
