"""Data quality fixes — delete junk, clear bad URLs, fix cities, enrich descriptions."""
import csv, os, re, time
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app import create_app
app = create_app()
from models import Company, db
import requests
from bs4 import BeautifulSoup
from scraper import HEADERS

sep = "─" * 65

# ── Step 1: Named deletes ─────────────────────────────────────────────────────
NAMED_DELETES = [
    "Michigan State University",
    "Phoebe Allentown Senior Living Community",
    "Life Integrative Medicine",
    "Medop Behavioral Health Associates",
    "Psych Recovery Inc",
    "Geropsych Health",
    "Geriatric Psychiatric Services Pllc",
    "On-Site Psychiatry and Counseling",
    "Outreach Psychiatric Associates",
]

# ── Step 2: Directory domains — clear website_url ────────────────────────────
BAD_URL_DOMAINS = [
    "threebestrated.com", "freecenters.org", "rehab.com", "jrank.net",
    "telegra.ph", "myzinghealth.com", "healthgrades.com", "vitals.com",
    "doximity.com", "psychologytoday.com", "zocdoc.com",
    "npiprofile.com", "usnews.com", "ehealthscores.com",
    "carbonmedicalservice.com", "newyork-company.com", "greatnonprofits.org",
    "nhs.uk", "empassion.com", "rehabmedia.com", "npino.com", "npi.io",
    "npidb.org", "w3.health", "openmd.com", "doctor.com", "ratemds.com",
    "sharecare.com", "wellness.com", "bbb.org", "yellowpages.com",
    "yelp.com", "facebook.com", "linkedin.com",
]
NPI_DESC = "NPI-registered practice — website not yet verified"

# ── Step 3: City mismatches ───────────────────────────────────────────────────
CITY_FIXES = [
    ("Psyche Wellbeing",                    "city", None),   # Vancouver/IL mismatch
    ("Comprehensive Psychiatric Solutions", "city", None),   # Santa Rosa/MI mismatch
]

# ── helpers ───────────────────────────────────────────────────────────────────
def _fetch(url, timeout=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""

def _meta_description(html):
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for tag in [
        soup.find("meta", attrs={"name": "description"}),
        soup.find("meta", attrs={"property": "og:description"}),
        soup.find("meta", attrs={"name": "twitter:description"}),
    ]:
        if tag and tag.get("content", "").strip():
            desc = tag["content"].strip()
            if len(desc) > 20:
                return desc[:500]
    return None

def _is_bad_url(url):
    if not url:
        return False
    u = url.lower()
    return any(d in u for d in BAD_URL_DOMAINS)

# ── Step 1 ────────────────────────────────────────────────────────────────────
print(f"\n{sep}\nSTEP 1 — Named deletes\n{sep}")
with app.app_context():
    before = Company.query.count()
    deleted = []
    for pattern in NAMED_DELETES:
        cos = Company.query.filter(Company.company_name.ilike(f"%{pattern}%")).all()
        for co in cos:
            deleted.append(f"[{co.id}] {co.company_name}")
            db.session.delete(co)
    db.session.commit()
    after = Company.query.count()
    for d in deleted:
        print(f"  Deleted: {d}")
    print(f"  {len(deleted)} deleted — {before} → {after} remaining")

# ── Step 2 ────────────────────────────────────────────────────────────────────
print(f"\n{sep}\nSTEP 2 — Clear directory/junk website URLs\n{sep}")
with app.app_context():
    cleared = []
    for co in Company.query.filter(Company.website_url != None).all():
        if _is_bad_url(co.website_url):
            cleared.append(f"[{co.id}] {co.company_name[:45]:<45} was: {co.website_url[:50]}")
            co.website_url = None
            co.description = NPI_DESC
    db.session.commit()
    for c in cleared:
        print(f"  Cleared: {c}")
    print(f"  {len(cleared)} URLs cleared")

# ── Step 3 ────────────────────────────────────────────────────────────────────
print(f"\n{sep}\nSTEP 3 — Fix city mismatches\n{sep}")
with app.app_context():
    for name_pattern, field, value in CITY_FIXES:
        cos = Company.query.filter(Company.company_name.ilike(f"%{name_pattern}%")).all()
        for co in cos:
            old = getattr(co, field)
            setattr(co, field, value)
            print(f"  Fixed: {co.company_name} — {field}: '{old}' → '{value}'")
    db.session.commit()

# ── Step 4 — Meta description for top 30 with real websites ──────────────────
print(f"\n{sep}\nSTEP 4 — Fetch meta descriptions for top 30\n{sep}")
with app.app_context():
    top30 = (Company.query
             .filter(Company.website_url != None, Company.website_url != "")
             .order_by(Company.rank_score.desc())
             .limit(30).all())
    ids = [(c.id, c.company_name, c.website_url) for c in top30]

print(f"  Fetching meta descriptions for {len(ids)} companies...")
updated_desc = 0
for cid, name, url in ids:
    html = _fetch(url.rstrip("/"))
    desc = _meta_description(html)
    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        if desc and desc != NPI_DESC:
            co.description = desc
            db.session.commit()
            updated_desc += 1
            print(f"  [{cid}] {name[:45]:<45} → {desc[:60]}…")
        else:
            print(f"  [{cid}] {name[:45]:<45} → (no meta description found)")
    time.sleep(1)

print(f"\n  ✓ {updated_desc} descriptions updated")

# ── Step 5 — Regenerate CSV ───────────────────────────────────────────────────
print(f"\n{sep}\nSTEP 5 — Regenerate CSV\n{sep}")
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
    has_web   = sum(1 for c in all_cos if c.website_url)
    has_email = sum(1 for c in all_cos if c.email and "@" in (c.email or ""))
    has_yr    = sum(1 for c in all_cos if c.year_founded)
    score70   = sum(1 for c in all_cos if (c.rank_score or 0) >= 70)

    print(f"  Total companies : {total}")
    print(f"  Has website     : {has_web} ({has_web*100//total}%)")
    print(f"  Has email       : {has_email} ({has_email*100//total}%)")
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
