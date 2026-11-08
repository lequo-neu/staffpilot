# Evaluation of the assistant

How the GenAI part is measured: the test sets, the scores, the runs, and a check of the AI judge against a person. The summary is in the [README](../README.md).

## Test sets and scores

`eval/testset.jsonl` has 40 labelled questions across eight intents (plan lookup, compare, what if, sensitivity, insight, memo, rules, out of scope). `eval/holdout.jsonl` has 32 more written in different words. `eval/followups.jsonl` has 10 follow ups, each asked after the earlier question it lists in `context`. `eval/edge.jsonl` has 11 harder what if questions (see the edge set below). For each backend and split the harness reports:

* intent, country and scenario field accuracy of the structured request;
* grounded rate (passes the number check without the template fallback; always 100 percent for the offline templates, by construction);
* a 1 to 5 judge score, averaged over judge models from every other provider, with a written rubric (no model grades its own provider);
* tool choice accuracy of the `create_agent` chat;
* tokens, cost (where a price is configured) and latency.

Strong and fast tiers are compared separately so each model faces its peers. Retrieval is scored on its own: for rule questions labelled with the passage that answers them, BM25 puts that passage in the top three for 7 of 8; the one it misses (h14, the length of support) is shown in red on the Evaluation page.

Two runs fill the table, joined with `--keep`:

* **Local, 3 November 2026** (`python -m staffpilot eval --source local gemma llama --skip-agent`): two open models on this computer through Bionic, `google/gemma-4-e4b` (4B) and `meta-llama-3.1-8b-instruct` (8B), each judged by the other. It took 2 hours 19 minutes and cost nothing.
* **Online, 4 November 2026** (`STAFFPILOT_CONFIG=config/eval_online.toml python -m staffpilot eval openai anthropic --tier strong --skip-agent --keep`): a cheap model, `openai:gpt-5-nano`, and a strong one, `anthropic:claude-sonnet-5-5`, each judged by the other, both judging offline (so offline was run again). It took 42 minutes; the answers cost $1.26 for Claude and $0.06 for GPT 5 nano, plus the judging. Gemini was left out: the free Google key had no quota left. The Anthropic credit ran out during the last 6 follow ups (f05 to f10); they count as errors, not as answers, so Claude's follow up row rests on 4 questions.

| Split | Backend | Intent | Country | Scenario | Grounded | Judge score (1 to 5) | Seconds per question | Answer cost per question |
|---|---|---|---|---|---|---|---|---|
| main (40) | offline | 100% | 100% | 100% | 100% | 3.84 | 0.1 | free |
| main (40) | Gemma 4 E4B (local) | 100% | 95% | 83% | 62% | 4.08 | 72 | free |
| main (40) | Llama 3.1 8B (local) | 100% | 88% | 100% | 98% | 3.27 | 11 | free |
| main (40) | GPT 5 nano | 95% | 95% | 96% | 78% | 3.17 | 13 | $0.001 |
| main (40) | Claude Sonnet 5.5 | 100% | 100% | 100% | 100% | 4.25 | 9 | $0.016 |
| **holdout (32)** | offline | 28% | 97% | 0% | 100% | 2.95 | 0.0 | free |
| **holdout (32)** | Gemma 4 E4B (local) | 88% | 97% | 67% | 75% | 4.47 | 66 | free |
| **holdout (32)** | Llama 3.1 8B (local) | 38% | 81% | 11% | 94% | 3.47 | 11 | free |
| **holdout (32)** | GPT 5 nano | 84% | 97% | **100%** | 84% | 2.78 | 12 | $0.001 |
| **holdout (32)** | **Claude Sonnet 5.5** | **100%** | **100%** | **100%** | **100%** | 4.19 | 8 | $0.016 |
| followups (10) | offline | 90% | 100% | 75% | 100% | 3.75 | 0.1 | free |
| followups (10) | Gemma 4 E4B (local) | 100% | 100% | 88% | 70% | 4.40 | 62 | free |
| followups (10) | Llama 3.1 8B (local) | 90% | 90% | 67% | 100% | 4.10 | 12 | free |
| followups (10) | GPT 5 nano | 100% | 90% | 100% | 90% | 2.60 | 13 | $0.001 |
| followups (4 of 10) | Claude Sonnet 5.5 | 100% | 100% | 100% | 100% | 4.25 | 10 | $0.019 |

