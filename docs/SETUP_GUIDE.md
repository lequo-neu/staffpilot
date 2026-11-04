# Setup guide for beginners

This guide takes you from a computer with nothing installed to a running StaffPilot: the plan, the assistant, the web app and the notebook. No programming experience is needed. Plan for about 30 minutes, most of it waiting for downloads.

Every command goes into a terminal window. Type or paste it, press Enter, and wait until the prompt comes back before the next one. Commands differ slightly between macOS and Windows; each step shows both.

## What you need

* A Mac or a Windows PC with about 2 GB of free disk space and an internet connection.
* The teaching team data file (an `.xlsx` workbook from Canvas). You can finish most of the setup before you have it.
* Optional: an API key for OpenAI, Anthropic or Google if you want language models instead of the built in offline assistant.

## Step 1: Install Python 3.12

StaffPilot needs Python 3.11, 3.12 or 3.13. We use 3.12. Newer versions such as 3.14 may fail to install some packages.

**macOS**

1. Go to https://www.python.org/downloads/macos/ and download the latest "Python 3.12" macOS installer.
2. Open the downloaded file and click through the installer.
3. Open the **Terminal** app (press Command and Space, type Terminal, press Enter) and check:

```bash
python3.12 --version
```

You should see `Python 3.12.x`. If you use Homebrew, `brew install python@3.12` works too.

**Windows**

1. Go to https://www.python.org/downloads/windows/ and download the latest "Python 3.12" Windows installer (64 bit).
2. Run it. On the first screen tick **Add python.exe to PATH**, then click **Install Now**.
3. Open **PowerShell** (press the Windows key, type PowerShell, press Enter) and check:

```powershell
py -3.12 --version
```

You should see `Python 3.12.x`.

## Step 2: Get the code

**Option A, with Git (recommended, needed to push changes later).**

* macOS: run `git --version` in Terminal. If Git is missing, macOS offers to install the developer tools; accept and wait.
* Windows: install Git from https://git-scm.com/download/win with the default options, then reopen PowerShell.

