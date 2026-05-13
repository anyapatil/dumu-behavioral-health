"""Surgical pre-deployment cleanup + top-50 year/employee enrichment."""
import csv, os, re, time
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app import create_app
app = create_app()
from models import Company, db
import requests
from bs4 import BeautifulSoup
from scraper import HEADERS

sep = "─" * 65

# ── Step 1: Hard deletes ──────────────────────────────────────────────────────
NAMED_DELETES = [
    "Nursing Home Neglect Attorneys in Colorado Springs",
    "Nursing Home Geriatrics",
    "Portal",
    "We Don't See Patients, We See People",
    "compassionate mental health care",
    "Pauline K. Wiener, M.D., S.C.",
    "Page Moss Fletcher Md Pc",
    "Barbara Sparacino, M.D., P.A.",
]

# ── Step 2: Flag for review ───────────────────────────────────────────────────
NAMED_FLAGS = [
    "Life In Balance Healthcare & Wellness",
    "PersonalizedMemory Care",
    "Psych Recovery Inc",
]

print(f"\n{sep}\nSTEP 1 — Hard deletes\n{sep}")
with app.app_context():
    before = Company.query.count()
    deleted = []
    for name in NAMED_DELETES:
        cos = Company.query.filter(Company.company_name.ilike(f"%{name}%")).all()
        for co in cos:
            deleted.append(co.company_name)
            db.session.delete(co)
    db.session.commit()
    after = Company.query.count()
    for n in deleted:
        print(f"  Deleted: {n}")
    print(f"  {len(deleted)} deleted — {before} → {after} remaining")

print(f"\n{sep}\nSTEP 2 — Flag for review\n{sep}")
with app.app_context():
    flagged = []
    for name in NAMED_FLAGS:
        cos = Company.query.filter(Company.company_name.ilike(f"%{name}%")).all()
        for co in cos:
            co.status = "flagged_for_review"
            flagged.append(co.company_name)
    db.session.commit()
    for n in flagged:
        print(f"  Flagged: {n}")

# ── Step 3: Year/employee enrichment for top 50 missing these fields ──────────
YEAR_RE = re.compile(
    r"(?:founded|established|since|est\.?|incorporated|opened)\s+(?:in\s+)?(\d{4})",
    re.IGNORECASE,
)
COPY_YEAR_RE = re.compile(r"©\s*(\d{4})")
EMPLOYEE_RE  = re.compile(
    r"(?:team\s+of|over|more\s+than)?\s*(\d{1,3})\s*(?:\+)?\s*"
    r"(?:employees?|clinicians?|providers?|staff|practitioners?|therapists?|psychiatrists?|psychologists?)",
    re.IGNORECASE,
)

def _fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""

def _text(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())

def _year(text):
    for m in YEAR_RE.finditer(text):
        y = int(m.group(1))
        if 1950 <= y <= 2025:
            return str(y)
    for m in COPY_YEAR_RE.finditer(text):
        y = int(m.group(1))
        if 1950 <= y <= 2024:
            return str(y)
    return None

def _emp(text):
    best = None
    for m in EMPLOYEE_RE.finditer(text):
        n = int(m.group(1))
        if 1 <= n <= 200:
            if best is None or n > best:
                best = n
    return best

print(f"\n{sep}\nSTEP 3 — Year/employee enrichment for top 50\n{sep}")
with app.app_context():
    top50 = (
        Company.query
        .filter(Company.website_url != None, Company.website_url != "")
        .filter(
            (Company.year_founded == None) | (Company.year_founded == "") |
            (Company.employee_count_estimate == None) | (Company.employee_count_estimate == "")
        )
        .order_by(Company.rank_score.desc())
        .limit(50)
        .all()
    )
    ids = [(c.id, c.company_name, c.website_url, bool(c.year_founded), bool(c.employee_count_estimate))
           for c in top50]

print(f"  Top 50 missing year or employee data: {len(ids)}")

found_yr = 0
found_emp = 0
for cid, name, base_url, has_yr, has_emp in ids:
    base = (base_url or "").rstrip("/")
    combined = ""
    for path in ["/about", "/about-us", "/team", "/our-team", ""]:
        html = _fetch(base + path)
        if html:
            combined += " " + _text(html)
        time.sleep(0.5)

    yr  = _year(combined) if not has_yr else None
    emp = _emp(combined)  if not has_emp else None

    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        changed = False
        if yr and not co.year_founded:
            co.year_founded = yr
            found_yr += 1
            changed = True
        if emp is not None and not co.employee_count_estimate:
            co.employee_count_estimate = str(emp)
            found_emp += 1
            changed = True
        if changed:
            db.session.commit()
            yr_s  = f"est.{yr}" if yr else ""
            emp_s = f"{emp} staff" if emp is not None else ""
            print(f"  {name[:50]:<50} {yr_s} {emp_s}", flush=True)

print(f"\n  ✓ Found {found_yr} years, {found_emp} employee counts in top 50")

# ── Step 4: Regenerate CSV ────────────────────────────────────────────────────
print(f"\n{sep}\nSTEP 4 — Regenerate CSV\n{sep}")
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

    # Final stats
    has_yr  = sum(1 for c in all_cos if c.year_founded)
    has_emp = sum(1 for c in all_cos if c.employee_count_estimate)
    has_email = sum(1 for c in all_cos if c.email and "@" in (c.email or ""))
    score70 = sum(1 for c in all_cos if (c.rank_score or 0) >= 70)
    score80 = sum(1 for c in all_cos if (c.rank_score or 0) >= 80)

    print(f"  CSV → {csv_path}")
    print(f"\n{sep}")
    print(f"FINAL STATE")
    print(sep)
    print(f"  Total companies     : {total}")
    print(f"  Has email           : {has_email} ({has_email*100//total}%)")
    print(f"  Has year founded    : {has_yr} ({has_yr*100//total}%)")
    print(f"  Has employee est.   : {has_emp} ({has_emp*100//total}%)")
    print(f"  Score 70+           : {score70}")
    print(f"  Score 80+           : {score80}")

    print(f"\n{'─'*65}")
    print("TOP 10 BY RANK SCORE")
    print(f"{'─'*65}")
    print(f"{'#':<4} {'Score':<7} {'St':<4} {'Yr':<6} {'Emp':<5} {'Email':<6} Company")
    print(f"{'─'*4} {'─'*6} {'─'*3} {'─'*5} {'─'*4} {'─'*5} {'─'*40}")
    top10 = Company.query.order_by(Company.rank_score.desc()).limit(10).all()
    for i, co in enumerate(top10, 1):
        flag  = " [F]" if co.status == "flagged_for_review" else ""
        yr    = co.year_founded or "—"
        emp   = co.employee_count_estimate or "—"
        email = "✓" if co.email and "@" in (co.email or "") else "—"
        print(f"{i:<4} {co.rank_score:<7} {(co.state or '??'):<4} {yr:<6} {emp:<5} {email:<6} {co.company_name}{flag}")
    print(sep)
