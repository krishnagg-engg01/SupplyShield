# SupplyShield — Run Guide (quick start)

For someone who just wants to **run and demonstrate** the project on Windows. Everything here uses **Command Prompt (CMD)**. A PowerShell appendix is at the end. Full detail: [DEPLOYMENT.md](DEPLOYMENT.md) and [README.md](README.md).

> **Honesty box.** The bundled data is **synthetic** (invented). Demo mode proves the app works; Exasol mode proves the Exasol integration works — neither describes a real company. Say "connected to Exasol" only when the pill is **green** and you have done the checks in Part 4.

Expected outputs below are what the project's code prints. Items marked *(unverified on Windows)* were not run on a Windows machine while writing this guide.

---

## Part 0 — Prerequisites (one time)

1. Install **Python 3.10+** from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**.
2. Open a **new** CMD window and check:
   ```bat
   python --version
   ```
   Expected: `Python 3.10.x` (or newer).

## Part 1 — Install (one time, about 2 minutes)

```bat
cd /d C:\path\to\supplyshield
setup_windows.bat
```
Replace `C:\path\to\supplyshield` with the folder that contains `app.py`. It creates `.venv`, installs `flask`, `pyexasol`, `python-dotenv`, and copies `.env.example` to `.env`. *(unverified on Windows; needs internet)*

Expected last lines:
```
Created .env from .env.example. Demo mode needs no changes to it. For Exasol mode, fill in your Exasol connection details.

Setup complete. Next: run  run_app.bat   - edit .env first only if you want Exasol mode.
```

## Part 2 — Run the DEMO (no Exasol, no internet needed)

```bat
cd /d C:\path\to\supplyshield
run_app.bat
```
Expected console output (the browser may also open by itself):
```
SupplyShield running at http://127.0.0.1:5000  (Ctrl+C to stop)
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. ...
 * Running on http://127.0.0.1:5000
```
Leave this window open. The warning is normal — this is a local demo server.

**Browser URL:** <http://127.0.0.1:5000> (if "can't connect", wait 2 seconds and refresh).

### Enter demo mode
You see **"Choose a data source"** with a note *"Exasol is not configured yet."* Click **Explore with SYNTHETIC demo data**.

**You are in demo mode when:** the top-right pill is amber **SYNTHETIC DEMO DATA**, and a banner reads *"SYNTHETIC DEMO MODE — all figures come from invented data… Nothing on this screen was read from Exasol."*

### Run one supported scenario (supplier failure) — about 1 minute
1. Left menu → **Command Center**. Under *Open disruptions* find the **Shenzhen MicroSemi** event (`D-001`, a synthetic fab fire) and click **Open in simulator →**. It pre-fills *Supplier failure*, supplier `S-SZX`, outage 21 days.
2. Press **▶ Run simulation**.
3. Read the result: stock-projection chart (no disruption / no action / recommended), the **no-action baseline**, and the recovery options with scores.
4. Optional: press **Record: approve** (or reject/defer). In demo mode it is stored in memory only.

### Confirm the results are working (demo mode)
These are the values the code produced in a test run on the default synthetic data (seed 42). Dates inside the data are relative to the day you run it, so small differences are possible, but the pattern should match:

| Where | You should see |
|---|---|
| Command Center | Risk index about **30.8 (MODERATE)**; **2 of 8** positions at risk; earliest stockout about **18.5 days**; no-action cost about **₹94,76,000** (9,476,000); 2 open disruptions |
| Simulation result, header | Mode pill `SYNTHETIC DEMO` and *"kept in memory only (demo)"* and a run id like `RUN-YYYYMMDD-HHMMSS-XXXX` |
| Recommended option | **Alternative supplier — Taipei ChipWorks** (`ALT_S-TPE`, score about 95) for the Chennai Plant and Pune Plant motor-control MCU positions; **No action** scores about 13.5 |
| Decision Log (left menu) | Your recorded decision, tagged `demo · memory` |

Optional HTTP check from a **second** CMD window while the app runs:
```bat
curl http://127.0.0.1:5000/api/status
```
Expected: JSON containing `"ui_state":"demo"` after you clicked the demo button (`"ui_state":"not_configured"` before). *(curl ships with recent Windows 10/11; unverified on Windows)*

### Stop
Click the CMD window running the app and press **Ctrl+C**.

## Part 3 — Switch between Demo and Exasol modes

| To go to… | Do this |
|---|---|
| **Demo** | **Data Source** (left menu) → **Use SYNTHETIC demo**. Works any time, with or without Exasol. |
| **Exasol** | Needs the one-time setup in Part 4. Then **Data Source** → **Test connection (SELECT 1)** → **Use Exasol data** (the button is enabled only after a successful test). |

Notes:
* If `.env` is filled in correctly and the database is seeded, the app starts **directly in Exasol mode** (green pill). Use **Use SYNTHETIC demo** to demo without it.
* Demo data is **never** substituted automatically. If Exasol fails you see a red *"Exasol · connection error"* — that is intended.
* **After editing `.env`, stop the app (Ctrl+C) and start it again.** Pressing "Test connection" alone does not re-read `.env`.

