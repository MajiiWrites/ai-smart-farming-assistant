# AI Smart Farming Assistant 🌱

A Flask web app (BSIT Final Year Project) that helps Pakistani farmers with three tools:

1. **Leaf Disease Detection** — upload a leaf photo, get a diagnosis (severity, confidence, diseased area) plus treatment advice.
2. **Irrigation Estimator** — enter crop, growth stage, soil, acres and weather (city or manual) to get water needs and a watering schedule.
3. **Fertilizer Cost Calculator** — bags-per-acre input with an editable market-price table, plus revenue / profit / break-even analysis.

English-only UI (a deliberate scope decision — plain English strings in the templates, no translation layer), per-user accounts with login, and a history of every analysis and calculation.

---

## Backend workstream — VS Code setup (Windows)

1. Open this folder in VS Code.
2. Create and activate a virtual environment:
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```
   (Linux/Mac: `source venv/bin/activate`)
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create the database and seed demo data (idempotent — safe to re-run):
   ```bash
   python data/seed.py
   ```
5. Start the app:
   ```bash
   python run.py
   ```
6. Open **http://127.0.0.1:5000** and log in with the demo account:
   **demo@farm.pk / demo1234**

> The student can edit fertilizer prices any time at **/costs/fertilizers** (prices ship as approximate 2024–2025 PKR values).

## Demo walkthrough (for the viva)

1. **Register/Login** — show password hashing (the DB stores only a hash; log in with the demo account).
2. **Leaf Disease Detection** — upload a leaf photo → result page shows diagnosis, confidence bar, diseased-area %, treatment advice; the same analysis appears in **History**.
3. **Irrigation Estimator** — pick wheat / mid-season / loam / 2 acres / a city → result shows litres needed, ETc, and a watering schedule.
4. **Fertilizer Costs** — enter bags per acre and other input costs → result shows total cost, profit/loss, break-even yield; edit a market price at **/costs/fertilizers** and re-run.
5. **English-only UI** — every string is plain English written directly in the templates (no translation files, no language toggle).

## Viva Q&A (short answers)

**Q: Describe the architecture.**
Three tiers: *presentation* (Jinja templates + Flask blueprints in `app/routes/`), *logic* (`app/services/` — CV engine, weather, irrigation/cost math), *data* (SQLAlchemy models in `app/models.py`). Routes never compute; services never touch the DB.

**Q: Why the app-factory pattern (`create_app()`)?**
Tests can build a fresh app per test, different configs (dev/test/prod) plug in without code edits, and it avoids circular imports between blueprints and the app object.

**Q: Why is the CV engine rule-based instead of a deep-learning model?**
No labelled leaf-disease dataset and no GPU on a student laptop/server; a colour/lesion rule-based engine (OpenCV) runs on CPU, needs no training, and its decisions are explainable in a viva.

**Q: Which formula estimates irrigation?**
The Hargreaves evapotranspiration formula (temperature-based ET₀) multiplied by a crop growth-stage coefficient (Kc) → crop water need ETc → litres per acre. Weather comes from a city lookup or manual tmin/tmax/humidity.

**Q: Why is the UI English-only?**
Keeping one language removed the whole translation layer (no `t()` helper, no language files, no session handling) — less code to explain in the viva and fewer places for bugs. It was a deliberate scope decision, not a missing feature.

**Q: Why hash passwords / why `@login_required`?**
Hashing (werkzeug PBKDF2/scrypt) means a database leak reveals no real passwords. `@login_required` guards per-user records so one user cannot open another's analysis history by guessing URLs.

---

*(Backend workstream section — other workstreams may append their own sections below.)*
