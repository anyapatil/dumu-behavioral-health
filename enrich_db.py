"""
Multi-phase DB enrichment for Dumu BH acquisition targets.
Phases: website → email → year/employees → revenue → rescore → flag solos
Run: venv/bin/python -u enrich_db.py 2>&1 | tee outputs/enrich_run.log
"""

import csv
import os
import re
import sys
import time
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app import create_app
app = create_app()
from models import Company, db

# ── reuse scraper helpers ──────────────────────────────────────────────────────
import requests
from bs4 import BeautifulSoup
from scraper import HEADERS, SKIP_DOMAINS, SKIP_PATH_FRAGMENTS, SKIP_TLDS

# ── constants ─────────────────────────────────────────────────────────────────

ENRICH_SKIP_DOMAINS = SKIP_DOMAINS | {
    "npidb.org", "npino.com", "npi.io", "npiregistry.cms.hhs.gov",
    "cms.gov", "medicare.gov",
    "npiprofile.com", "nppes.com", "usnews.com", "sharecare.com",
    "ratemds.com", "wellness.com", "openmd.com", "doctor.com",
    "us.castleconnolly.com", "castleconnolly.com",
    "w3.health", "practo.com", "betterhelp.com", "talkspace.com",
}

ENRICH_TIMEOUT = 10
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

YEAR_RE = re.compile(
    r"(?:founded|established|since|est\.?|incorporated|opened)\s+(?:in\s+)?(\d{4})",
    re.IGNORECASE,
)
COPY_YEAR_RE = re.compile(r"©\s*(\d{4})")
EMPLOYEE_RE = re.compile(
    r"(?:team\s+of|over|more\s+than)?\s*(\d{1,4})\s*"
    r"(?:\+)?\s*(?:employees?|clinicians?|providers?|staff|practitioners?|therapists?|psychiatrists?|psychologists?)",
    re.IGNORECASE,
)

SNF_SIGNALS = [
    "nursing home", "skilled nursing", r"\bsnf\b", "long-term care",
    r"\bltc\b", "assisted living", r"\balf\b", "memory care facilit",
    "nursing facilit", "post-acute", "rehab facilit",
]

SOLO_CRED_RE = re.compile(
    r"\b(M\.?D\.?|D\.?O\.?|Ph\.?D\.?|Psy\.?D\.?|L\.?C\.?S\.?W\.?|"
    r"L\.?M\.?F\.?T\.?|L\.?P\.?C\.?|A\.?P\.?R\.?N\.?|N\.?P\.?|"
    r"M\.?S\.?W\.?|D\.?P\.?M\.?|D\.?C\.?)\s*[,.]?\s*(P\.?A\.?|P\.?L\.?L\.?C\.?|LLC|Inc\.?|P\.?C\.?)?\s*$",
    re.IGNORECASE,
)
SOLO_DR_RE   = re.compile(r"^dr\.?\s+", re.IGNORECASE)
SOLO_NAME_RE = re.compile(
    r"^[A-Z][a-z]+\s+(?:[A-Z]\.?\s+)?[A-Z][a-z']+,?\s+"
    r"(M\.?D\.?|D\.?O\.?|Ph\.?D\.?|Psy\.?D\.?|L\.?C\.?S\.?W\.?)",
    re.IGNORECASE,
)

sep = "─" * 70

def _domain(url):
    if not url:
        return ""
    url = re.sub(r"^https?://", "", url.lower())
    return url.split("/")[0].lstrip("www.")

def _is_skip(url):
    if not url:
        return True
    d = _domain(url)
    if any(skip in d for skip in ENRICH_SKIP_DOMAINS):
        return True
    if any(url.lower().endswith(t) for t in SKIP_TLDS):
        return True
    for frag in SKIP_PATH_FRAGMENTS:
        if frag in url.lower():
            return True
    return False

def _fetch(url, timeout=ENRICH_TIMEOUT):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout,
                         allow_redirects=True)
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