## Part 4 — Exasol mode (one-time setup, about 10 minutes)

You need an Exasol database (SaaS or Personal). For **Exasol SaaS**: the database must be **running**, your IP must be in its **allowed-IP list**, and you need the console's **connection string**, **port (8563)**, **user name** and a **personal access token** (shown once).

1. Put your details in `.env`:
   ```bat
   cd /d C:\path\to\supplyshield
   notepad .env
   ```
   Fill in (replace the `<placeholders>`; **never share or commit this file**):
   ```
   EXASOL_DSN=<connection-string>:8563
   EXASOL_USER=<user name>
   EXASOL_PASSWORD=<personal access token or password>
   ```
   Save and close Notepad.
2. Activate the environment and create the schema, tables, views:
   ```bat
   .venv\Scripts\activate
   python scripts\init_db.py
   ```
   Expected:
   ```
   Connected to Exasol. Target schema: SUPPLYSHIELD
   Executed 01_schema.sql
   Executed 02_views.sql
   Done: 21 statements. Next: python scripts/seed_db.py
   ```
3. Load the synthetic seed data:
   ```bat
   python scripts\seed_db.py
   ```
   Expected: 11 table lines (e.g. `inventory 8 rows`, `delivery_history 120 rows`) then `Seeded SYNTHETIC data (seed=42, as_of=...)`.
4. Test the connection:
   ```bat
   python -c "from supplyshield.config import get_settings; from supplyshield.db import ExasolService; print(ExasolService(get_settings()).health_check())"
   ```
   Expected: `{'ok': True, 'latency_ms': ...}`
5. Start the app (`run_app.bat` or `python app.py`) and open <http://127.0.0.1:5000>.

**Confirm Exasol mode is genuinely working** — all four should be true:
* Pill is green **Exasol · connected**; banner reads *"Live from Exasol · dataset label: SYNTHETIC (synthetic rows stored in Exasol)"*.
* **Data Source** → expand *Row counts (COUNT(\*) per table in Exasol)*: e.g. `inventory 8`, `shipments 15`.
* Run the supplier-failure scenario from Part 2. The result header says **"saved to Exasol (SCENARIO_RUNS, RECOVERY_OPTIONS)"**.
* In a SQL client on the same database, `SELECT RUN_ID, CREATED_AT, SCENARIO_TYPE, DECISION FROM SUPPLYSHIELD.SCENARIO_RUNS ORDER BY CREATED_AT DESC;` lists your run.

If you cannot tick all four, **do not say Exasol is connected.** See the table below.

## Part 5 — Run the tests
```bat
run_tests.bat
```
Expected end: `Ran 98 tests in ...s` then `OK (skipped=3)`. The 3 skipped tests need a live database; to run them: `set RUN_EXASOL_INTEGRATION=1` then `python -m unittest tests.test_integration_exasol -v`.

## Quick fixes

| You see | Do this |
|---|---|
| `'python' is not recognized` | Reinstall Python with **Add to PATH**, open a **new** CMD. |
| `Run setup_windows.bat first.` | Run `setup_windows.bat`. |
| `'pyexasol' package is not installed` | `.venv\Scripts\activate`, then `pip install -r requirements.txt`. |
| Port 5000 already in use | `set SUPPLYSHIELD_PORT=5001`, `python app.py`, open `http://127.0.0.1:5001` yourself. |
| Pill: **Exasol · not configured** | `.env` empty or still has `<placeholders>` → fill it in and restart, or click the demo button. |
| `Authentication failed` | Wrong user/password/token (SaaS: token must be valid and not revoked). |
| `Could not reach Exasol` | Wrong host/port, SaaS database stopped, your IP not in the allowed list, or firewall. |
| `TLS certificate could not be verified` | Use `host/FINGERPRINT:8563` in `EXASOL_DSN` (dev only: `EXASOL_VALIDATE_CERT=false`). |
| `schema SUPPLYSHIELD could not be opened` | Run `init_db.py`, then `seed_db.py` (Part 4). |

---

## Appendix — PowerShell equivalents *(unverified)*

Prefer CMD. Use these only if you opened PowerShell. In PowerShell you must prefix scripts in the current folder with `.\`.

```powershell
cd C:\path\to\supplyshield
.\setup_windows.bat
.\run_app.bat
```
Manual setup:
```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```
(`Set-ExecutionPolicy -Scope Process` affects only the current window.) Then the same `python scripts\init_db.py`, `python scripts\seed_db.py` and `python app.py` commands as in CMD.

Integration tests in PowerShell (CMD's `set X=1` does not work here):
```powershell
$env:RUN_EXASOL_INTEGRATION = "1"
python -m unittest tests.test_integration_exasol -v
```
Port change: `$env:SUPPLYSHIELD_PORT = "5001"`.
