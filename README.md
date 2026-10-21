# Portfolio Risk Copilot

**An AI risk analyst for Indian stock portfolios.** Upload holdings from Zerodha or Groww (CSV, Excel or PDF statement). See how risky the portfolio is in plain words, stress-test it against sector shocks and real past crashes, forecast next month with Monte Carlo, and ask a LangGraph agent questions that are answered from your real numbers.

**Stack:** Python · FastAPI · PostgreSQL · SQLAlchemy · Alembic · Pandas · NumPy · LangGraph · Gemini · Groq · React · Recharts · Docker · GitHub Actions

![Overview page](docs/screenshots/overview.png)
<sub>Screenshot uses the app's built-in demo prices.</sub>

---

## Highlights

- **Risk engine** in Pandas/NumPy: volatility, max drawdown, historical VaR and expected shortfall, beta, Sharpe, correlation, concentration (HHI), and **Euler risk contributions** (which stock causes how much of the risk). Every formula is unit-tested against hand-worked answers.
- **Time-series and probability models:** **EWMA volatility** (the RiskMetrics method) as a "risk is rising" signal, a **10,000-path Monte Carlo** month-ahead forecast (filtered historical simulation), and a **Kupiec backtest** that checks whether the VaR number actually held up on past data.
- **Stress testing:** sector shocks with knock-on effects estimated by beta, market shocks, custom moves, and replays of the 2020 COVID crash, the 2022 rate-hike selloff and the 4 June 2024 election-day fall on today's holdings.
- **AI agent that never does its own maths:** a LangGraph tool-calling loop with 10 tools. Gemini picks the tool and explains the result; every number comes from tested code. If Gemini fails (busy, quota, retired model), **Groq** answers with the same tools; rule-based answers only if both fail.
- **Agent evaluation harness:** 30 questions (16 dev + 14 held-out) scored on tool choice, numeric accuracy, **groundedness** (is every ₹ and % in the answer copied from a tool result?), no-advice behaviour, latency and token cost.
- **Document extraction:** reads PDF statements (ruled and unruled tables). For PDFs with no table, Gemini returns **structured JSON validated by Pydantic**, and every quantity and price it reads must appear in the PDF text, or the row is rejected.
- **Production basics:** JWT auth with **role-based access**, per-user data isolation, Alembic migrations (schema + data), daily alerts to Telegram, an Excel risk report, Docker, and CI that runs **102 tests on SQLite and PostgreSQL 16**.

## What the user sees

| Page | What it does |
|---|---|
| **Overview** | "On a bad day, you could lose ₹9,519." Value, profit/loss, VaR, drawdown, and which stock is quietly causing most of the risk. "Looking ahead": volatility now vs usual, the Monte Carlo distribution of next month, and the VaR backtest result. Every finance word explains itself on hover. Download everything as Excel. |
| **What if?** | Pick a sector shock, a market shock, your own moves, or a past crash. See the rupee impact per stock and how each move was estimated. |
| **Ask** | Chat with the agent: "What if banks fall 20%?", "What's the chance I lose 10% next month?", "Give me a weekly brief". Shows which tools it used. |
| **Alerts** | Weekday 6:30 pm IST checks: big daily moves, stocks far below their 1-year high, too much in one stock or sector, a volatility spike, and negative news. Sent to Telegram. |
| **Holdings** | Upload CSV, Excel or PDF, or add stocks by hand. Edit quantities, prices and sectors. |

## How it fits together

```
React app (Vite)
     │  /api
     ▼
FastAPI ─────────── PostgreSQL  (users, holdings, cached prices, alerts) ← Alembic migrations
  │
  ├── Upload ────────────── CSV / Excel / PDF tables  ──► same table parser
  │                         PDF without a table ──► Gemini structured output ──► numbers checked against PDF
  ├── Stock data ────────── NSE industry list (app/data) + Yahoo sectors mapped to NSE names
  ├── Prices ────────────── yfinance → upserted into the DB (only missing days are fetched)
  ├── Risk engine ───────── volatility, drawdown, VaR/CVaR, beta, risk contributions
  ├── Quant models ──────── EWMA volatility, Monte Carlo (10k paths), Kupiec VaR backtest
  ├── Scenario engine ───── sector / market / custom / historical replay
  ├── LangGraph agent ───── Gemini (Groq as backup) + 10 tools (the tools call the engines above)
  ├── Excel report ──────── 6 sheets via pandas + openpyxl
  └── Daily job ─────────── alerts → Google News RSS + Telegram bot
```

**Key design choice:** the LLM never calculates. It chooses a tool and explains the result. The evaluation checks this by flagging any number in an answer that didn't come from a tool. See [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

---

## Agent evaluation

```bash
cd backend
python -m eval.agent_eval                        # your main AI (LLM_PROVIDER in .env)
LLM_PROVIDER=groq python -m eval.agent_eval      # same questions on Groq, to compare
LLM_PROVIDER=offline python -m eval.agent_eval   # rule-based baseline
```

| Mode | Set | Tool choice | Numbers correct | Grounded | No advice |
|---|---|---|---|---|---|
| Rule-based baseline | dev (16) | 100% | 100% | 100% | – |
| Rule-based baseline | **held-out (14)** | **50%** | **36%** | 100% | 100% |
| Gemini agent | held-out (14) | *run it and fill in* | | | |
| Groq agent (gpt-oss-120b) | held-out (14) | *run it and fill in* | | | |