Then download the repository into your home folder (replace the link with your team's repository):

```bash
cd ~
git clone https://github.com/lequo-neu/staffpilot.git
cd staffpilot
```

**Option B, without Git.** On the repository page on GitHub click **Code**, then **Download ZIP**. Unzip it, then in the terminal go into the unzipped folder, for example:

```bash
cd ~/Downloads/staffpilot-main
```

On Windows the same command works in PowerShell. To check you are in the right place, list the files: `ls` should show `README.md`, `pyproject.toml` and the `src` folder.

## Step 3: Create a virtual environment

A virtual environment is a private copy of Python for this project, so its packages do not mix with anything else on your computer. You create it once.

**macOS**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.venv\Scripts\Activate.ps1
```

The middle line only allows scripts in this one window; it is needed because Windows blocks activation scripts by default. In the older `cmd.exe` window use `.venv\Scripts\activate.bat` instead.

When the environment is active, the prompt starts with `(.venv)`. From now on the command is simply `python`, on both systems.

## Step 4: Install StaffPilot

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev,notebook]"
```

This downloads a few hundred megabytes and takes two to five minutes. The quotes around `.[dev,notebook]` matter. `dev` adds the testing tools and `notebook` adds JupyterLab.

## Step 5: Check the installation

The tests use made up data, so they work before you have the real file:

```bash
python -m pytest -q
```

The last line should say `140 passed`. If it does, Python, the solver and every package are working.

## Step 6: Add the data file

1. Copy the workbook from Canvas into the folder `data/raw/` inside the project.
2. Open `config/staffpilot.toml` in any text editor (TextEdit on Mac, Notepad on Windows, or VS Code).
3. Change the `path` line so the file name matches exactly, for example:

```toml
[data]
path = "data/raw/IE5374_Hackathon_Google_Data.xlsx"
```

Save the file. The planning year follows the data automatically: sign ups from 2023 and 2024 give a plan for 2025.

## Step 7: Build the plan

```bash
python -m staffpilot plan
```

After about 20 seconds you see the planning year, the net value, the service rate and a small table that compares the recommended plan with simpler policies. Three files appear in `outputs/`:

* `plan.csv`: agents per country and month, with hires, notices and payroll. It opens in Excel or Numbers.
* `kpis.csv`: cost, value, service and wait times per country.
* `policy_comparison.csv`: the recommended plan against the baselines.

If you see `Data problem: Dataset not found`, go back to step 6 and compare the file name in `config/staffpilot.toml` with the real one, letter by letter.

## Step 7b: Explore the data

```bash
python -m staffpilot eda
```

This checks the data (missing values, duplicates, impossible dates) and writes `outputs/eda/eda_report.md` with six charts. Open the Markdown file in VS Code or any Markdown viewer to read it with the pictures.

## Step 8: Ask the assistant

```bash
python -m staffpilot ask "How many agents does Germany need in March and why?"
python -m staffpilot ask "What if sign ups in Brazil drop 30% in Q3?"
python -m staffpilot memo Vietnam
```

Each answer ends with a short note on which planner tool answered and whether every number was checked, and saves a chart that illustrates it in `outputs/answers/`.

To have a conversation instead of single questions:

```bash
python -m staffpilot chat
```

Type a question, press Enter, then try a short follow up such as `And Mexico?` or `What about 50 percent instead?`. The assistant keeps what you left out from your last question and says so under the answer. Type `new` to start over, `save` to write the conversation to `outputs/conversations/chat.md`, or press Enter on an empty line to quit. Without API keys the offline assistant answers; it understands the phrasing in the examples well and unusual phrasing less well.

## Step 9: Open the web app

```bash
python -m staffpilot app
```

The terminal prints `Starting StaffPilot at http://127.0.0.1:7860`. Open that address in your browser; the very first start takes about 15 seconds while the plan is built and saved in `.cache/`; later starts take about 5. The sidebar on the left has:

* **New chat**, to start a conversation; the chats you have had in this browser tab are listed under **Recent chats**, and clicking one reopens it.
* The pages: **Assistant** (chat; follow up questions work), **Plan** (monthly headcount per country, with an approval button), **Scenario** (describe a change in words, check the parameters, run it), **Memo** (a staffing memo for one country), **Data** (the exploratory analysis) and **Evaluation** (how the assistant scored).
* **Settings**: the language model to use, **Refresh models** and **Save conversation**. The app always starts on **Offline**, which is free. With API keys the list also shows every model your keys can use, cheapest first; on start the app checks the cheapest ones with a tiny request, hides models that no longer work and marks the cheapest working one. Picking a model makes each question cost a fraction of a cent.

The headline numbers (net value, agents at work, advertisers served, utilization, cost) are on the **Plan** page. Hover over the small i next to each one for what it means.

On a phone, open the sidebar with the arrow at the top left. Add `?__theme=dark` to the address for dark mode.

To stop the app, click the terminal and press Control and C.

## Step 10: Open the notebook

The notebook `notebooks/StaffPilot_Topic3.ipynb` is the file the course asks for. To look at it and run it yourself:

```bash
cd notebooks
jupyter lab
```

JupyterLab opens in the browser. Double click `StaffPilot_Topic3.ipynb`, then choose **Run**, then **Restart Kernel and Run All Cells**. The run takes four to five minutes. Close JupyterLab with Control and C in the terminal, then `cd ..` to go back to the project folder.

In VS Code, install the Python and Jupyter extensions, open the notebook and pick the `.venv` interpreter when asked.

To rebuild the notebook from scratch and save it with all outputs (for submission), run from the project folder:

```bash
python scripts/build_notebook.py
```

## Step 11 (optional): Use language models

1. Get an API key from OpenAI (https://platform.openai.com), Anthropic (https://console.anthropic.com) or Google AI Studio (https://aistudio.google.com).
2. Make your own key file from the example:
   * macOS: `cp .env.example .env`
   * Windows: `Copy-Item .env.example .env`
3. Open `.env` in a text editor and paste your key after the matching name, for example `ANTHROPIC_API_KEY=sk-ant-...`. Leave the others empty.
4. Check that StaffPilot sees the key:

```bash
python -c "from staffpilot.agent import available_providers; print(available_providers())"
```

It should print the providers you set, for example `['anthropic']`. Next, see which models your keys can use (this asks each provider for its model list and costs nothing):

```bash
python -m staffpilot models
```

It lists the chat models cheapest first and marks the two StaffPilot will use (the cheapest as the fast tier, the most capable as the strong tier). To check that those two really answer, add `--ping` (one very short call each, a fraction of a cent). A line with `FAILED` shows the reason; to use a different model, set it in `config/staffpilot.toml` under `[llm.models]` or `[llm.fast_models]`. Then:

```bash
python -m staffpilot ask "How many agents does Germany need in March and why?" --backend anthropic_fast
python -m staffpilot eval
```

The evaluation sends 82 questions to each model, plus judge and agent calls, so it costs money; check the usage page of your provider after a first run. Use `python -m staffpilot eval --tier fast` for the cheaper models only. Replies are saved in `eval/cache/`, so a second run is free. Never commit `.env`; it is already excluded by `.gitignore`.

### Free option: models on your own computer

If LM Studio or Bionic is installed, you can use its models for free:

1. Start the local server: `~/.lmstudio/bin/lms server start`
2. Load a model: `~/.lmstudio/bin/lms load google/gemma-4-e4b` (see your models with `~/.lmstudio/bin/lms ls`)
3. Check that StaffPilot sees it: `python -m staffpilot models` lists a `local:` section
4. Ask with it: `python -m staffpilot ask "How many agents does Germany need in March?" --backend local_fast`

Local models are slower than cloud models and need memory: a 4B model needs about 7 GB, a 27B model about 16 GB. Stop the server with `~/.lmstudio/bin/lms server stop`.

To compare the local models with each other (free), run `python -m staffpilot eval --source local`. It needs at least two chat models; the [testing guide](TESTING_GUIDE.md) walks through it step by step.

## See what is going on

* `python -m staffpilot --log-level INFO plan` prints each step; `DEBUG` prints even more. Every run also writes its own log file in `logs/`, named after the start time and the command, for example `logs/20261102_232446_plan.log`.
* `python -m staffpilot history` lists earlier runs with the data file, the settings and the results.
* `python -m staffpilot plan` ends with alerts. A **critical** alert such as "This file plans 2026, but the brief asks for 2025" means the numbers should not be used yet.

## Every time you come back

Open a terminal, go to the project folder and activate the environment again:

* macOS: `cd ~/staffpilot` then `source .venv/bin/activate`
* Windows: `cd ~\staffpilot`, then `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`, then `.venv\Scripts\Activate.ps1`

You do not need to reinstall.

## Troubleshooting

| What you see | What to do |
|---|---|
| `python3.12: command not found` (macOS) | Python 3.12 is not installed or the terminal was open during the install. Close and reopen Terminal, or repeat step 1. |
| `'py' is not recognized` (Windows) | Rerun the Python installer, choose **Modify** and make sure the launcher and PATH options are ticked. |
| `running scripts is disabled on this system` | Run the `Set-ExecutionPolicy` line from step 3 in the same PowerShell window. |
| The prompt does not start with `(.venv)` | The environment is not active; run the activate command from step 3. |
| `No module named staffpilot` | The environment is not active, or step 4 was skipped. Activate it and run the install command again. |
| `pip` fails while building a package | Your Python is too new. Check `python --version`; recreate `.venv` with Python 3.12 (delete the `.venv` folder first). |
| `Data problem: Dataset not found` | The file is not in `data/raw/` or the name in `config/staffpilot.toml` differs. |
| `Address already in use` when starting the app | Another app uses port 7860. Run `python -m staffpilot app --port 7861` and open that address. |
| The notebook cannot find files | Start JupyterLab from the `notebooks` folder, as in step 10. |
| An answer says it cannot read a change | The offline assistant knows a limited set of phrasings. Rephrase like the examples, or add an API key (step 11). |

## Command cheat sheet

| Task | Command |
|---|---|
| Activate the environment (macOS) | `source .venv/bin/activate` |
| Activate the environment (Windows) | `.venv\Scripts\Activate.ps1` |
| Run the tests | `python -m pytest -q` |
| Build the plan | `python -m staffpilot plan` |
| Explore the data | `python -m staffpilot eda` |
| List earlier runs | `python -m staffpilot history` |
| More detail in the terminal | `python -m staffpilot --log-level INFO plan` |
| Ask a question | `python -m staffpilot ask "your question"` |
| Have a conversation | `python -m staffpilot chat` |
| Write a memo | `python -m staffpilot memo Germany` |
| Start the app | `python -m staffpilot app` |
| Rebuild the notebook | `python scripts/build_notebook.py` |
| Compare language models | `python -m staffpilot eval` |
| Leave the environment | `deactivate` |

To check that everything works, page by page, follow the [testing guide](TESTING_GUIDE.md).
