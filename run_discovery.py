"""
Standalone discovery runner — Dumu Holdings Behavioral Health.
Runs all 15 states × 10 queries + NPI registry per state + directory scrape.

Usage:
    python run_discovery.py
    python run_discovery.py --states TX FL GA   (subset)
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime

# Suppress noisy HTTP-level logging from ddgs/primp
logging.basicConfig(level=logging.WARNING)
for noisy in ("primp", "httpx", "httpcore", "ddgs", "urllib3", "requests"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

# ── Setup Flask app context ───────────────────────────────────────────────────
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app import create_app

app = create_app()

from models import Company, db
from scraper import (PRIORITY_STATES, SEARCH_QUERIES, STATE_NAMES,
                     discover_companies_by_state, discover_from_npi_by_state,
                     discover_from_directories)

# ── Args ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--states", nargs="*", default=PRIORITY_STATES)
args = parser.parse_args()
states = args.states

# ── Counters ──────────────────────────────────────────────────────────────────
grand_total    = 0
grand_high     = 0
grand_flagged  = 0
grand_excluded = 0

start_time = datetime.now()
sep = "─" * 65

print(sep)
print(f"DUMU HOLDINGS — BH ACQUISITION DISCOVERY")
print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"States:  {', '.join(states)}")
print(f"Queries: {len(SEARCH_QUERIES)} per state  |  Total: {len(states) * len(SEARCH_QUERIES)}")
print(sep)

# ── Track pre-existing DB count ───────────────────────────────────────────────
with app.app_context():
    pre_existing = Company.query.count()
print(f"Pre-existing companies in DB: {pre_existing}")
print()

# ── Per-state progress lines ──────────────────────────────────────────────────
state_results = []

for state in states:
    print(f"\n{'═'*65}")
    print(f"  STATE: {state}")
    print(f"{'═'*65}")

    state_log = []

    def progress(msg):
        print(f"  {msg}", flush=True)
        state_log.append(msg)

    new_cos = discover_companies_by_state(state, None, app, progress_cb=progress)

    # NPI registry pass for this state
    print(f"\n  [NPI] Querying registry for {state}...")
    npi_cos = discover_from_npi_by_state(state, app, progress_cb=progress)
    new_cos = new_cos + npi_cos

    state_high    = sum(1 for c in new_cos if c["score"] >= 70)
    state_flagged = sum(1 for c in new_cos if c["flagged"])

    grand_total   += len(new_cos)
    grand_high    += state_high
    grand_flagged += state_flagged

    summary = (
        f"STATE COMPLETE: {state} | {len(new_cos)} companies | "
        f"{state_high} scored 70+ | {state_flagged} flagged"
    )
    print(f"\n  {'▶'} {summary}")
    state_results.append({"state": state, "n": len(new_cos), "high": state_high, "flagged": state_flagged})

# ── Directory pass (AAGP + Psychology Today) ─────────────────────────────────
print(f"\n{'═'*65}")
print(f"  DIRECTORY PASS: AAGP + Psychology Today")
print(f"{'═'*65}")
dir_cos = discover_from_directories(app, progress_cb=lambda m: print(f"  {m}", flush=True))
grand_total   += len(dir_cos)
grand_high    += sum(1 for c in dir_cos if c["score"] >= 70)
grand_flagged += sum(1 for c in dir_cos if c["flagged"])
print(f"\n  ▶ DIRECTORIES COMPLETE | {len(dir_cos)} additional companies")

# ── Final summary ─────────────────────────────────────────────────────────────
elapsed = datetime.now() - start_time
print(f"\n{sep}")
print(
    f"SCRAPE COMPLETE | {grand_total} companies | "
    f"{grand_high} scored 70+ | "
    f"{grand_flagged} flagged for review | "
    f"{grand_excluded} disqualified"
)
print(f"Duration: {str(elapsed).split('.')[0]}")
print(sep)

# ── Export to CSV ─────────────────────────────────────────────────────────────
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "bh_companies.csv")
os.makedirs(os.path.dirname(csv_path), exist_ok=True)

fieldnames = [
    "company_name", "company_type", "delivery_setting", "address", "city",
    "state", "zip", "phone", "email", "website_url", "description",
    "revenue_estimate", "funding_status", "rank_score", "positive_signals",
    "exclude_flags", "status", "verified", "notes",
]

with app.app_context():
    all_cos = Company.query.order_by(Company.rank_score.desc()).all()
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for co in all_cos:
            writer.writerow({
                "company_name":    co.company_name or "",
                "company_type":    co.company_type or "",
                "delivery_setting":co.delivery_setting or "",
                "address":         co.address or "",
                "city":            co.city or "",
                "state":           co.state or "",
                "zip":             co.zip or "",
                "phone":           co.phone or "",
                "email":           (co.email or "").lower(),
                "website_url":     co.website_url or "",
                "description":     (co.description or "").replace("\n", " "),
                "revenue_estimate":co.revenue_estimate or "",
                "funding_status":  co.funding_status or "",
                "rank_score":      co.rank_score or 0,
                "positive_signals":co.positive_signals or "",
                "exclude_flags":   co.exclude_flags or "",
                "status":          co.status or "",
                "verified":        "Yes" if co.verified else "No",
                "notes":           (co.notes or "").replace("\n", " "),
            })

print(f"\nExported {len(all_cos)} total companies → {csv_path}")

# ── Top 10 by rank score ──────────────────────────────────────────────────────
print(f"\n{'─'*65}")
print("TOP 10 COMPANIES BY RANK SCORE")
print(f"{'─'*65}")
print(f"{'#':<4} {'Score':<7} {'State':<6} {'Company'}")
print(f"{'─'*4} {'─'*6} {'─'*5} {'─'*45}")

with app.app_context():
    top10 = (
        Company.query
        .filter(Company.acquirable == True)
        .order_by(Company.rank_score.desc())
        .limit(10)
        .all()
    )
    for i, co in enumerate(top10, 1):
        flag = " [FLAGGED]" if co.status == "flagged_for_review" else ""
        print(f"{i:<4} {co.rank_score:<7} {(co.state or '??'):<6} {co.company_name}{flag}")

print(f"{'─'*65}")
print(f"\nDone. Run the Flask app to view results: python app.py")