The baseline was written around the dev questions, so its dev score means nothing. The held-out set uses new wordings ("dropped by a fifth") and multi-step questions ("compare a 10% Nifty fall with the 2020 crash"). That's the fair comparison. Per-question answers, latency and token counts are saved to `backend/eval/results.json`.

---

## Run it on your computer

You need **Python 3.12 or 3.13** and **Node.js 20.19+ (22 recommended)**.

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                   # Windows: copy .env.example .env
python -m uvicorn app.main:app --reload
```

The API runs at http://localhost:8000. Interactive API docs: http://localhost:8000/docs

**Database:** nothing to set up. Locally it uses a SQLite file. On start, the app runs its Alembic migrations, which create and update all tables. In production you point `DATABASE_URL` at Postgres and the same happens.

> **No internet or Yahoo blocked?** Set `PRICE_SOURCE=demo` in `.env` to use realistic fake prices.

### 2. Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, create an account, and upload a file from `sample_data/`.

### 3. Turn on the AI (optional, free)

Get a key at https://aistudio.google.com/apikey. In `backend/.env` set `LLM_PROVIDER=gemini` and `GOOGLE_API_KEY=...`, then restart. Without a key, the Ask page runs in basic mode, and PDFs without tables can't be read.

**Backup AI (recommended):** also add a free Groq key from https://console.groq.com/keys as `GROQ_API_KEY=...`. If Gemini fails, Groq answers instead. Or use Groq as the main AI with `LLM_PROVIDER=groq`.

> Model names change often. If you get "model not found", update `GEMINI_MODEL` (see https://ai.google.dev/gemini-api/docs/models) or `GROQ_MODEL` (see https://console.groq.com/docs/models).

### 4. Use NSE's full official stock list (recommended)

The app ships a starter list of ~130 large NSE stocks with NSE's industry names. To load all 500 stocks from NSE's official Nifty 500 file:

```bash
cd backend
python -m scripts.update_stock_list
```

If NSE blocks the script, download `ind_nifty500list.csv` from the NSE website in your browser, save it as `backend/app/data/nifty500.csv`, and restart.

### 5. Telegram alerts (optional)

Create a bot with **@BotFather**, put the token in `TELEGRAM_BOT_TOKEN`, press **Start** in your bot, get your chat ID from **@userinfobot**, and paste it in the app's Settings.

### Or run everything with Docker

```bash
docker compose up --build      # then open http://localhost:8080
```

---

## Tests

```bash
cd backend
python -m pytest -q                                    # 102 tests, SQLite
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/empty_db python -m pytest -q   # same on Postgres
```

What they cover: risk formulas against hand-worked answers; EWMA against the RiskMetrics recursion; Monte Carlo against normal-distribution theory; the Kupiec test against a value worked by hand; scenarios on a portfolio with known betas; every broker file format, including multi-page PDF tables and the AI fallback (with a fake LLM that invents a row, which must be rejected); sector-name mapping; the data migration; login, data isolation and admin-only routes; the agent loop with a scripted LLM; the Excel export; and the evaluation's own number checks. CI also runs `alembic check`, so a model change without a migration fails the build.

## Deploy for free

Step-by-step guide: **[docs/DEPLOY.md](docs/DEPLOY.md)**. Neon (Postgres) + Render (backend, one click with `render.yaml`) + Vercel (frontend) + GitHub Actions (daily alerts, since Render's free plan sleeps). Tested before release: all tests on Postgres 16, 20 users at once on a cold cache with no errors, and ~290 MB peak memory (Render's free plan gives 512 MB).

## Project layout

```
backend/
  app/
    main.py               App, startup safety checks, health check
    models.py, database.py Tables; migrations run on start
    data/                 NSE stock lists (official format) and ETFs
    routers/              auth, portfolio (+ Excel), scenarios, chat, alerts, admin, cron
    services/
      csv_parser.py       Finds the holdings table in CSV/Excel/PDF grids
      pdf_extract.py      PDF tables + AI extraction with number checks
      sectors.py          One sector vocabulary (NSE names) for all sources
      stocks_meta.py      Loads the stock lists
      prices.py           Price fetching + upsert cache
      risk_engine.py      Risk maths (pure functions)
      quant.py            EWMA, Monte Carlo, Kupiec backtest
      portfolio_data.py   Builds the risk report
      scenarios.py        What-if engine
      excel_report.py     Excel export
      alerts.py, news.py  Daily checks and news
    agent/                LangGraph loop, 10 tools, rule-based fallback
  migrations/             0001 creates tables, 0002 renames old sector labels
  scripts/                Download NSE's list; make the sample PDFs
  tests/                  pytest suite
  eval/                   Agent evaluation (questions.json, agent_eval.py)
frontend/src/             Pages and components
sample_data/              Example Zerodha, Groww, template CSVs and PDF statements
docs/                     HOW_IT_WORKS.md, DEPLOY.md, screenshots
```

## Limitations

- **Based on the past.** Risk uses the last 1–2 years of prices. A calm period can hide risk; the VaR backtest is there to catch that.
- **Constant weights.** Risk numbers assume today's mix was held the whole time.
- **Monte Carlo assumes no trend** and re-uses real past days, so it can't produce a crash worse than anything in the sample.
- **NSE stocks only.** No mutual funds or F&O. Scanned (image-only) PDFs aren't supported.
- **Prices come from Yahoo Finance** (unofficial, end-of-day). A production system would use a licensed data feed.
- **Not financial advice.** The app explains risk. The agent is told not to recommend trades, and the evaluation checks it.
