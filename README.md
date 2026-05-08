# dumu-behavioral-health

Acquisition target research tool for Dumu Holdings — behavioral health M&A.

Tracks founder-operated US companies delivering psychiatric, psychological, or behavioral health
services to seniors in SNFs, ALFs, memory care, and senior living communities.

## Stack

- Flask + SQLAlchemy + SQLite
- Jinja2 templates + vanilla CSS
- Gunicorn (Railway deployment)

## Local Setup

```bash
cd dumu-behavioral-health
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

App runs at http://localhost:5100

## Railway Deployment

1. Create a new Railway project
2. Connect this repo (or push code directly)
3. Railway auto-detects the Procfile: `web: gunicorn app:app`
4. Set env var: `SECRET_KEY=your-secret-here`
5. Database is SQLite by default (persisted via Railway volume if configured)

## Pages

| Route | Description |
|-------|-------------|
| `/` | Dashboard — stats, state coverage, top 10, discovery runner |
| `/companies` | Target list — filterable, sortable, color-coded by score |
| `/companies/<id>` | Company detail — full profile, signals, contacts, outreach log |
| `/companies/add` | Manual add form |
| `/flagged` | Diana's review queue — approve or reject flagged companies |
| `/outreach` | Outreach log and follow-up queue |
| `/export` | CSV and Excel export with filters |

## Scraper Logic

Run discovery from the Dashboard → "Run Discovery" panel.

**Include logic** (ALL THREE required):
- Clinical terms: psychiatry, psychiatric, behavioral health, geropsychiatry, etc.
- Senior population terms: geriatric, elderly, seniors, older adults, etc.
- Delivery setting terms: skilled nursing, SNF, assisted living, memory care, etc.

**Exclude — hard disqualify**: children, pediatric, SaaS, app-based, virtual-first, VC/PE signals

**Flag for review**: substance use disorder, EAP, workplace wellness

**Named competitors excluded**: Acadia Healthcare, Optum, Landmark Health, Carelon,
Bluestone Physician Services, Vitalic Health, Deer Oaks, Senior PsychCare, SPC Health,
Comprehensive Mobile Care, MD2U

**Ranking (1–100, start at 50)**:
- +10: founder-led/owned, family-owned, since 19XX
- +8: SNF partnerships, weekly rounds, Medicare Part B
- +5: multi-state, GUIDE model, F-tag compliance
- -10: telehealth mentions
- -15: VC/PE signals

## Seed Data

Drop a `bh_companies.csv` file in the `outputs/` directory before first run to pre-populate the DB.

Required columns: `company_name, website_url, phone, email, address, city, state, zip,
description, company_type, delivery_setting, revenue_estimate, funding_status, rank_score,
status, verified, positive_signals, notes`
