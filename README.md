# Transaction Ledger API

A PostgreSQL-backed FastAPI service for zero-balance accounts, immutable ledger entries,
balance retrieval, filtered transaction history, and atomic transfers. The implementation
covers the assessment's mandatory backend requirements and its money-transfer bonus.
There is no frontend.

Live assessment demo: [Swagger UI](https://ledger-api.187.127.162.233.sslip.io/docs),
[health](https://ledger-api.187.127.162.233.sslip.io/health),
[OpenAPI](https://ledger-api.187.127.162.233.sslip.io/openapi.json).
Source: [GitHub](https://github.com/MohammedMaheer/transaction-ledger-api).
Use fictional data in the shared public sandbox.

## Stack and structure

Python 3.12+, FastAPI, SQLAlchemy 2.0 async ORM, asyncpg, PostgreSQL 16, Pydantic v2,
Alembic, Uvicorn, Pytest, and HTTPX. Direct dependencies are pinned in `requirements.txt`.

```text
transaction-ledger/
├── app/
│   ├── main.py                    # App factory, lifecycle, readiness
│   ├── core/
│   │   ├── config.py              # Environment settings
│   │   ├── database.py            # Engine and per-request sessions
│   │   └── exceptions.py          # Consistent public errors
│   ├── models/
│   │   ├── account.py
│   │   └── transaction.py
│   ├── schemas/
│   │   ├── account.py
│   │   └── transaction.py
│   ├── api/
│   │   ├── accounts.py
│   │   ├── transactions.py
│   │   └── transfers.py
│   └── services/
│       ├── account_service.py
│       └── transaction_service.py
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/0001_create_ledger.py
├── tests/
│   ├── conftest.py
│   ├── helpers.py
│   ├── test_accounts.py
│   ├── test_transactions.py
│   ├── test_transfers.py
│   ├── test_concurrency.py
│   ├── test_database_integrity.py
│   └── test_health.py
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── docker-compose.production.yml
├── deploy/
│   ├── nginx.conf
│   └── HOSTINGER.md
├── requirements.txt
├── pyproject.toml
├── alembic.ini
├── README.md
├── ASSUMPTIONS.md
└── API_DOCUMENTATION.md
```

Routes validate inputs and delegate to services. Services own database transaction
boundaries and financial rules. Models declare persistence constraints; schemas define
the API contract. Migrations are explicit and are never replaced by startup `create_all`.

## Quick start with Docker Compose

Requires Docker Engine/Desktop and Docker Compose v2. From this directory:

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs migrate api
curl --fail http://localhost:8000/health
```

PostgreSQL initializes the configured user and database on its first start. The `migrate`
service waits for the database health check, runs `alembic upgrade head`, and must succeed
before the API starts. PostgreSQL data is stored in the `ledger_data` named volume.
The API container runs as an unprivileged user. Host ports bind to loopback.

If port 5432 or 8000 is occupied, set `POSTGRES_PORT` or `API_PORT` in `.env` before
starting. Container-to-container database connections always use `db:5432`; update
`DATABASE_URL` separately if running Python on the host against a changed database port.

```bash
docker compose down                 # Stop services; preserve data
docker compose run --rm migrate     # Apply migrations after a schema update
```

Do not remove the database volume unless intentionally discarding its data. The example
passwords are for local development. Use URL-encoded credentials in connection URLs.

## Run Python locally

Install Python 3.12+ and PostgreSQL 16 (or use `docker compose up -d db`). With a local
PostgreSQL server, initialize a dedicated role and databases using an administrator:

```bash
createuser --pwprompt ledger
createdb --owner=ledger ledger
createdb --owner=ledger ledger_test
```

Choose the development password from `.env.example` when prompted, or update both
connection URLs with the password you chose. The test database must be disposable.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`: `DATABASE_URL` must use `postgresql+asyncpg://` and point to your development
database. For two databases on one local PostgreSQL server, set `TEST_DATABASE_URL` to
`postgresql+asyncpg://ledger:ledger_local_password@localhost:5432/ledger_test`.
The example file instead points tests at the optional Compose test database on port 5433.

```bash
alembic upgrade head
alembic current
alembic check
uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Configuration variables:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Required async PostgreSQL URL for the API and Alembic |
| `TEST_DATABASE_URL` | Separate disposable database used only by Pytest |
| `LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, or `CRITICAL` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Compose database initialization |
| `POSTGRES_PORT`, `API_PORT` | Compose host ports; defaults 5432 and 8000 |

Existing environment variables override `.env`. Changing Compose initialization credentials
does not change a role in an already initialized PostgreSQL volume.

## Automated tests

Tests exercise the actual ASGI application, database services, and real PostgreSQL commits.
No SQLite substitute or mocked financial logic is used. The fixture applies Alembic
migrations and truncates `accounts` and `transactions` before each test. It checks ledger
reconciliation after every test. A database name ending in `_test` is mandatory, and the
test URL must differ from the configured application URL. Do not run two test processes
against the same database.

Using the local environment configured above:

```bash
pytest -q --cov=app --cov-report=term-missing
ruff check .
ruff format --check .
```

Or run the complete suite inside Docker, with its own ephemeral PostgreSQL instance:

```bash
docker compose --profile test run --build --rm tests
docker compose --profile test stop test-db
```

To run host Python against that isolated Compose test database:

```bash
docker compose --profile test up -d --wait test-db
TEST_DATABASE_URL=postgresql+asyncpg://ledger:ledger_test_password@localhost:5433/ledger_test pytest -q
```

Coverage includes account creation and validation, exact decimal arithmetic, financial
limits, missing accounts, duplicates, cross-account reference reuse, filtering, pagination,
timestamp ties, API immutability, transfers, retry behavior, and database constraint failures.
Concurrency tests hold a PostgreSQL row lock until all competing requests are observed
waiting in `pg_stat_activity`, then release it. They verify overspend prevention, no lost
updates, duplicate credits/transfers, and opposite-direction transfers. A lock timeout test
also verifies the safe retry response. The test database owner can inspect its own sessions.

### Verification performed

On 26 October 2026, Python 3.13.12 with PostgreSQL 16.13 completed **113 tests in 22.06
seconds, all passing** (`pytest -q --cov=app --cov-report=term-missing`; reported application
line coverage: 86%). Alembic upgrade, downgrade/re-upgrade on the disposable test database,
and `alembic check` passed. Ruff lint/format checks, Python 3.12 syntax parsing, and
`pip check` passed. A live Uvicorn HTTP check exercised account creation, credits, debits,
transfers, duplicates, balance/history retrieval, validation errors, health, and OpenAPI;
a direct PostgreSQL query reconciled stored balances with ledger totals.

Docker was not installed locally, so its path was verified on the Hostinger VPS instead.
The Linux container run used Python 3.12.15 and an isolated PostgreSQL 16 test service:
**113 tests passed in 19.08 seconds**, including coverage reporting, with exit code zero.
The production image built successfully and its Alembic migration and readiness check passed.
To reproduce the Docker setup:

```bash
cp .env.example .env
docker compose up --build -d --wait
curl --fail http://localhost:8000/health
docker compose --profile test run --build --rm tests
```

The VPS uses a separate production Compose file with an internal PostgreSQL service and
an API port bound to loopback behind Nginx/HTTPS. See [Hostinger deployment instructions](deploy/HOSTINGER.md).

## Endpoints and interactive documentation

| Method | Endpoint | Success |
| --- | --- | --- |
| POST | `/api/v1/accounts` | 201: account with zero balance |
| POST | `/api/v1/accounts/{account_id}/transactions` | 201: credit or debit entry |
| GET | `/api/v1/accounts/{account_id}/balance` | 200: current balance |
| GET | `/api/v1/accounts/{account_id}/transactions` | 200: filtered, paginated history |
| POST | `/api/v1/transfers` | 201: source debit and destination credit |
| GET | `/health` | 200: database reachable and tables present; otherwise 503/500 |

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI JSON: <http://localhost:8000/openapi.json>

Use the actual returned UUID in place of `ACCOUNT_ID`:

```bash
curl -sS -X POST http://localhost:8000/api/v1/accounts \
  -H 'Content-Type: application/json' -d '{"name":"John Doe"}'

curl -sS -X POST http://localhost:8000/api/v1/accounts/ACCOUNT_ID/transactions \
  -H 'Content-Type: application/json' \
  -d '{"type":"credit","amount":"100.00","description":"Initial deposit","reference_id":"DEP-001"}'

curl -sS http://localhost:8000/api/v1/accounts/ACCOUNT_ID/balance
curl -sS 'http://localhost:8000/api/v1/accounts/ACCOUNT_ID/transactions?type=credit&page=1&limit=10'

curl -sS -X POST http://localhost:8000/api/v1/transfers \
  -H 'Content-Type: application/json' \
  -d '{"source_account_id":"SOURCE_UUID","destination_account_id":"DESTINATION_UUID","amount":"30.00","reference_id":"TRF-001","description":"Account transfer"}'
```

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for the complete contract and
[ASSUMPTIONS.md](ASSUMPTIONS.md) for monetary and reference semantics.

## Integrity and design decisions

- All monetary arithmetic uses `Decimal`; database amounts and balances use `NUMERIC(18,2)`.
  Requests require decimal strings, and responses use strings with exactly two decimal places.
- Every financial operation uses one `async with session.begin()` block. Successful exit
  commits once; flush or commit errors automatically roll back every affected row.
- Writers acquire `SELECT ... FOR UPDATE` account locks before checking references or funds.
  Transfers lock UUIDs in ascending order, preventing cycles between these supported writers.
  A fresh async session belongs to each request, following the
  [SQLAlchemy concurrency guidance](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks).
- Database constraints enforce nonnegative balances, positive finite amounts, valid types,
  nonblank names/references, foreign keys, and unique `(account_id, reference_id)` pairs.
  Financial service transactions preserve the aggregate balance-to-ledger invariant.
- Reference conflicts return 409, including retries with changed payloads. A transfer uses
  the same reference on both accounts; any collision rolls the whole operation back.
- The history index is `(account_id, created_at DESC, id DESC)`. Filtering, counting, sorting,
  and pagination happen in PostgreSQL. A brief shared account lock keeps count and page
  queries consistent with concurrent supported writers.
- Lock waits are bounded at 5 seconds, statements at 15 seconds. Known timeout/deadlock/
  serialization conflicts return 409 so the caller can retry the same reference safely.
  Connection establishment and pool checkout waits are bounded at 5 seconds and return
  503 when unavailable.
- Exception handlers return one JSON error envelope and never include SQL, credentials,
  raw request inputs, or stack traces. There are no update/delete ledger endpoints.
- Authentication is outside this assessment. Put authentication/authorization and TLS in
  place before exposing account access to untrusted clients. Direct database administrator
  writes are outside the API's integrity contract; no aggregate-maintenance triggers are used.

## Assessment requirement map

| Requirement | Implementation / verification |
| --- | --- |
| Unique server IDs, required name, zero initial balance, system timestamps | Account schema/model/service; account tests |
| Credit/debit rules, sufficient funds, duplicate handling | Transaction service, row locks, unique constraint; transaction/concurrency tests |
| Balance retrieval and missing-account errors | Account routes/service; account tests |
| Type filtering, pagination metadata, latest-first sorting | History service and composite index; history tests |
| Immutable transactions and consistent balances | No mutation routes; reconciliation after every integration test |
| Atomic record + balance writes and failure rollback | Single transaction boundary; injected PostgreSQL constraint failure tests |
| Validation and consistent error/status handling | Pydantic input schemas and exception handlers; invalid-input tests |
| Bonus atomic transfer | Two locked accounts/two entries/one commit; transfer and concurrency tests |
| Runnable application, migrations, submission documentation | Compose, Dockerfile, Alembic, this README, API docs, assumptions |
