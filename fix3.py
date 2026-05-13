"""Three final fixes before local preview."""
import csv, os, re, time
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app import create_app
app = create_app()
from models import Company, db
import requests
from bs4 import BeautifulSoup
from scraper import HEADERS

sep = "─" * 65
NPI_DESC_ORIG = "NPI-registered Geriatric Psychiatry group practice"

def _fetch(url, timeout=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""

def _meta_desc(html):
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for tag in [
        soup.find("meta", attrs={"name": "description"}),
        soup.find("meta", attrs={"property": "og:description"}),
        soup.find("meta", attrs={"name": "twitter:description"}),
    ]:
        if tag and tag.get("content", "").strip():
            d = tag["content"].strip()
            if len(d) > 20:
                return d[:500]
    return None

# ── FIX 1: Delete junk records ────────────────────────────────────────────────
print(f"\n{sep}\nFIX 1 — Delete junk records\n{sep}")
with app.app_context():
    before = Company.query.count()
    deleted = []

    # Named deletes
    for pattern in [
        "Kershaw Primary Care And Weight Loss",
        "Life In Balance Healthcare & Wellness",
    ]:
        for co in Company.query.filter(Company.company_name.ilike(f"%{pattern}%")).all():
            deleted.append(f"[{co.id}] {co.company_name}")
            db.session.delete(co)

    # Pattern: contains "Weight Loss"
    for co in Company.query.filter(Company.company_name.ilike("%Weight Loss%")).all():
        if co not in db.session.deleted:
            deleted.append(f"[{co.id}] {co.company_name} (weight loss pattern)")
            db.session.delete(co)

    db.session.commit()
    after = Company.query.count()
    for d in deleted:
        print(f"  Deleted: {d}")
    print(f"  {len(deleted)} deleted — {before} → {after} remaining")

# ── FIX 2: Symed dedup ────────────────────────────────────────────────────────
print(f"\n{sep}\nFIX 2 — Symed dedup\n{sep}")
with app.app_context():
    # Keep Symed NC LLC (symed.net — real site), delete Symed LLC (siccode.com — junk)
    keep   = Company.query.filter(Company.company_name.ilike("Symed NC%")).first()
    remove = Company.query.filter(Company.company_name.ilike("Symed, LLC")).first()

    if keep and remove:
        # Transfer year if keep is missing it
        if not keep.year_founded and remove.year_founded:
            keep.year_founded = remove.year_founded
            print(f"  Transferred year_founded={remove.year_founded} to {keep.company_name}")
        print(f"  Keeping : [{keep.id}] {keep.company_name} (website: {keep.website_url})")
        print(f"  Deleting: [{remove.id}] {remove.company_name} (website: {remove.website_url})")
        db.session.delete(remove)
        db.session.commit()
    elif not remove:
        print("  Symed LLC not found — may already be gone")
    else:
        print("  Symed NC LLC not found — skipping")

# ── FIX 3: Replace generic NPI descriptions ───────────────────────────────────
print(f"\n{sep}\nFIX 3 — Replace generic NPI descriptions\n{sep}")
with app.app_context():
    targets = Company.query.filter(
        Company.description == NPI_DESC_ORIG
    ).order_by(Company.rank_score.desc()).all()
    ids = [(c.id, c.company_name, c.website_url, c.city, c.state) for c in targets]

print(f"  Companies with generic NPI description: {len(ids)}")
print(f"  (with website: {sum(1 for _, _, w, _, _ in ids if w)})")

updated = 0
for cid, name, url, city, state in ids:
    new_desc = None

    if url:
        html = _fetch(url.rstrip("/"))
        new_desc = _meta_desc(html)
        time.sleep(1.5)

    # Fallback: generate from name/city/state
    if not new_desc:
        location = f"{city}, {state}" if city else state or ""
        new_desc = f"{name} is a behavioral health practice serving seniors in {location}.".strip(" .")
        new_desc += "."

    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        co.description = new_desc
        db.session.commit()
        updated += 1
        src = "meta" if url and new_desc and not new_desc.endswith(".") else "generated"
        print(f"  [{cid}] {name[:45]:<45} [{src}] {new_desc[:60]}…")

print(f"\n  ✓ {updated} descriptions updated")

# ── Regenerate CSV ────────────────────────────────────────────────────────────
print(f"\n{sep}\nCSV EXPORT\n{sep}")
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "bh_companies.csv")
fieldnames = [
    "company_name", "company_type", "delivery_setting", "address", "city",
    "state", "zip", "phone", "email", "website_url", "description",
    "year_founded", "employee_count_estimate", "revenue_estimate",
    "funding_status", "rank_score", "positive_signals",
    "exclude_flags", "status", "verified", "notes",
]
with app.app_context():
    all_cos = Company.query.order_by(Company.rank_score.desc()).all()
    total = len(all_cos)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for co in all_cos:
            writer.writerow({
                "company_name":            co.company_name or "",
                "company_type":            co.company_type or "",
                "delivery_setting":        co.delivery_setting or "",
                "address":                 co.address or "",
                "city":                    co.city or "",
                "state":                   co.state or "",
                "zip":                     co.zip or "",
                "phone":                   co.phone or "",
                "email":                   (co.email or "").lower(),
                "website_url":             co.website_url or "",
                "description":             (co.description or "").replace("\n", " "),
                "year_founded":            co.year_founded or "",
                "employee_count_estimate": co.employee_count_estimate or "",
                "revenue_estimate":        co.revenue_estimate or "",
                "funding_status":          co.funding_status or "",
                "rank_score":              co.rank_score or 0,
                "positive_signals":        co.positive_signals or "",
                "exclude_flags":           co.exclude_flags or "",
                "status":                  co.status or "",
                "verified":                "Yes" if co.verified else "No",
                "notes":                   (co.notes or "").replace("\n", " "),
            })

    print(f"  CSV → {csv_path}")
    print(f"\n{sep}\nFINAL STATE\n{sep}")
    score70 = sum(1 for c in all_cos if (c.rank_score or 0) >= 70)
    has_web = sum(1 for c in all_cos if c.website_url)
    has_em  = sum(1 for c in all_cos if c.email and "@" in (c.email or ""))
    has_yr  = sum(1 for c in all_cos if c.year_founded)
    print(f"  Total companies : {total}")
    print(f"  Has website     : {has_web} ({has_web*100//total}%)")
    print(f"  Has email       : {has_em} ({has_em*100//total}%)")
    print(f"  Has year founded: {has_yr} ({has_yr*100//total}%)")
    print(f"  Score 70+       : {score70}")

    print(f"\n{'─'*65}\nTOP 10 BY RANK SCORE\n{'─'*65}")
    print(f"{'#':<4} {'Score':<7} {'St':<4} {'Yr':<6} {'Web':<4} {'Email':<6} Company")
    print(f"{'─'*4} {'─'*6} {'─'*3} {'─'*5} {'─'*3} {'─'*5} {'─'*40}")
    for i, co in enumerate(all_cos[:10], 1):
        flag  = " [F]" if co.status == "flagged_for_review" else ""
        web   = "✓" if co.website_url else "—"
        email = "✓" if co.email and "@" in (co.email or "") else "—"
        print(f"{i:<4} {co.rank_score:<7} {(co.state or '??'):<4} {(co.year_founded or '—'):<6} {web:<4} {email:<6} {co.company_name}{flag}")
    print(sep)
