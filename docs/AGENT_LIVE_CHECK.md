# Live check of the create_agent chat

The structured assistant is tested offline, but the free form chat built with LangChain `create_agent` (where the model chooses and chains the planner tools) only runs with a real model. This page records a live run, checked against the planner, on 3 November 2026.

* Command: `python -m staffpilot chat --agent --backend anthropic_fast`
* Model: `anthropic:claude-haiku-5-5` (picked as the cheapest Anthropic model that answers)
* Data: `IE5374_Hackathon_Google_Data.xlsx`, planning year 2026
* Cost: three questions, well under one cent

## Transcript

```
Type 'new' to start over, or press Enter on an empty line to quit.

You: Which three countries give the most notices this year, and how many each?
StaffPilot agent: Based on the 2026 staffing plan from `get_plan`, the three countries with the most notices are:

1. **Germany: 516 notices**
2. **UK: 487 notices**
3. **USA: 439 notices**

France is fourth with 419.

(anthropic:claude-haiku-5-5; tools called: get_plan; every number found in the tool output.)

You: For the first of those, what is its net value and how many agents work in March?
StaffPilot agent: Germany's net value is **24,042,953.65** for 2026 (from `get_plan`, all-year Germany row).

In March, **86 agents** are active in Germany (from `get_plan` month detail for 2026-03). There are no hires or notices that month.

(anthropic:claude-haiku-5-5; tools called: get_plan; every number found in the tool output.)

You: What happens to it if sign ups drop 30 percent in Q3?
StaffPilot agent: If Germany's sign ups drop 30 percent in July to September, with the plan rebuilt (`run_scenario`):

- **Net value falls by 2,920,790**, from 24,042,953.65 to 21,122,163.48 (about 12%).
- **Served advertisers fall by 367**, from 5,373 to 5,006. Service rate stays at 100% and nothing is dropped.
- **Uplift value falls by 3,037,989**, which more than offsets the **117,199 cost saving**.
- **Staffing barely moves:** average active agents drop from 133.4 to 130.3, hires rise by 1 (16 to 17), and notices rise by 2 (516 to 518).

(anthropic:claude-haiku-5-5; tools called: run_scenario; numbers not found in the tool output: 12%.)

You: (empty line, quit)
```

## Checked against the planner

| Question | Agent | Planner | Result |
|---|---|---|---|
| Most notices | Germany 516, UK 487, USA 439 (France 419 next) | Germany 516, UK 487, USA 439, France 419 | correct |
| Germany net value | 24,042,953.65 | $24.0M | correct |
| Germany agents in March | 86 | 86 | correct |
| Germany, sign ups down 30 percent in Q3 | net value down 2,920,790 | down $2.92M | correct |
| Memory | "the first of those" and "it" read as Germany | | correct |
| Number check | flags only "12%", which the agent worked out itself | | as designed |

## What the live run found and fixed

The first live runs showed problems that the offline tests could not:

1. Asked about all countries, `get_plan` sent the agent the first 15 monthly rows (USA and UK only), so it could not rank countries. It now sends one row per country, and up to 30 rows in all.
2. The number check only knew the named facts, so correct numbers read from a tool's table were flagged. Table rows and notes now count as evidence, while numbers the agent works out itself are still flagged.
3. The model read "notices" as advertiser sign ups and called the sign up tool. The agent prompt and the tool descriptions now define notices, hires, sign ups and net value.
4. `chat --agent` and `ask --backend ...` did not read the keys in `.env` and failed with a traceback. Keys are now read when a model backend is built, and a missing model gives a one line message.
