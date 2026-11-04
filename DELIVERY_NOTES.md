# DELIVERY NOTES — AI Smart Farming Assistant (FYP Build)

**Project:** AI Smart Farming Assistant — BSIT Final Year Project, The Islamia University of Bahawalpur
**Location:** `~/workspace/smart_farming/`
**Built:** 2026-11-04 by a 4-agent coordinator pipeline (backend / frontend+i18n / AI-engine+services workstreams + English-only cleanup pass + integration & verification)
**UI language:** English only — a deliberate scope decision by the user on 2026-11-04 (the proposal's Urdu/English objective was explicitly dropped). Zero Urdu/Arabic script verified across the codebase (Python regex scan over all .py/.html/.css/.json/.md files: no matches).

---

## 1. Exact run commands (verified verbatim)

```bash
cd ~/workspace/smart_farming
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\activate
pip install -r requirements.txt   # verified: installs clean on a FRESH venv
python data/seed.py               # idempotent; creates data/app.db, 6 fertilizers, demo user
python run.py                     # serves http://127.0.0.1:5000 (debug=True)
```

Demo login: **demo@farm.pk / demo1234**
Generate viva demo leaf images: `python demo/make_sample_leaves.py` → `demo/samples/` (healthy, spotted, blight, chlorotic, non-leaf — deterministic)

## 2. Test summary

| Check | Result |
|---|---|
| Fresh-venv `pip install -r requirements.txt` | ✅ clean install, exit 0 |
| `python data/seed.py` (fresh DB) | ✅ 6 fertilizers + demo user; re-run adds 0 rows |
| `pytest tests/` (fresh venv) | ✅ **41 passed** |
| End-to-end script (Flask test client, 23 checks) | ✅ ALL PASSED: register → login → upload synthetic blight leaf → result page shows "Blight" + treatment advice + annotated image → non-leaf upload rejected gracefully → manual-weather irrigation estimate (litres + Hargreaves formula note) → cost calculation (totals, profit, break-even) → disease & cost history pages show entries → second user sees none (per-user isolation) → 404 page |
| Live server boot + curl | ✅ `GET /` 200 (Dashboard), `GET /auth/login` 200, anonymous `/disease/` → 302 to login |
| Zero-Urdu scan | ✅ no `[\u0600-\u06FF]` matches in any source file |
| i18n remnant scan | ✅ no `t('`, `set_lang`, `session['lang']` references remain |

## 3. Verification evidence (key numbers)

- Vision engine on synthetic leaves: spotted→`leaf_spot`, blight→`blight`, chlorotic→`chlorosis`, healthy→`healthy`; non-leaf→`NoLeafDetectedError` → friendly flash. Confidence always within **55–92** (never 99/100).
- Irrigation math independently verified: Ra=41.0854 & ETo=17.9615 match hand calculation (Bahawalpur, 2026-06-15, 40/26 °C); **10 mm × 1 acre = 40468.6 L** identity holds.
- Costs math verified: hand-computed ledger (total 77000, profit 243000, break-even 9.62 maunds/acre) matches.

## 4. Architecture (as built)

```
smart_farming/
  run.py / config.py / requirements.txt / README.md / DELIVERY_NOTES.md
  app/
    __init__.py      # app factory (create_app), blueprints, error handlers
    models.py        # User, Analysis, IrrigationRecord, CostRecord, Fertilizer
    routes/          # main, auth, disease, irrigation, costs (presentation tier)
    services/        # vision, knowledge, weather, irrigation, costs (logic tier)
    templates/       # 14 Jinja templates, plain-English strings, mobile-first
    static/css/style.css   # green agri theme, responsive
  data/seed.py       # DB creation + fertilizer prices + demo user
  demo/make_sample_leaves.py  # deterministic synthetic leaf generator
  tests/             # 41 pytest tests (vision, irrigation, costs, knowledge, weather, routes)
```

## 5. Honest limitations (for the viva)

1. **The disease engine is rule-based computer vision, not a trained CNN.** It segments leaf/lesion/chlorosis regions in HSV colour space and applies documented heuristic rules. It works on clear single-leaf photos; cluttered field photos, poor lighting, or rare diseases can misclassify. A CNN (e.g., fine-tuned MobileNet on PlantVillage) could plug in behind `vision.analyze_leaf()` without touching routes — the function boundary was designed for that.
2. **Confidence is a heuristic** (55 + 37·feature-margin, capped at 92), not a calibrated probability.
3. **Weather** uses the free Open-Meteo API (no key); offline or API failure → the form falls back to manual Tmax/Tmin/humidity entry.
4. **Fertilizer prices** are approximate 2024–2025 Pakistan market values, editable at `/costs/fertilizers`.
5. **Irrigation** uses the Hargreaves temperature-based ET₀ (not Penman-Monteith — no wind/solar sensors assumed) with FAO-56 typical Kc values; soil factors are simple multipliers.
6. `Analysis.diagnosis_ur` column still exists in the model (unused after the English-only change); harmless.
7. Dev server (`python run.py`) is for demo; `gunicorn` is in requirements for production.
