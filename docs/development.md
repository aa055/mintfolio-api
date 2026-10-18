# API development guide

> **What this covers:** setting up, configuring, running, testing and operating `mintfolio-api`.
> Running both repos together: [Setup and running](https://github.com/aa055/mintfolio-docs/blob/main/docs/06-setup-and-running.md) · [Testing, QA and debugging](https://github.com/aa055/mintfolio-docs/blob/main/docs/07-testing-qa-and-debugging.md). Hosting: [Deployment](https://github.com/aa055/mintfolio-docs/blob/main/docs/05-deployment-and-environments.md).

---

## 1. Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env              # fill in values (§2)
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

- Health: <http://localhost:8000/health>
- Interactive docs (try any endpoint with a token): <http://localhost:8000/docs>

**Getting a token for `/docs`:** sign in on the web app. In the browser dev tools, the Supabase auth cookie holds `access_token`; paste it into **Authorize** as `Bearer <token>`. Or use the Supabase password grant, as `e2e/support.ts` does.

---

## 2. Configuration

All settings are read from `.env` by `app/config.py`. The full table with examples is in [Deployment §4.1](https://github.com/aa055/mintfolio-docs/blob/main/docs/05-deployment-and-environments.md#41-api-mintfolio-apienv).

| Group | Variables |
|---|---|
| Required | `DATABASE_URL`, `DATABASE_URL_SYNC`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` |
| Optional | `ENVIRONMENT`, `SUPABASE_STORAGE_BUCKET`, `SUPABASE_AVATAR_BUCKET`, `PRICE_CURRENCIES`, `CORS_ORIGINS` |
| Jobs | `GOLDAPI_KEY` (daily), `METALS_DEV_KEY` (backfill) |

**Database URL tip:** the direct host `db.<ref>.supabase.co` is IPv6-only on the free tier. On a normal IPv4 network, use the **Session pooler** host (`aws-0-ap-southeast-1.pooler.supabase.com:5432`, user `postgres.<ref>`, region Singapore). Keep the driver prefixes: `postgresql+asyncpg://` for the app and `postgresql+psycopg://` for Alembic.

---

## 3. Everyday commands

| Task | Command |
|---|---|
| Run the server | `uvicorn app.main:app --reload --port 8000` |
| Unit tests | `pytest` (33 tests, ~2 s) |
| Tests with coverage | `pytest --cov=app` |
| Lint / format | `ruff check .` · `ruff format .` |
| Type check | `mypy app` (strict; 21 known typing errors) |
| New migration | `alembic revision --autogenerate -m "…"` then **read the file** |
| Apply / undo | `alembic upgrade head` · `alembic downgrade -1` |
| Today's prices | `python -m app.jobs.fetch_prices` (`--force` to replace today) |
| History backfill | `python -m app.jobs.backfill_prices --dry-run`, then without the flag. Options: `--years N`, `--fill-gaps`, `--max-calls N` |

---

## 4. Tests

| File | What it checks |
|---|---|
| `tests/test_health.py` | `/health` responds |
| `tests/test_valuation.py` | purity parsing, item values, summary totals, other-currency handling |
| `tests/test_price_history.py` | ranges, gap filling (carry forward), daily rules |
| `tests/test_performance.py` | value-vs-invested series, held-until-sale, today's change, premium (entered vs market) |

The maths services take **plain dataclasses** (`HoldingInput`, rate series), so these tests need no database. Endpoints are exercised end to end by the web repo's Playwright suite (`mintfolio-web/e2e`).

**Writing a new test:** build `HoldingInput(...)` objects and a rates dict or series, call the service function, and assert on `Decimal` values (compare with `Decimal("…")`, never floats).

---

## 5. Daily job on GitHub Actions

File: `.github/workflows/daily-prices.yml`.

| Setting | Value |
|---|---|
| Schedule | `37 16 * * 1-5` (weekdays 16:37 UTC). In practice it starts 5–7 h late. |
| Manual run | Actions → **Daily metal prices** → Run workflow (tick *force* to re-fetch today) |
| Secrets | `DATABASE_URL` (pooler URL), `GOLDAPI_KEY` |
| Other env | `PRICE_CURRENCIES=AED`. The remaining required settings get dummy values; the job doesn't use them. |
| Concurrency | `daily-prices` group, so two runs never overlap |
| Auto-disable | after 60 days without commits (public repo). Re-enable it in the Actions tab. |

Check that it ran: Actions tab (green ✔), or

```sql
select metal, purity, rate_per_gram, fetched_at
from price_history where source = 'goldapi'
order by fetched_at desc limit 10;
```

---

## 6. Code style

- Ruff rules: `E W F I B UP N SIM`, line length 100, isort with `app` first-party.
- Types on every function (mypy strict).
- Money is `Decimal`; never convert it to `float`.
- Keep routers thin; put logic in `app/services` with a unit test.
- Load relationships explicitly. They're `lazy="raise"` on purpose.
- Patterns and the new-endpoint checklist: [architecture.md](architecture.md#7-adding-a-new-endpoint-checklist).