The local rows were run before the router repairs and the stricter number check described below; the online rows and offline were run after them, so the comparison flatters the online models a little. Offline's judge scores are lower than in the local run (2.95 instead of 4.13 on the holdout) only because its judges changed (Claude and GPT 5 nano instead of Gemma and Llama): judge scores compare only between rows with the same judges, which the `judged_by` column names.

What the numbers say:

* **On new wording (holdout), a language model router is far better than keywords.** Claude Sonnet 5.5 reads every intent and every scenario field correctly, Gemma 88 and 67 percent and GPT 5 nano 84 and 100 percent, against 28 and 0 percent for offline.
* **Claude Sonnet 5.5 is the best assistant, and it costs little.** It is the only model that passes the number check on its first draft every time (grounded 100 percent), answers in about 8 seconds, and costs about $0.016 a question; a manager asking 50 questions a month would spend under a dollar.
* **GPT 5 nano is the cheap middle ground.** At a tenth of a cent a question it reads 84 percent of new wording, but about one draft in five fails the number check and falls back to the template, and Claude judges its answers lowest (2.8).
* **Grounding holds for every model.** No answer reached the user with an unchecked number: when a model's draft failed the number check twice (Gemma for about a quarter of the answers), the template answer was used instead, which is why its grounded rate is lower while its answers stay correct.
* **Llama's router output often failed validation.** In 68 of its questions it filled `service_target` with values such as 90 or 10000 although the field is a share between 0 and 1, so the whole request was rejected and the offline router took over; its holdout row is therefore close to offline. This is fixed since that run: the router now keeps a reply and repairs the bad fields (a share written as 90 becomes 0.9, a scenario on a question that is not a what if is dropped, unknown fields are removed). Replaying six holdout questions Llama had missed, it now reads all six intents correctly; the local rows above are from before the fix.
* **Grading 30 answers by hand found answers that passed the number check but were unusable.** Llama often sent back a tool call as JSON instead of sentences, and memos left fact names unfilled (`France.hires`) or a bullet empty. Every number in them was right, so the check passed. The check now also rejects JSON, single braces, bare fact names and empty bullets, so the answer is rewritten or falls back to the template. Two router faults were fixed with them: a model that filled the country with "All" got the reply "I do not have data for All", and the offline router took "Indian" and a sentence that starts with "Effect" for unknown places. Country adjectives now map to their country. The words "Indian" and "Spanish" came from holdout questions, so the offline holdout score after this fix is slightly optimistic. Years also print as 2026 instead of 2,026. The local rows above are from before these fixes.
* **Speed and cost.** Offline answers in a fraction of a second; Claude in about 8 seconds, Llama, GPT 5 nano in about 11 to 13 and Gemma in over a minute on a laptop. Offline and the local models are free.
* **Judge scores depend on the judge.** Llama (judging Gemma) was more lenient than Gemma (judging Llama), GPT 5 nano (judging Claude) was more lenient than Claude (judging GPT 5 nano), and two of the four judges are small models, so the judge column is the least reliable one; the structured accuracies are exact.


The offline keywords were written while looking at the main set, so its main score flatters it; the holdout shows the gap a language model router has to close. The follow up rules were written together with the follow up set, so treat that row as a regression check. The test questions and labels were drafted with AI assistance (see [docs/AI_USAGE.md](AI_USAGE.md)). `python scripts/label_review_sheet.py` writes them to `eval/label_review.csv`, one row per question with columns for a reviewer's verdict. The team checked all 82 labels there on 3 November 2026 and changed none. Six questions carry a comment because they can be read more than one way: "end the year" (p04) is labelled with no month although it implies December, "the summer months" (h01) is read as June to August, and "around Christmas" (h17) as December only. To check the judge score itself, `python scripts/judge_review.py sheet` writes 30 answers to `eval/judge_review.xlsx` for team members to grade by hand on the judges' rubric, and `python scripts/judge_review.py compare` reports how closely the judges match them (steps in [docs/TESTING_GUIDE.md](TESTING_GUIDE.md), Part H).

