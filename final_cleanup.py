"""Final junk cleanup before Flask launch."""
import csv, os, re
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app import create_app
app = create_app()
from models import Company, db

NAMED_DELETES = [
    "Indianapolis Nursing Home Abuse Lawyer",
    "Northwest Cardiology",
    "Alexian Brothers",
    "Anything is possible",
    "Harbor",
    "Advanced Psychiatric Services",
    "Eagleville Hospital",
]

NAME_PATTERNS = [
    r"\blawyer\b", r"\battorney\b", r"\blaw firm\b", r"\blegal\b",
    r"\bcardiology\b", r"\borthopedic\b", r"\bdental\b", r"\bpodiatry\b",
]

HOSPITAL_RE  = re.compile(r"\bhospital\b", re.IGNORECASE)
BH_RE        = re.compile(r"\bbehavioral\b|\bpsychiatric\b|\bpsych\b|\bmental health\b", re.IGNORECASE)

sep = "─" * 65
deleted = []

with app.app_context():
    before = Company.query.count()

    for co in Company.query.all():
        name = (co.company_name or "").strip()
        name_l = name.lower()
        reason = None

        # Named deletes (partial match)
        for nd in NAMED_DELETES:
            if nd.lower() in name_l:
                reason = f"named delete: {nd}"
                break

        # Pattern deletes
        if not reason:
            for p in NAME_PATTERNS:
                if re.search(p, name_l):
                    reason = f"name pattern: {p}"
                    break

        # Hospital without BH language
        if not reason and HOSPITAL_RE.search(name):
            if not BH_RE.search(name):
                reason = "hospital — no behavioral health signal in name"

        # Employee count > 200
        if not reason and co.employee_count_estimate:
            try:
                if int(co.employee_count_estimate) > 200:
                    reason = f"too large: {co.employee_count_estimate} employees"
            except ValueError:
                pass

        if reason:
            deleted.append((co.id, name, reason))
            db.session.delete(co)

    db.session.commit()
    after = Company.query.count()

    print(f"\n{sep}")
    print("FINAL CLEANUP")
    print(sep)
    print(f"  Before : {before}")
    print(f"  Deleted: {len(deleted)}")
    for cid, name, reason in deleted:
        print(f"    [{cid}] {name[:50]:<50} — {reason}")
    print(f"  After  : {after}")

    # Top 20
    top20 = (Company.query
             .filter(Company.acquirable == True)
             .order_by(Company.rank_score.desc())
             .limit(20).all())
    print(f"\n{'─'*65}")
    print("TOP 20 AFTER CLEANUP")
    print(f"{'─'*65}")
    print(f"{'#':<4} {'Score':<7} {'St':<4} {'Yr':<6} {'Emp':<6} Company")
    print(f"{'─'*4} {'─'*6} {'─'*3} {'─'*5} {'─'*5} {'─'*40}")
    for i, co in enumerate(top20, 1):
        flag = " [F]" if co.status == "flagged_for_review" else ""
        yr   = co.year_founded or "—"
        emp  = co.employee_count_estimate or "—"
        print(f"{i:<4} {co.rank_score:<7} {(co.state or '??'):<4} {yr:<6} {emp:<6} {co.company_name}{flag}")

    # Regenerate CSV
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "bh_companies.csv")
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
    print(f"\n  CSV → {csv_path} ({len(all_sorted)} companies)")
    print(f"{sep}")
    print(f"  FINAL CLEAN COUNT: {after} companies")
    print(sep)
