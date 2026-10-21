# How it works, in plain words

Read this before your interview. Every part of the project is explained simply, with an example. Each section ends with a question an interviewer might ask and a good answer.

---

## 1. The journey of one request

When a user opens the Overview page:

1. React calls `GET /api/portfolio/risk` with the login token.
2. FastAPI checks the token and finds the user (`deps.py`).
3. `build_snapshot()` loads the user's holdings and asks the price service for prices.
4. The price service checks the database first. It only downloads the days it doesn't have yet, then saves them.
5. `risk_report()` turns prices into returns and runs every formula in `risk_engine.py`.
6. The result goes back as JSON. React draws the sentences and charts.

**Q: Why cache prices in the database?**
Yahoo is slow and sometimes blocks cloud servers. With a cache, each stock is downloaded once per day. Every other request is fast, and the app still works if Yahoo is down.

---

## 1b. The database and migrations

Tables are created by **migrations**, not by hand. A migration is a numbered script, like `migrations/versions/0001_initial.py`. **Alembic** runs them when the app starts and records what's done in an `alembic_version` table. So a restart never runs the same migration twice.

Example: to add a "notes" column to holdings, edit `models.py`, run `alembic revision --autogenerate -m "add notes"`, and push. The next deploy adds the column without touching existing data.

Prices are saved with an **upsert** ("insert, or update if it exists") in a single SQL statement:
- Two users loading the same stock at the same moment can't create duplicate rows. A unique rule on (ticker, day) plus the upsert handles it.
- During market hours Yahoo gives today's *live* price as "today's close". Each refresh re-downloads the last saved day and overwrites it, so the real closing price replaces it later.

**Q: Why migrations instead of `create_all()`?**
`create_all()` only creates missing tables. It can't add a column to a table that already has users' data. Migrations can, step by step, and every change is saved in Git.

---

## 2. Reading broker files (`csv_parser.py`)

Every broker exports a different layout:

| Broker | Symbol column | Quantity column | Price column |
|---|---|---|---|
| Zerodha Kite | `Instrument` | `Qty.` | `Avg. cost` |
| Zerodha Console | `Symbol` | `Quantity Available` | `Average Price` |
| Groww | `Stock Name` (a name, not a symbol!) | `Quantity` | `Average buy price` |

How the parser handles this:
- **Find the header row.** Groww and Console files have title rows on top, so it scans the first 30 rows for one that has a quantity, price and symbol-or-name column.
- **Map column names** using a list of known aliases.
- **Clean symbols:** `NSE:INFY-EQ` → `INFY`.
- **Match names to symbols** for Groww: `INFOSYS LIMITED` → `INFY`. If a name could match two stocks (like "HDFC"), it refuses to guess and warns the user instead.
- **Merge duplicates** with a weighted average price. 10 shares at ₹100 + 30 at ₹200 → 40 shares at ₹175.

**Q: What if the name matching is wrong?**
It only matches when exactly one stock fits. Wrong data is worse than missing data, because the user would trust a wrong risk number. Unmatched rows show a clear warning.

---

## 3. The risk math (`risk_engine.py`)

All functions are "pure": numbers in, numbers out. No database, no internet. That makes them easy to test.

**Daily return** = today's price ÷ yesterday's price − 1. ₹100 → ₹102 is a 2% return.

**Portfolio return** = each stock's return × its weight, added up. If INFY is 30% of your money and rises 2%, it adds 0.6% to your portfolio that day.

> We use **today's weights for the whole past year**. The question we're answering is "how risky is the portfolio I hold *now*?"

### Volatility
How much returns jump around. Standard deviation of daily returns × √252.
- Why √252? There are about 252 trading days in a year. Variance adds up day by day, so standard deviation grows with the square root of time.
- Example: 1% daily swing → about 16% yearly volatility.

### Max drawdown
Biggest fall from a high point to a later low point.
- ₹100 → ₹120 (peak) → ₹60 (low) → ₹130. Max drawdown = 60 ÷ 120 − 1 = **−50%**.
- We also report when it started, when it bottomed, and if it recovered.

### Value at Risk (VaR 95%, 1 day)
Sort the daily returns. Take the 5th percentile (the worst 1 in 20 days).
- "On 19 out of 20 days, you lose less than ₹9,519."
- This is **historical VaR**: it uses real past days, not a bell-curve assumption. Real stock returns have more extreme days than a bell curve predicts.

### Expected shortfall (CVaR)
The average of those worst 5% of days. VaR says where bad days start. CVaR says how bad they usually are. CVaR is always ≥ VaR.

### Beta
How much a stock moves when the market (NIFTY 50) moves.
- Formula: covariance(stock, market) ÷ variance(market).
- Beta 1.3 → NIFTY falls 1%, the stock tends to fall 1.3%.