**Edge set.** `eval/edge.jsonl` holds 11 what if questions taken from Hamad Al Sulaimi's scenario explorer prototype. Five should be asked back instead of run: an unknown place, a period that runs past December, a 400 percent change, a vague question and one with no size of change. Six should run: two lists of changes for different countries and months, "doubles", "October through December", "120% demand" and full country names. Besides the usual fields the harness scores `ask_back_accuracy`, the share of questions where the assistant asked back exactly when it should. Offline gets all 11 right (intent, countries, scenario and ask back 100 percent; `python -m staffpilot eval --split edge`). The reader was fixed with these questions in view, so like the follow ups this row is a regression check; the language models have not been run on it.

**Does the AI judge agree with a person?** Quoc Hung Le graded the 30 answers in `eval/judge_review.xlsx` by hand on 3 November 2026, checking every number against the facts the judges saw. Against these grades the local judges (each grading the other model) did poorly:

| Judge | Answers | Same score | Within one point | Mean gap | Bias (judge minus person) | Rank correlation |
|---|---|---|---|---|---|---|
| Mean of both local judges | 30 | 37% | 50% | 1.45 | +0.78 | 0.35 |
| Gemma | 20 | 35% | 50% | 1.75 | +0.95 | 0.23 |
| Llama | 20 | 45% | 55% | 1.20 | +0.20 | 0.47 |

| Answers from | Person | Local judges |
|---|---|---|
| offline | 3.3 | 3.25 |
| Gemma | 2.3 | 3.00 |
| Llama | 1.0 | 2.70 |

Both local judges are lenient and unstable: they gave 5 to two answers that were raw JSON, and only half of their scores fall within one point of the person's. The person ranks the models offline, Gemma, Llama, with a far wider gap than the judges show. So the judge scores of the local run should not be used to rank models; intent accuracy, the number check and the hand grades are the evidence. It rests on one grader and 30 answers, so it shows the direction, not a precise size. The grading also found the faults described in the notes above (JSON answers, unfilled fact names, words read as countries). The results also write `eval/results/routing.json`, which recommends a model per intent from the holdout when an intent has at least three questions; the app does not apply it on its own, the user picks the model in Settings.

## Two ways to run the multi LLM evaluation

| | Online (default) | Local |
|---|---|---|
| Command | `python -m staffpilot eval` | `python -m staffpilot eval --source local` |
| Models | GPT, Claude and Gemini through the API keys in `.env`, at the tiers chosen with `--tier` | every chat model of LM Studio or Bionic on this computer, each one on its own |
| Judges | the strong model of each other provider (a provider without one judges with its fast model) | every other local model; none grades itself |
| Cost | paid per token (see `[llm.prices]`) | nothing |
| Speed | fast | slower, limited by the computer |

For the local run, start the server of LM Studio, or of Bionic, which uses it, with `~/.lmstudio/bin/lms server start`; StaffPilot reads it at `http://localhost:1234/v1` (`[llm] local_url`) and waits up to `local_timeout` seconds per call. Words after the command pick models, for example `eval --source local gemma llama`; at least two are needed. Each judge grades all answers after they are in, so the computer keeps one model in memory at a time instead of swapping on every question. In the app and in `ask` and `chat`, local models appear as the provider `local` (`--backend local_fast` is the smallest, `local` the largest).

Each run writes `eval/results/` afresh. Add `--keep` to keep the earlier results of every model not run this time, so a local run and an online run end up on one page. The models run again (offline is in every run) replace their own rows, and a `judged_by` column names the judges of each row: the intent, country, scenario and grounded rates are checked against the labels and compare across all rows, while judge scores compare only between rows graded by the same judges. To compare a cheap, a middle and a strong model of three providers, pin them in a copy of the config and run the strong tier:

```bash
cp config/staffpilot.toml config/eval_online.toml   # then set [llm.models] for openai, google and anthropic
STAFFPILOT_CONFIG=config/eval_online.toml python -m staffpilot eval openai google anthropic --tier strong --skip-agent --keep
```

Online, a Google key without billing can call the Flash and Flash Lite models but not Pro; StaffPilot then judges with the fast model and keeps to `[llm.requests_per_minute] google = 10` so calls wait instead of failing.
