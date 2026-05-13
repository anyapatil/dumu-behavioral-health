"""FIX 1: delete Mercer University. FIX 2: replace all NPI-registered descriptions."""
import csv, os, time
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app import create_app
app = create_app()
from models import Company, db
import requests
from bs4 import BeautifulSoup
from scraper import HEADERS

sep = "─" * 65

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

# ── FIX 1 ─────────────────────────────────────────────────────────────────────
print(f"\n{sep}\nFIX 1 — Delete Mercer University\n{sep}")
with app.app_context():
    before = Company.query.count()
    deleted = []
    for co in Company.query.filter(Company.company_name.ilike("%mercer university%")).all():
        deleted.append(f"[{co.id}] {co.company_name}")
        db.session.delete(co)
    db.session.commit()
    after = Company.query.count()
    for d in deleted:
        print(f"  Deleted: {d}")
    print(f"  {len(deleted)} deleted — {before} → {after} remaining")

# ── FIX 2 ─────────────────────────────────────────────────────────────────────
print(f"\n{sep}\nFIX 2 — Replace NPI-registered descriptions\n{sep}")
with app.app_context():
    targets = Company.query.filter(
        Company.description.ilike("%NPI-registered%")
    ).order_by(Company.rank_score.desc()).all()
    ids = [(c.id, c.company_name, c.website_url, c.city, c.state) for c in targets]

print(f"  Found {len(ids)} companies with NPI-registered descriptions")
print(f"  With website: {sum(1 for _, _, w, _, _ in ids if w)}")

updated = 0
for i, (cid, name, url, city, state) in enumerate(ids, 1):
    new_desc = None

    if url:
        html = _fetch(url.rstrip("/"))
        new_desc = _meta_desc(html)
        time.sleep(1.5)

    if not new_desc:
        loc = f"{city}, {state}" if city and state else (city or state or "")
        new_desc = f"{name} is a geriatric behavioral health practice serving seniors in {loc}."

    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        co.description = new_desc
        db.session.commit()
        updated += 1
        src = "meta" if url and not new_desc.endswith(".") else "generated"
        print(f"  [{i:>3}/{len(ids)}] [{cid}] {name[:40]:<40} [{src}] {new_desc[:55]}…", flush=True)

print(f"\n  ✓ {updated} descriptions updated")

# ── CSV ────────────────────────────────────────────────────────────────────────
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
    print(f"  CSV → {csv_path} ({total} companies)")

    remaining_npi = Company.query.filter(Company.description.ilike("%NPI-registered%")).count()
    score70 = sum(1 for c in all_cos if (c.rank_score or 0) >= 70)
    print(f"\n{sep}\nFINAL STATE\n{sep}")
    print(f"  Total companies        : {total}")
    print(f"  NPI-registered remaining: {remaining_npi}")
    print(f"  Score 70+              : {score70}")