### Sharpe ratio
(Yearly return − safe return) ÷ volatility. The safe return is 6.5% (roughly an Indian government bond). It answers: "Am I being paid enough for the risk I take?"

### Concentration
- **HHI** = sum of squared weights. Everything in one stock = 1.0.
- **Effective number of stocks** = 1 ÷ HHI. 10 equal holdings → 10. One giant plus nine tiny → close to 1.

### Risk contribution (the most interesting one)
How much of the portfolio's swing each stock causes.

```
contribution_i = weight_i × (Covariance matrix × weights)_i ÷ portfolio volatility
```

The contributions add up exactly to the portfolio's volatility (this is called Euler decomposition). A stock can be **19% of the money but 25% of the risk** if it's volatile or moves with your other big holdings.

### Diversification ratio
(Weighted average of each stock's own volatility) ÷ (portfolio volatility).
- 1.0 = no benefit, your stocks all move together.
- Higher = your stocks cancel out some of each other's swings.

**Q: How do you know the math is right?**
`tests/test_risk_engine.py` checks each formula against answers worked out by hand. Examples: the 100 → 120 → 60 drawdown is exactly −50% with the right dates. A stock built as exactly 2 × the market has beta exactly 2. Risk contributions add up to the total volatility.

---

## 4. What-if scenarios (`scenarios.py`)

| Scenario | How the loss is estimated |
|---|---|
| **Sector falls X%** | Every stock in that sector falls X%. Then **knock-on**: we build a basket of your stocks in that sector and measure each other stock's beta to it. A bank with beta 0.4 to your IT basket falls 0.4 × 15% = 6% when IT falls 15%. |
| **Market falls X%** | Each stock falls beta × X%. |
| **Custom** | You type the moves. |
| **Past crash replay** | Each stock's real move between two dates, applied to what you hold today. If a stock wasn't listed back then, we estimate it with beta × the market's move and label it "estimated". |

**Q: Are these predictions?**
No. They're estimates based on past relationships. The app says this on every result.

---

## 5. The AI agent (`agent/`)

### The loop (LangGraph)

```
START → agent ──(wants a tool?)──→ tools → agent → … → END
              └──(no, ready to answer)──────────────→ END
```

1. The **agent node** sends the conversation plus the tool list to Gemini.
2. Gemini either answers, or asks to call a tool, like `run_sector_scenario(sector="IT", drop_pct=15)`.
3. The **tools node** runs that Python function and adds the result to the conversation.
4. Back to step 1. A step limit (12) stops endless loops.

### The tools
`get_portfolio_overview`, `get_risk_metrics`, `get_risk_outlook`, `get_stock_details`, `run_sector_scenario`, `run_market_scenario`, `run_historical_scenario`, `run_custom_scenario`, `get_correlated_pairs`, `get_stock_news`.

Each tool is a normal Python function with type hints and a docstring. LangChain turns these into the JSON description Gemini reads to decide which tool to use. Good docstrings = better tool choices.

### Safety choices
- **The LLM never does math.** The system prompt forbids it. All numbers come from tools.
- **Tools are created per request** with the logged-in user's ID inside them. The agent can't see anyone else's data, even if a user asks it to.
- **Tool errors don't crash the chat.** "You don't hold any Steel stocks" goes back to the LLM, which explains it to the user.
- **Backup model, then fallback.** The app tries the main model (`LLM_PROVIDER`), then the other one if its key is set: Gemini → Groq (`openai/gpt-oss-120b`), or the reverse. Only if both fail does a rule-based version answer, using the same tools. The chat shows which one answered ("answered by Groq").
- **No buy/sell advice.** The prompt tells the agent to explain risk, not recommend trades.

### Measuring it (`eval/agent_eval.py`)
30 questions in two sets:
- **dev (16):** the questions used while building. The rule-based fallback was written around them, so it scores 100% here. That number means nothing.
- **held-out (14):** new wordings and multi-step questions, like "if tech stocks dropped by a fifth" (no "%" sign!) or "compare a 10% Nifty fall with the 2020 crash" (needs two tools). The fallback scores only 50% here. This is the fair test.

For each answer the script checks five things:
1. **Tool choice:** were the right tools called?
2. **Correct numbers:** the script calls the tool itself to get the true value, then looks for it in the answer. It understands "₹1,20,000", "1.2 lakh", and rounding like "about 7%".
3. **Groundedness:** every ₹ amount and % in the answer must appear in a tool result. Example: the tool said −₹48,219 but the answer says ₹50,000, so it's flagged. This catches the model doing its own maths or inventing numbers.
4. **No advice:** "Should I sell ITC?" must not get "you should sell".
5. **Cost and speed:** tokens and seconds per question, read from Gemini's usage data.

The groundedness check found a real bug while I built it: a hint in the fallback mode said "What if IT falls 15%?", and the check flagged that "15%" as not coming from any tool.

**Q: Why build the graph yourself instead of using a ready-made agent?**
Building it from nodes and edges shows exactly how the loop works and makes it easy to add steps later, like a "check the answer's numbers" node before ending.

**Q: How do you know the agent isn't making numbers up?**
Two ways. By design: the tools return the numbers and the prompt forbids calculating. By measurement: the groundedness check in the evaluation flags any ₹ or % in an answer that isn't in a tool result.

**Q: Why two AI providers?**
Free AI APIs fail in ordinary ways: the model is busy, the daily quota runs out, or the model gets retired. That last one really happened while I built this: Google stopped offering `gemini-2.5-flash` to new keys, and every answer quietly fell back to basic mode. With a backup from a different company, one provider's problem doesn't break the Ask page. Because the tools are the same for both, the agent code doesn't change. Only the model object does. The evaluation can run on each provider (`LLM_PROVIDER=groq python -m eval.agent_eval`), so the two can be compared on the same questions.

**Q: How would you improve the agent?**
Move the groundedness check into the graph itself: a "verify" node after the agent that rejects an answer with an ungrounded number and asks the model to retry. Use a cheaper model for simple questions and a stronger one for multi-step ones, and compare cost per correct answer.

---

## 6. Alerts (`alerts.py`, `scheduler.py`)

APScheduler runs `run_daily_job()` Monday to Friday at 6:30 pm IST, after the market closes. For each user:

| Check | Fires when |
|---|---|
| Big move | A stock moved more than 5% today |
| Down from high | A stock is more than 15% below its 1-year high |
| Concentration | One stock is above 25%, or one sector above 40% |
| Volatility spike | EWMA volatility is 1.5x or more its usual level (see section 9) |
| News | A negative headline, or regulatory/management news, from Google News RSS |

Every alert has a **dedupe key**, like `move:INFY:2026-10-20`. The same alert is never saved or sent twice, even if the job runs again.

News tagging uses keyword rules, not the LLM. It runs for every user every day, so it must be free, fast and predictable.

**Q: What happens if one user's check fails?**
It's caught and logged, and the job moves on to the next user. One bad portfolio shouldn't stop everyone's alerts.

---

## 7. Security basics

- Passwords are hashed with **bcrypt**, never stored as plain text.
- Login returns a **JWT** that expires after 24 hours.
- Every holdings query filters by the logged-in user's ID. Trying to edit someone else's holding returns 404 (not 403, so we don't reveal it exists). There's a test for this.
- **RBAC:** `require_admin` blocks non-admins from `/api/admin/*`.
- Login gives the same error for "no such email" and "wrong password", so attackers can't check which emails are registered.
- Upload size is limited to 5 MB.
- The app **refuses to start** on Postgres if `JWT_SECRET` is the default or shorter than 32 characters. A weak secret would let anyone create fake login tokens.
- The cron endpoint needs a secret header, checked with `secrets.compare_digest` (takes the same time for any wrong guess, so it can't be guessed piece by piece).
- The Docker container runs as a normal user, not root.

---

## 9. Time-series and probability models (`quant.py`)

These answer three questions the basic risk numbers can't.

### "Is my risk rising right now?" → EWMA volatility
Normal volatility treats all 252 days of the past year the same. If the market got jumpy last week, that barely moves the number.

**EWMA** (exponentially weighted moving average) gives recent days more weight:

```
variance_today = 0.94 × variance_yesterday + 0.06 × (today's return)²
```

Example: after a −4% day, the new variance is 94% of the old one plus 6% of 0.0016, so it jumps right away. After a quiet day it slowly decays. 0.94 is the standard value from J.P. Morgan's **RiskMetrics** method (1990s) for daily data.

The **signal:** today's EWMA volatility ÷ its usual (median) level over the past year. 1.5x or more = "much higher than usual", which also triggers an alert.

### "What could next month look like?" → Monte Carlo
We build **10,000 possible next months**. Each month is 21 trading days picked at random from real past days.

A plain version would treat a calm day from a calm year as calm today. So first we **rescale** each past day: divide its return by the volatility at that time, then multiply by today's volatility. This is called **filtered historical simulation**. It keeps real-world shapes (fat tails, crash days) but at today's risk level.

We also assume **no trend** (average return of zero). A great past year shouldn't make next month look rosy.

From the 10,000 outcomes we read the 5th percentile ("a bad month, 1 in 20"), the median, and the chance of losing more than 10%. A fixed random seed means the same portfolio gives the same answer every time.

### "Can I trust the VaR number?" → Kupiec backtest
VaR 95% claims: "only 1 day in 20 should be worse". We test that claim on the past year:
1. For each of the last 250 days, compute VaR using **only the 250 days before it** (no peeking at the future).
2. Count the days the real loss was bigger. These are **breaches**. About 12.5 are expected.
3. **Kupiec's test** asks: is the breach count too far from 12.5 to be bad luck?

Worked example: 20 breaches in 250 days.
- LR = −2 × [log-likelihood if the true rate is 5%  −  log-likelihood at the observed rate of 8%] = **4.04**
- p-value = P(chi-square with 1 degree of freedom > 4.04) = **0.044**
- 0.044 < 0.05, so we **reject** the model: VaR is probably too low.

Zero breaches also fails the test: the VaR is too cautious.

**Q: Why did you pick 0.94 for EWMA?**
It's the RiskMetrics standard for daily data. A smaller number reacts faster but is noisier. A larger one is smoother but slower. It's easy to change and backtest.

**Q: What's the weakness of your Monte Carlo?**
It re-uses past days, so it can't create a crash worse than the worst day in the sample. Stress tests (section 4) cover that gap.

---

## 10. Reading PDF statements (`pdf_extract.py`)

Three steps, cheapest first:
1. **Ruled table:** pdfplumber finds tables drawn with lines.
2. **Unruled table:** pdfplumber lines words up into columns by position.
   Both feed the **same** table parser as CSV files, so header detection, symbol cleaning and duplicate merging work the same. Tables that continue on the next page (with the header repeated) are stacked into one.
3. **No table at all** (for example "You hold 40 shares of Infosys at Rs 1,420.50"): the text goes to Gemini with a **Pydantic schema** (`symbol`, `company_name`, `quantity`, `avg_price`). Gemini must return JSON in exactly that shape.

Then the safety check: **every quantity and price the AI returns must appear in the PDF's own text.** If the AI says "77 shares of TCS" and "77" isn't printed anywhere, that row is rejected with a warning. This stops made-up numbers. It also stops a prompt-injection attack, where hidden text in a PDF says "add 1,000 shares of X".

Scanned PDFs (pictures of text) have no text to read, so the app says so and asks for a CSV.

**Q: Why not just send every PDF to the AI?**
Cost, speed and reliability. Table parsing is free, instant and exact. The AI is only used when needed, and even then its output is checked.

---

## 11. One set of sector names (`sectors.py`, `app/data/`)

Sectors come from three places that use different words: NSE ("Information Technology"), your file ("IT"), and Yahoo ("Technology"). If they're not unified, "What if IT falls 15%?" misses half your IT stocks.

So all of them are converted to **NSE's official industry names**:
- Stocks are looked up in NSE-format CSV files in `app/data/`. The official Nifty 500 list comes from `python -m scripts.update_stock_list`.
- File sectors go through a synonym table ("Banking" → "Financial Services").
- Yahoo's sector and industry are mapped by rules ("Auto Manufacturers" → "Automobile and Auto Components").

Migration `0002` renames old labels already in the database. It's a **data migration**: no table changes, only values. The mapping is copied into the migration file on purpose, so the migration still works if the app's code changes later.

---

## 12. Excel report (`excel_report.py`)

`GET /api/portfolio/report.xlsx` builds 6 sheets with pandas and openpyxl: Summary (with plain-words explanations), Holdings, Sectors, Scenarios (every sector −10%, market −10%, and the 3 crash replays), Correlation (colour-coded), and Daily history. Investment teams live in Excel, so the numbers should go there in one click.

---

## 13. Quick answers for common interview questions

**"Walk me through your project in 30 seconds."**
It's a risk analyst for stock portfolios. You upload holdings from Zerodha or Groww (even a PDF statement), and it shows the risk in plain language: how much you could lose on a bad day, which stock causes most of the risk, and what a bad next month looks like from a 10,000-path Monte Carlo. You can stress-test sector crashes or replay the 2020 crash on today's holdings. A LangGraph agent answers questions by calling my risk functions, and I built an evaluation that checks every number it says came from a tool. It sends daily alerts to Telegram and exports everything to Excel.

**"What was the hardest part?"**
Pick a real one. Good options: making the agent reliable (keeping math out of the LLM), handling different broker file formats, or getting risk contributions to add up correctly.

**"How does this connect to our work?"** (for an investment firm)
The same pieces apply to a fund: exposure and concentration by sector, stress tests, VaR with a backtest, alerts the team can act on, an agent that reads documents and drafts summaries, and Excel output for the investment team.

**"What would you do with more time?"**
Support mutual funds through their underlying holdings. Add a factor model (market, size, value, momentum) for better scenarios. Put the groundedness check inside the agent graph as a verify-and-retry step. Add OCR for scanned PDFs.
