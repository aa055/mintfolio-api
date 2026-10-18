# mintfolio-api docs

The FastAPI backend for Mintfolio. It is the **only** way into the data: it checks who you are, checks you own what you ask for, and does all the money and price maths.

## Read in this order

| # | Doc | Read it to… |
|---|---|---|
| 1 | [architecture.md](architecture.md) | understand the layers, the folder map, the life of a request, and the patterns every endpoint follows |
| 2 | [api-reference.md](api-reference.md) | see all 23 endpoints with inputs, outputs and errors |
| 3 | [database.md](database.md) | see the current schema, constraints, indexes, buckets and migrations |
| 4 | [pricing-and-valuation.md](pricing-and-valuation.md) | understand price sources, the daily job, and every formula, with a worked example |
| 5 | [development.md](development.md) | set up, configure, test, run migrations and run the jobs |
| — | [schema-design.md](schema-design.md) | the original design record (revision 2, May 2026): *why* the schema looks the way it does |

## Project-wide docs

Product requirements, the cross-repo architecture, database operations, deployment, testing, status and the development plan live in the **[mintfolio-docs](https://github.com/aa055/mintfolio-docs)** repo, which is the workspace folder this repo is cloned into. Start at [docs/README.md](https://github.com/aa055/mintfolio-docs/blob/main/docs/README.md).

## Where things are in the code

| I want to change… | Go to |
|---|---|
| An endpoint's URL, inputs or response | `app/routers/<area>.py` + `app/schemas/<area>.py` |
| How value / P/L / premium is calculated | `app/services/valuation.py`, `performance.py` |
| How prices are read for charts | `app/services/price_history.py` |
| Who can access what | `app/deps.py`, `app/services/portfolio_access.py` |
| Token verification | `app/services/jwt_verifier.py` |
| File uploads / buckets | `app/services/storage.py`, `app/routers/files.py` |
| A table or column | `app/models/<table>.py` **+** a new migration in `alembic/versions/` |
| The daily price job | `app/jobs/fetch_prices.py`, `.github/workflows/daily-prices.yml` |
| Settings / env vars | `app/config.py`, `.env.example` |
