"""
One-shot DB cleanup pass.
Step 1 — Hard delete junk records
Step 2 — Flag ambiguous records for review
Step 3 — Print stats
"""

import os, re, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app import create_app
app = create_app()

from models import Company, db

JUNK_NAME_PATTERNS = [
    r"sparky",
    r"policy pub",
    r"\bpub\b",
    r"\bbar\b",
    r"\brestaurant\b",
    r"memory care facilities$",      # directory listing pages
    r"mental health$",               # bare generic page title
    r"behavioral health$",
    r"\bpsychiatry$",
    r"visiting angels",
    r"comfort keepers",
    r"home instead",
    r"right at home",
    r"senior helpers",
    r"\bdirectory\b",
    r"\bresources\b",
    r"\bguide\b",
    r"\blist\b",
    r"\btop \d",                     # "Top 10 ..."
    r"\bbest \d",
    r" in [a-z]{2,}$",              # "Psychiatry in Texas"
    r"facilities in ",
    r"services in ",
    r"providers in ",
]

JUNK_URL_PATTERNS = [
    r"/blog/",
    r"/news/",
    r"/article/",
    r"/articles/",
    r"/press/",
    r"/post/",
]

FLAG_NAME_PATTERNS = [
    # City/state as primary identifier: "Chicago Behavioral Health", "Ohio Psychiatry"
    r"^(alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|"
    r"georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|"
    r"massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|"
    r"new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|"
    r"oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|"
    r"vermont|virginia|washington|west virginia|wisconsin|wyoming|"
    r"atlanta|dallas|houston|chicago|phoenix|philadelphia|san antonio|san diego|"
    r"jacksonville|austin|columbus|fort worth|charlotte|indianapolis|san francisco|"
    r"seattle|denver|nashville|oklahoma city|el paso|washington dc|boston|memphis|"
    r"louisville|portland|las vegas|milwaukee|albuquerque|tucson|fresno|sacramento|"
    r"mesa|kansas city|omaha|raleigh|miami|cleveland|minneapolis|wichita|arlington|"
    r"new orleans|bakersfield|tampa|aurora|anaheim|santa ana|corpus christi|riverside|"
    r"st. louis|lexington|pittsburgh|anchorage|stockton|cincinnati|st. paul|toledo|"
    r"greensboro|newark|plano|henderson|lincoln|buffalo|fort wayne|jersey city|"
    r"chula vista|orlando|st. petersburg|norfolk|chandler|laredo|madison|durham|lubbock|"
    r"winston.salem|garland|glendale|hialeah|reno|baton rouge|irvine|chesapeake|"
    r"scottsdale|north las vegas|fremont|gilbert|san bernardino|birmingham|rochester)\b",
]

FLAG_DESC_PATTERNS = [
    r"\bdirectory\b",
    r"\blisting\b",
    r"\bdirectory listing\b",
]

def matches_any(text, patterns):
    t = (text or "").lower().strip()
    return any(re.search(p, t, re.IGNORECASE) for p in patterns)

with app.app_context():
    all_cos = Company.query.all()
    total_before = len(all_cos)

    deleted = []
    flagged = []

    for co in all_cos:
        name = (co.company_name or "").strip()
        url  = (co.website_url or "").lower()
        desc = (co.description or "").lower()

        # Step 1a — name-based hard deletes
        if matches_any(name, JUNK_NAME_PATTERNS):
            deleted.append((co.id, name, "junk name pattern"))
            db.session.delete(co)
            continue

        # Step 1b — names > 60 chars are likely page titles
        if len(name) > 60:
            deleted.append((co.id, name, f"name too long ({len(name)} chars)"))
            db.session.delete(co)
            continue

        # Step 1c — names that are pure generic category words
        normalized = re.sub(r"[^a-z ]", "", name.lower()).strip()
        if normalized in {
            "mental health", "behavioral health", "psychiatry", "psychology",
            "geriatric psychiatry", "geropsychiatry", "senior care", "memory care",
            "home care", "elder care", "senior living",
        }:
            deleted.append((co.id, name, "pure generic name"))
            db.session.delete(co)
            continue

        # Step 2a — URL contains blog/news/article
        if matches_any(url, JUNK_URL_PATTERNS):
            if co.status != "flagged_for_review":
                co.status = "flagged_for_review"
                flagged.append((co.id, name, "blog/news/article URL"))
            continue

        # Step 2b — description mentions directory/listing
        if matches_any(desc, FLAG_DESC_PATTERNS):
            if co.status != "flagged_for_review":
                co.status = "flagged_for_review"
                flagged.append((co.id, name, "description mentions directory/listing"))
            continue

        # Step 2c — city/state as primary name identifier
        if matches_any(name, FLAG_NAME_PATTERNS):
            if co.status != "flagged_for_review":
                co.status = "flagged_for_review"
                flagged.append((co.id, name, "city/state primary identifier"))
            continue

    db.session.commit()

    # ── Stats ─────────────────────────────────────────────────────────────────
    remaining = Company.query.all()
    total_after = len(remaining)

    has_phone = sum(1 for c in remaining if c.phone and len(c.phone.strip()) >= 7)
    has_email = sum(1 for c in remaining if c.email and "@" in c.email)

    top20 = (
        Company.query
        .filter(Company.acquirable == True)
        .order_by(Company.rank_score.desc())
        .limit(20)
        .all()
    )

    sep = "─" * 70
    print(f"\n{sep}")
    print(f"CLEANUP COMPLETE")
    print(sep)
    print(f"  Before : {total_before}")
    print(f"  Deleted: {len(deleted)}")
    print(f"  Flagged: {len(flagged)}")
    print(f"  After  : {total_after}")
    print(f"  Phone  : {has_phone} companies with a phone number")
    print(f"  Email  : {has_email} companies with an email")
    print()

    if deleted:
        print("DELETED:")
        for cid, name, reason in deleted:
            print(f"  [{cid}] {name[:55]:<55} — {reason}")

    if flagged:
        print("\nNEWLY FLAGGED:")
        for cid, name, reason in flagged:
            print(f"  [{cid}] {name[:55]:<55} — {reason}")

    print(f"\n{sep}")
    print("TOP 20 BY RANK SCORE")
    print(sep)
    print(f"{'#':<4} {'Score':<7} {'State':<6} {'Company'}")
    print(f"{'─'*4} {'─'*6} {'─'*5} {'─'*50}")
    for i, co in enumerate(top20, 1):
        flag = " [FLAGGED]" if co.status == "flagged_for_review" else ""
        print(f"{i:<4} {co.rank_score:<7} {(co.state or '??'):<6} {co.company_name}{flag}")
    print(sep)