def _search_website(query):
    """Return first clean URL from DDG search, or None."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=10))
        for r in results:
            url = r.get("href") or r.get("url") or ""
            if not url:
                continue
            if _is_skip(url):
                continue
            # Reject deep paths (likely article/blog)
            path = url.split("//", 1)[-1].split("/", 1)[-1] if "//" in url else ""
            if path.count("/") > 1:
                continue
            return url
    except Exception:
        pass
    return None

def _extract_emails(html, base_domain=""):
    soup = BeautifulSoup(html or "", "html.parser")
    emails = []
    # 1. mailto links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            e = href[7:].split("?")[0].strip().lower()
            if e and "@" in e:
                emails.append(e)
    # 2. regex in text
    text = soup.get_text(" ")
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower().strip(".,;")
        if "@" in e and "." in e.split("@")[-1]:
            emails.append(e)

    # Filter: prefer domain-matching emails; drop noreply/info@ junk
    bad = {"noreply", "no-reply", "donotreply", "do-not-reply", "webmaster", "postmaster"}
    clean = []
    for e in emails:
        local = e.split("@")[0].lower()
        if local in bad:
            continue
        if base_domain and base_domain in e:
            clean.insert(0, e)  # domain match → prioritize
        else:
            clean.append(e)
    seen = []
    for e in clean:
        if e not in seen:
            seen.append(e)
    return seen

def _extract_year(text):
    for m in YEAR_RE.finditer(text):
        y = int(m.group(1))
        if 1950 <= y <= 2025:
            return str(y)
    # footer copyright fallback
    for m in COPY_YEAR_RE.finditer(text):
        y = int(m.group(1))
        if 1950 <= y <= 2025:
            return str(y)
    return None

def _extract_employees(text):
    best = None
    for m in EMPLOYEE_RE.finditer(text):
        n = int(m.group(1))
        if 1 <= n <= 2000:
            if best is None or n > best:
                best = n
    return best

def _revenue_from_employees(emp_str):
    if not emp_str:
        return "unknown"
    try:
        n = int(emp_str)
    except (ValueError, TypeError):
        return "unknown"
    if n <= 5:
        return "$500K-$1M"
    if n <= 15:
        return "$1M-$3M"
    if n <= 30:
        return "$3M-$8M"
    if n <= 50:
        return "$8M-$15M"
    return "$15M+"

def _snf_in_text(text):
    t = (text or "").lower()
    return any(re.search(p, t) for p in SNF_SIGNALS)

def _is_solo(name):
    n = (name or "").strip()
    if SOLO_DR_RE.match(n):
        return True
    if SOLO_CRED_RE.search(n):
        return True
    if SOLO_NAME_RE.match(n):
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# IMMEDIATE — Delete 4 named junk records
# ═══════════════════════════════════════════════════════════════════════════════

IMMEDIATE_DELETE = [
    "Sheridan Village",
    "Senior Connections",
    "Medicare Options Made Simple",
    "Elder Care Support",
]

print(f"\n{sep}")
print("IMMEDIATE DELETIONS")
print(sep)
with app.app_context():
    removed = 0
    for name in IMMEDIATE_DELETE:
        co = Company.query.filter(Company.company_name.ilike(f"%{name}%")).first()
        if co:
            print(f"  Deleted: [{co.id}] {co.company_name}")
            db.session.delete(co)
            removed += 1
        else:
            print(f"  Not found: {name}")
    db.session.commit()
    total = Company.query.count()
print(f"  {removed} deleted — {total} remaining\n")

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — Find websites for companies missing them
# ═══════════════════════════════════════════════════════════════════════════════

print(f"{sep}")
print("PHASE 1 — Find missing websites")
print(sep)

with app.app_context():
    no_site = Company.query.filter(
        (Company.website_url == None) | (Company.website_url == "")
    ).order_by(Company.id).all()
    ids_no_site = [c.id for c in no_site]

print(f"  Companies without website: {len(ids_no_site)}")

found_sites = 0
for i, cid in enumerate(ids_no_site, 1):
    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        name  = co.company_name or ""
        city  = co.city or ""
        state = co.state or ""

    query = f'"{name}" {city} {state} behavioral health psychiatry'
    url = _search_website(query)

    if not url:
        # Retry with simpler query
        query2 = f"{name} {state} mental health practice"
        url = _search_website(query2)

    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        if url:
            co.website_url = url
            db.session.commit()
            found_sites += 1
            print(f"  [{i}/{len(ids_no_site)}] {name[:45]:<45} → {url[:50]}")
        else:
            print(f"  [{i}/{len(ids_no_site)}] {name[:45]:<45} → (not found)")

    time.sleep(2)

print(f"\n  ✓ Phase 1 complete — {found_sites}/{len(ids_no_site)} websites found\n")

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Scrape websites for email
# ═══════════════════════════════════════════════════════════════════════════════

print(f"{sep}")
print("PHASE 2 — Find emails from websites")
print(sep)

with app.app_context():
    need_email = Company.query.filter(
        (Company.email == None) | (Company.email == ""),
        Company.website_url != None,
        Company.website_url != "",
    ).order_by(Company.id).all()
    ids_need_email = [c.id for c in need_email]

print(f"  Companies with website but no email: {len(ids_need_email)}")

found_emails = 0
for i, cid in enumerate(ids_need_email, 1):
    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        base = co.website_url.rstrip("/")
        base_domain = _domain(base)
        name = co.company_name or ""

    email = None
    for path in ["", "/contact", "/contact-us", "/about", "/about-us"]:
        html = _fetch(base + path)
        if not html:
            continue
        candidates = _extract_emails(html, base_domain)
        if candidates:
            email = candidates[0]
            break
        time.sleep(0.5)

    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        if email:
            co.email = email.lower()
            db.session.commit()
            found_emails += 1
            print(f"  [{i}/{len(ids_need_email)}] {name[:40]:<40} → {email}")
        else:
            if i % 20 == 0:
                print(f"  [{i}/{len(ids_need_email)}] (batch — no emails found this group)")

    time.sleep(1)

print(f"\n  ✓ Phase 2 complete — {found_emails}/{len(ids_need_email)} emails found\n")

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Enrich year_founded and employee_count_estimate
# ═══════════════════════════════════════════════════════════════════════════════

print(f"{sep}")
print("PHASE 3 — Find year founded and employee count")
print(sep)

with app.app_context():
    has_site = Company.query.filter(
        Company.website_url != None,
        Company.website_url != "",
    ).order_by(Company.id).all()
    ids_site = [c.id for c in has_site]

print(f"  Companies with website to enrich: {len(ids_site)}")

found_year = 0
found_emp  = 0
for i, cid in enumerate(ids_site, 1):
    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        base       = (co.website_url or "").rstrip("/")
        name       = co.company_name or ""
        already_yr = bool(co.year_founded)
        already_emp = bool(co.employee_count_estimate)

    if already_yr and already_emp:
        continue

    combined = ""
    for path in ["/about", "/about-us", "/team", "/our-team", "/leadership", ""]:
        html = _fetch(base + path)
        if html:
            combined += " " + _text(html)
        time.sleep(0.3)

    year = _extract_year(combined) if not already_yr else None
    emp  = _extract_employees(combined) if not already_emp else None

    with app.app_context():
        co = Company.query.get(cid)
        if not co:
            continue
        changed = False
        if year and not co.year_founded:
            co.year_founded = year
            found_year += 1
            changed = True
        if emp is not None and not co.employee_count_estimate:
            co.employee_count_estimate = str(emp)
            found_emp += 1
            changed = True
        if changed:
            db.session.commit()
            yr_str  = f"est. {year}" if year else ""
            emp_str = f"{emp} staff" if emp is not None else ""
            print(f"  [{i}] {name[:45]:<45} {yr_str} {emp_str}")

    if i % 10 == 0:
        print(f"  ... {i}/{len(ids_site)} processed", flush=True)

print(f"\n  ✓ Phase 3 complete — {found_year} years, {found_emp} employee counts found\n")

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — Estimate revenue from employee count
# ═══════════════════════════════════════════════════════════════════════════════

print(f"{sep}")
print("PHASE 4 — Estimate revenue from employee count")
print(sep)

with app.app_context():
    all_cos = Company.query.all()
    updated = 0
    for co in all_cos:
        rev = _revenue_from_employees(co.employee_count_estimate)
        if rev != (co.revenue_estimate or "unknown"):
            co.revenue_estimate = rev
            updated += 1
    db.session.commit()

print(f"  ✓ Revenue estimate updated for {updated} companies\n")

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — Re-score with new signals
# ═══════════════════════════════════════════════════════════════════════════════

print(f"{sep}")
print("PHASE 5 — Re-score with enriched signals")
print(sep)

with app.app_context():
    all_cos = Company.query.all()
    rescored = 0
    for co in all_cos:
        bonus = 0
        new_signals = []

        # +15 if description/signals contain SNF delivery language
        full_text = " ".join(filter(None, [co.description, co.positive_signals]))
        if _snf_in_text(full_text):
            bonus += 15
            new_signals.append("snf-delivery-confirmed")

        # +10 if email found
        if co.email and "@" in co.email:
            bonus += 10
            new_signals.append("email-found")

        # +10 if year_founded before 2020 (established practice)
        if co.year_founded:
            try:
                if int(co.year_founded) < 2020:
                    bonus += 10
                    new_signals.append(f"established-{co.year_founded}")
            except ValueError:
                pass

        # +8 if employee count 10+
        if co.employee_count_estimate:
            try:
                if int(co.employee_count_estimate) >= 10:
                    bonus += 8
                    new_signals.append(f"team-{co.employee_count_estimate}")
            except ValueError:
                pass

        # +5 if address starts with a number (real street address)
        if co.address and re.match(r"^\d+", co.address.strip()):
            bonus += 5
            new_signals.append("street-address-confirmed")

        if bonus > 0:
            old_score = co.rank_score or 0
            co.rank_score = min(100, old_score + bonus)
            # Merge new signals
            existing = co.positive_signals or ""
            additions = [s for s in new_signals if s not in existing]
            if additions:
                co.positive_signals = (existing + "; " + "; ".join(additions)).strip("; ")
            rescored += 1

    db.session.commit()

print(f"  ✓ Re-scored {rescored} companies with enrichment bonuses\n")

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 6 — Flag solo practitioners
# ═══════════════════════════════════════════════════════════════════════════════

print(f"{sep}")
print("PHASE 6 — Flag solo practitioners")
print(sep)

SOLO_NOTE = "Solo practitioner — verify if group practice before outreach"

with app.app_context():
    all_cos = Company.query.all()
    flagged_solo = 0
    for co in all_cos:
        if _is_solo(co.company_name):
            if co.status != "flagged_for_review":
                co.status = "flagged_for_review"
            existing_notes = co.notes or ""
            if SOLO_NOTE not in existing_notes:
                co.notes = (existing_notes + "\n" + SOLO_NOTE).strip()
            flagged_solo += 1
    db.session.commit()

print(f"  ✓ Flagged {flagged_solo} solo practitioners for review\n")

# ═══════════════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

print(f"{sep}")
print("ENRICHMENT COMPLETE — FINAL SUMMARY")
print(sep)

with app.app_context():
    all_cos      = Company.query.all()
    total        = len(all_cos)
    has_website  = sum(1 for c in all_cos if c.website_url)
    has_email    = sum(1 for c in all_cos if c.email and "@" in c.email)
    has_phone    = sum(1 for c in all_cos if c.phone and len((c.phone or "").strip()) >= 7)
    has_year     = sum(1 for c in all_cos if c.year_founded)
    has_emp      = sum(1 for c in all_cos if c.employee_count_estimate)
    has_revenue  = sum(1 for c in all_cos if c.revenue_estimate and c.revenue_estimate != "unknown")
    score_70     = sum(1 for c in all_cos if (c.rank_score or 0) >= 70)
    score_80     = sum(1 for c in all_cos if (c.rank_score or 0) >= 80)
    solo_flagged = sum(1 for c in all_cos if c.notes and SOLO_NOTE in c.notes)
    flagged_tot  = sum(1 for c in all_cos if c.status == "flagged_for_review")

    print(f"  Total companies     : {total}")
    print(f"  Has website         : {has_website} ({has_website*100//total}%)")
    print(f"  Has email           : {has_email} ({has_email*100//total}%)")
    print(f"  Has phone           : {has_phone} ({has_phone*100//total}%)")
    print(f"  Has year founded    : {has_year} ({has_year*100//total}%)")
    print(f"  Has employee est.   : {has_emp} ({has_emp*100//total}%)")
    print(f"  Has revenue est.    : {has_revenue} ({has_revenue*100//total}%)")
    print(f"  Score 70+           : {score_70}")
    print(f"  Score 80+           : {score_80}")
    print(f"  Solo flagged        : {solo_flagged}")
    print(f"  Total flagged       : {flagged_tot}")
    print()

    # Top 20
    top20 = (
        Company.query
        .filter(Company.acquirable == True)
        .order_by(Company.rank_score.desc())
        .limit(20)
        .all()
    )
    print(f"  {'#':<4} {'Score':<7} {'St':<4} {'Website':<5} {'Email':<6} Company")
    print(f"  {'─'*4} {'─'*6} {'─'*3} {'─'*4} {'─'*5} {'─'*45}")
    for i, co in enumerate(top20, 1):
        flag  = " [F]" if co.status == "flagged_for_review" else ""
        web   = "✓" if co.website_url else "—"
        email = "✓" if co.email else "—"
        print(f"  {i:<4} {co.rank_score:<7} {(co.state or '??'):<4} {web:<5} {email:<6} {co.company_name}{flag}")

    # ── Export CSV ─────────────────────────────────────────────────────────────
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "bh_companies.csv")
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    fieldnames = [
        "company_name", "company_type", "delivery_setting", "address", "city",
        "state", "zip", "phone", "email", "website_url", "description",
        "year_founded", "employee_count_estimate", "revenue_estimate",
        "funding_status", "rank_score", "positive_signals",
        "exclude_flags", "status", "verified", "notes",
    ]
    all_sorted = Company.query.order_by(Company.rank_score.desc()).all()
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for co in all_sorted:
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

print(f"\n  CSV exported → {csv_path}")
print(f"{sep}")
print(f"Done. Flask app: http://localhost:5100")
print(sep)
