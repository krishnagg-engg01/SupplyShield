# SupplyShield — Deployment Guide

This guide takes you from a clean Windows computer to a running SupplyShield, first in **demo mode** (no database), then connected to an **Exasol** database. It also says plainly what is **not** production-ready.

**Conventions.** Commands are for **Windows Command Prompt (CMD)**. Replace `C:\path\to\supplyshield` with your folder (the one that contains `app.py`). `(unverified)` marks steps that follow the project files but were **not executed** while writing this guide — see the [verification status](#8-verification-status-what-was-and-was-not-run) at the end.

**Contents:** 1 Local setup · 2 Demo mode · 3 Exasol database · 4 Credentials · 5 Schema and seed order · 6 Verify reads and writes · 7 Start/stop · 8 Production · 9 Verification status

---

## 1. Local Windows development setup

1. **Install Python 3.10+** from <https://www.python.org/downloads/>. Tick **"Add python.exe to PATH"**. Open a *new* CMD window and check:
   ```bat
   python --version
   ```
   Expected: `Python 3.10.x` or newer.
2. **Get the project** (unzip `SupplyShield_v2.zip`, or clone it) so you have a folder containing `app.py`, `requirements.txt`, `sql\`, `scripts\`.
3. **Create the environment and install dependencies** — one step:
   ```bat
   cd /d C:\path\to\supplyshield
   setup_windows.bat
   ```
   Manual equivalent:
   ```bat
   cd /d C:\path\to\supplyshield
   python -m venv .venv
   .venv\Scripts\activate
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   copy .env.example .env
   ```
   Dependencies installed (from `requirements.txt`): `flask`, `pyexasol`, `python-dotenv`. `(unverified on Windows)`
4. **Run the unit tests** to confirm the installation:
   ```bat
   run_tests.bat
   ```
   Expected last lines: `Ran 98 tests in ...s` and `OK (skipped=3)`. The 3 skips are live-database tests and are normal at this stage.

## 2. Run in demo mode (no Exasol)

```bat
run_app.bat
```
Expected console line: `SupplyShield running at http://127.0.0.1:5000  (Ctrl+C to stop)`, followed by Flask's own warning that this is a development server.

In the browser (<http://127.0.0.1:5000>) click **Explore with SYNTHETIC demo data**. Demo mode is only ever entered by this explicit click. You will see an amber **SYNTHETIC DEMO DATA** pill and a banner saying nothing was read from Exasol. Simulation runs and decisions are kept **in memory only** and disappear when you stop the app.

## 3. Configure an Exasol database

SupplyShield connects with a host:port, a user name and a password. It works the same way for Exasol SaaS and Exasol Personal; only where you find the three values differs.

### 3a. Exasol SaaS checklist

Based on Exasol's SaaS documentation for connecting client tools:

1. The **database must be running** (SaaS databases can be stopped).
2. **Your IP address must be in the database's allowed-IP list** (web console → *Security* / *Network Security*). Without this the connection times out.
3. In the console, open the database's **connect details** and copy the **connection string**, the **port** (default **8563**) and the **user name**.
4. Create a **personal access token (PAT)**. It is **shown only once** — copy it immediately; if lost, create a new one.
5. Map them to the app:

   | Exasol SaaS gives you | Goes in `.env` as |
   |---|---|
   | connection string + port | `EXASOL_DSN=<connection-string>:8563` |
   | user name | `EXASOL_USER=<user name>` |
   | personal access token | `EXASOL_PASSWORD=<token>` |

6. TLS is on by default (`EXASOL_ENCRYPTION=true`) and SaaS requires it. If you get a certificate error, put the **certificate fingerprint** into the DSN: `host/FINGERPRINT:8563`. As a last resort for development only, set `EXASOL_VALIDATE_CERT=false`.
7. The user needs rights to **create a schema, tables and views** and to **insert, update and delete** rows.

> **Unverified:** the app passes the token as the *password* to PyExasol, which matches Exasol's documented "user name + PAT as password" for SQL clients. This has **not been tested** against a SaaS database here. PyExasol also offers a separate `refresh_token` login for SaaS, which this app does not use. If your database rejects the PAT-as-password login, adding token support to `supplyshield/db.py` would be required.

### 3b. Exasol Personal
Use the host/IP, port, user and password from your instance's connection details.

## 4. Secure configuration of credentials

1. Create your private config file (skip if `setup_windows.bat` already did):
   ```bat
   copy .env.example .env
   notepad .env
   ```
2. Fill in the three required values. Example of the **shape** (fake values — never use these):
   ```
   EXASOL_DSN=your-database-host.example:8563
   EXASOL_USER=your_user
   EXASOL_PASSWORD=paste_your_token_or_password_here
   EXASOL_SCHEMA=SUPPLYSHIELD
   EXASOL_VALIDATE_CERT=true
   ```
3. **Keep it out of Git.** `.gitignore` already excludes `.env`. Before any commit:
   ```bat
   git check-ignore -v .env
   git status
   ```
   The first command should print a rule from `.gitignore`; `git status` must **not** list `.env`.
4. Do not put real values in `.env.example`, screenshots, chat, or a ZIP you share. If a credential leaks, revoke or replace it in Exasol first.
5. **Restart the app after every `.env` change.** `.env` is read once at start-up. Real Windows environment variables of the same name override the file.

An untouched `.env` (all `<placeholder>` values) counts as "not configured" — the app will not try to connect with placeholders.

## 5. Create the schema and load the seed data (order matters)

Run from the project folder with the environment active (`.venv\Scripts\activate`).

**Step 1 — schema, tables, views (once):**
```bat
python scripts\init_db.py
```
Expected:
```
Connected to Exasol. Target schema: SUPPLYSHIELD
Executed 01_schema.sql
Executed 02_views.sql
Done: 21 statements. Next: python scripts/seed_db.py
```
Behaviour to know: it refuses to run if the schema already contains tables. `python scripts\init_db.py --reset` **drops the schema and everything in it (including saved simulation history)** and recreates it.

**Step 2 — synthetic seed data:**
```bat
python scripts\seed_db.py
```
Expected: 11 lines (`dataset_meta 5`, `components 6`, `suppliers 8`, `supplier_components 10`, `factories 3`, `production_lines 8`, `routes 14`, `inventory 8`, `shipments 15`, `delivery_history 120`, `disruptions 3` rows), then `Seeded SYNTHETIC data (seed=42, as_of=<today>). Scenario history tables were left untouched.`

Seeding replaces the 11 seed tables only and is safe to repeat. Optional: `--seed 42 --as-of 2026-10-16` for a fixed reference date.

Why this order: the seed script needs the tables and views from step 1, and the app needs both.

## 6. Verify connectivity and real database reads/writes

Do **all** of these before telling anyone "Exasol is connected".

**6.1 Connection test from CMD:**
```bat
python -c "from supplyshield.config import get_settings; from supplyshield.db import ExasolService; print(ExasolService(get_settings()).health_check())"
```
Success: `{'ok': True, 'latency_ms': <number>}`. (It runs a real `SELECT 1`.)

**6.2 Start the app and check reads.** `python app.py`, open <http://127.0.0.1:5000>. With a valid `.env` and seeded data it opens directly in Exasol mode: green **Exasol · connected** pill and a banner "Live from Exasol · dataset label: SYNTHETIC … (synthetic rows stored in Exasol)". On **Data Source**, press **Test connection (SELECT 1)**, then expand **Row counts (COUNT(*) per table in Exasol)** under *Active dataset*: the counts should match the seed counts above (these come from `SELECT COUNT(*)` queries against Exasol).

**6.3 Verify a write.** In **Simulator & Recovery** run any scenario. The result header must say **"saved to Exasol (SCENARIO_RUNS, RECOVERY_OPTIONS)"** (if saving failed it shows "The simulation ran, but saving it to Exasol failed: …" instead). Record a decision (**Record: approve**, **Record: reject** or **Defer**). Then in a separate SQL client (e.g. DbVisualizer or DBeaver — Exasol documents connecting both to SaaS) run:
```sql
SELECT RUN_ID, CREATED_AT, SCENARIO_TYPE, DECISION, SELECTED_OPTION FROM SUPPLYSHIELD.SCENARIO_RUNS ORDER BY CREATED_AT DESC;
SELECT RUN_ID, OPTION_ID, SCORE, IS_RECOMMENDED FROM SUPPLYSHIELD.RECOVERY_OPTIONS ORDER BY RUN_ID DESC;
SELECT META_KEY, META_VALUE FROM SUPPLYSHIELD.DATASET_META;
```
You should see your run in `SCENARIO_RUNS` (with the decision), its evaluated options in `RECOVERY_OPTIONS`, and `label = SYNTHETIC` in `DATASET_META`.

**6.4 Verify failure is honest (optional).** Stop the SaaS database (or block the network) and press **Refresh data**. You must see a connection error, **not** demo data.

**6.5 Live integration tests (optional, read-only):**
```bat
set RUN_EXASOL_INTEGRATION=1
python -m unittest tests.test_integration_exasol -v
```
Expected: `Ran 3 tests ... OK` with **0 skipped**. Only a pass here counts as automated proof against your database.

## 7. Start and stop the Flask application

**Start:** `run_app.bat` (activates `.venv`, opens the browser, runs `python app.py`), or manually:
```bat
.venv\Scripts\activate
python app.py
```
Settings (optional, CMD, current window only):
```bat
set SUPPLYSHIELD_PORT=5001
set SUPPLYSHIELD_HOST=127.0.0.1
python app.py
```
Default is `127.0.0.1:5000`. `run_app.bat` always opens port 5000 in the browser; if you change the port, open the new address yourself.

**Stop:** press **Ctrl+C** in the CMD window running the app.

If the window was closed but the server still runs `(unverified)`:
```bat
netstat -ano | findstr :5000
taskkill /PID <the-number-in-the-last-column> /F
```

**Switch modes without restarting:** Data Source page → **Use SYNTHETIC demo** or **Use Exasol data** (the latter is enabled only after a successful connection test). Changed `.env`? Restart first.

## 8. Production considerations

**SupplyShield, as delivered, is a local demo and development application. It is not a production deployment and must not be described as one.** `python app.py` starts Flask's built-in development server (it prints a warning saying exactly that). The repository contains no production server configuration, container image, CI/CD pipeline, or infrastructure code.

Work that would be required before a real deployment:

| Area | Current state | What is needed |
|---|---|---|
| Web server | Flask development server | Run behind a production WSGI server (for example Waitress on Windows) and a reverse proxy; none is configured or in `requirements.txt` |
| HTTPS | none | TLS termination at the proxy/load balancer |
| Authentication / authorisation | **none** — anyone who can reach the port can switch data source, run simulations and write decisions to Exasol | Login (e.g. SSO), roles, audit trail of who approved what |
| State | Active mode, cached dataset and demo runs live **in the memory of one process** | Verify behaviour with several workers/instances (each would have its own state) or keep a single worker; move session/mode state out of process |
| Database access | A new connection per query; one shared credential | Connection pooling, a least-privilege service account, query timeouts and retries |
| Secrets | `.env` file on disk | A secrets manager or protected environment variables; rotation of the token/password |
| Data | Synthetic only; no import pipeline | Real ERP/WMS/TMS data integration, validation, refresh scheduling, data-quality checks |
| Operations | Console logging only | Structured logs, monitoring and alerting, backups of `SCENARIO_RUNS` / `RECOVERY_OPTIONS`, a restart policy |
| Quality | 98 unit tests with test doubles; 3 live tests, never run by the author of this guide | Run the integration tests in a staging environment; load and security testing; dependency pinning (`requirements.txt` uses minimum versions only) |
| Model | Planning assumptions in `config.py`, no forecasts | Calibrate assumptions with real operations data; business sign-off on thresholds |
| Exasol SaaS | PAT passed as password; not verified | Confirm authentication on your database; consider PAT/refresh-token handling and expiry |

Until that work is done, keep the app bound to `127.0.0.1` and use it for demonstration.

## 9. Verification status: what was and was not run

| Item | Status |
|---|---|
| 98 unit tests (3 skipped live tests), Python 3.12 on Linux | **Run — passed** |
| App start (`python app.py`), `/` and `/api/status` over HTTP, switching to demo mode, running the supplier-failure scenario and recording a decision in demo mode | **Run — worked** (Linux, no Exasol) |
| `.env.example` placeholders treated as "not configured" | **Run — fixed and covered by a new test** |
| `.env` edits not applied without restart | **Run — confirmed**; documented, UI hint corrected |
| `setup_windows.bat`, `run_app.bat`, `run_tests.bat`, `.venv\Scripts\activate`, `netstat`/`taskkill` | **Unverified** (no Windows machine; the `.bat` files were converted to Windows line endings) |
| `pip install -r requirements.txt` | **Unverified** (no network in the authoring sandbox; `pyexasol` was not installed there) |
| Connection to any Exasol database (SaaS or Personal) | **Unverified** |
| `init_db.py`, `seed_db.py`, `sql\01_schema.sql`, `sql\02_views.sql` executing on Exasol | **Unverified** (the printed "21 statements" and row counts were computed from the files and the generator, not from a database) |
| Live reads/writes (`SCENARIO_RUNS`, `RECOVERY_OPTIONS`) and the 3 integration tests | **Unverified** |
