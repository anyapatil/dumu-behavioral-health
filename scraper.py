"""
Discovery engine for Dumu Holdings — Behavioral Health Acquisition Targets.
Diana's complete keyword spec.

Include: ALL THREE categories must match (clinical × senior × setting).
Exclude: hard-disqualify, soft-flag, named competitors.
"""

import logging
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── INCLUDE keyword sets ──────────────────────────────────────────────────────

CLINICAL_TERMS = [
    r"\bpsychiatry\b",
    r"\bpsychiatric services\b",
    r"\bpsychiatric care\b",
    r"\bpsychological services\b",
    r"\bpsychological care\b",
    r"\bneuropsychology\b",
    r"\bneuropsychological testing\b",
    r"\bbehavioral health\b",
    r"\bmental health services\b",
    r"\bgeriatric psychiatry\b",
    r"\bgeriatric mental health\b",
    r"\bgeropsychology\b",
    r"\bgeropsychiatric\b",
    r"\bdementia care\b",
    r"\bcognitive assessment\b",
    r"\bpsychotherapy\b",
    r"\bcounseling services\b",
    r"\bmedication management\b",
    r"\bpsychotropic management\b",
    r"\bgradual dose reduction\b",
    r"\bgdr\b",
]

SENIOR_TERMS = [
    r"\bgeriatric\b",
    r"\belderly\b",
    r"\bseniors\b",
    r"\bolder adults\b",
    r"\baging\b",
    r"\baging population\b",
    r"\blate.life\b",
    r"\bend.of.life\b",
]

SETTING_TERMS = [
    r"\bskilled nursing facility\b",
    r"\bsnf\b",
    r"\bnursing home\b",
    r"\blong.term care\b",
    r"\bltc\b",
    r"\bpost.acute\b",
    r"\bassisted living\b",
    r"\balf\b",
    r"\bmemory care\b",
    r"\bsenior living\b",
    r"\bsenior community\b",
    r"\bretirement community\b",
    r"\bccrc\b",
    r"\bon.site\b",
    r"\bfacility.embedded\b",
    r"\bmobile\b",
    r"\bin.facility\b",
    r"\bhouse calls\b",
    r"\bhome visits\b",
    r"\bin.home\b",
]

# ── EXCLUDE — hard disqualify ─────────────────────────────────────────────────

HARD_EXCLUDE = [
    r"\bchildren\b",
    r"\bpediatric\b",
    r"\badolescent\b",
    r"\bteen\b",
    r"\byouth\b",
    r"\bschool.based\b",
    r"\bchild psychiatry\b",
    r"\badhd\b",
    r"\bautism\b",
    r"\bcollege\b",
    r"\buniversity counseling\b",
    r"\bperinatal\b",
    r"\bpostpartum\b",
    r"\baddiction recovery\b",
    r"\bsud\b",
    r"\brehab center\b",
    r"\bdetox\b",
    r"\binpatient psychiatric hospital\b",
    r"\bbehavioral health hospital\b",
    r"\bpsychiatric bed\b",
    r"\breal estate\b",
    r"\breit\b",
    r"\bresidential treatment\b",
    r"\btreatment center\b",
    r"\bsaas\b",
    r"\bapp.based therapy\b",
    r"\btelehealth platform\b",
    r"\bvirtual.first\b",
    r"\bdigital therapeutic\b",
    r"\bai.powered\b",
    r"\bemployee assistance program\b",
    r"\beap\b",
    r"\bworkplace wellness\b",
    r"\bprimary care clinic\b",
    r"\burgent care\b",
    r"\bemergency department\b",
    r"\bhospital system\b",
    r"\bhealth system\b",
    r"\bfqhc\b",
    r"\bcmhc\b",
    r"\bseries [abcd]\b",
    r"\braised funding\b",
    r"\bventure.backed\b",
    r"\bvc.backed\b",
    r"\bprivate equity portfolio\b",
    r"\bacquired by\b",
    r"\bsubsidiary of\b",
    r"\bdivision of\b",
]

# ── EXCLUDE — soft flag (insert with flagged_for_review status) ───────────────

SOFT_FLAG = [
    r"\bsubstance use disorder\b",
    r"\baddiction\b",
    r"\bmulti.specialty mobile\b",
    r"\bpodiatry\b",
    r"\bdental\b",
    r"\btelehealth supplement\b",
    r"\bvirtual option\b",
]

# ── EXCLUDE — named competitors (skip entirely) ───────────────────────────────

NAMED_COMPETITORS = [
    "acadia healthcare",
    "optum",
    "landmark health",
    "carelon",
    "bluestone physician services",
    "vitalic health",
    "deer oaks",
    "senior psychcare",
    "spc health",
    "comprehensive mobile care",
    "bluestone",
    "md2u",
    # National home-care franchises — not acquisition targets
    "visiting angels",
    "comfort keepers",
    "home instead",
    "right at home",
    "senior helpers",
    "brightspring",
    "enhabit",
    "amedisys",
    "lhc group",
    "kindred at home",
]

# ── EXCLUDE — franchise/national chain signals in page text ──────────────────

FRANCHISE_EXCLUDE = [
    r"\bfranchise\b",
    r"\bfranchisee\b",
    r"locations nationwide",
    r"500\+\s*locations",
    r"1[,.]?000\+\s*locations",
    r"nationwide network of",
    r"our franchise",
]

# ── Skip domains ──────────────────────────────────────────────────────────────

SKIP_DOMAINS = {
    # Job / staffing / recruiting
    "indeed.com", "glassdoor.com", "ziprecruiter.com", "monster.com",
    "hospitalrecruiting.com", "doccafe.com", "practicematch.com",
    "physicianandpractice.com", "merritt hawkins.com",
    # Directories & finders
    "healthgrades.com", "psychologytoday.com", "zocdoc.com",
    "vitals.com", "doximity.com", "npino.com", "npi.io",
    "bbb.org", "yellowpages.com", "yelp.com",
    "seniorly.com", "caring.com", "aplaceformom.com",
    "findatopdoc.com", "wellness.com",
    # Social / professional networks
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
    # News / media / trade press
    "mcknightsseniorliving.com", "mcknights.com", "seniorhousingnews.com",
    "hcinnovationgroup.com", "hfma.org", "modernhealthcare.com",
    "behavioral.net", "behavioral.org", "bisnow.com",
    "businesswire.com", "prnewswire.com", "globenewswire.com",
    # General reference
    "wikipedia.org", "webmd.com", "healthline.com", "medicalnewstoday.com",
    "merriam-webster.com", "mayoclinic.org", "medlineplus.gov",
    "news-medical.net",
    # Misc skip
    "seakexperts.com", "foryourrights.com",
    "kinderinthekeys.com", "seniorlivingbehavioralhealth.com",
}

# Path fragments that indicate blog/news/directory content — not a company homepage
SKIP_PATH_FRAGMENTS = {
    "/blog/", "/news/", "/press/", "/press-room/", "/columns/",
    "/resources/", "/articles/", "/jobs/", "/job/", "/careers/",
    "/about/geriatric", "/post/", "/insights/", "/events/",
    "/publications/", "/research/", "/white-paper/",
    "/marketplace-", "/webinar/",
}

SKIP_TLDS = {".gov", ".edu"}

# ── Subpages to scrape ────────────────────────────────────────────────────────

SUBPAGES = [
    "/about", "/about-us", "/services", "/team", "/contact",
    "/facilities", "/our-facilities", "/locations", "/our-work", "/who-we-serve",
    "/leadership", "/partner-communities",
]

# ── Ranking — positive boosts ─────────────────────────────────────────────────

POSITIVE_BOOSTS = [
    (10, [r"founder.led", r"founder.owned", r"physician.owned"]),
    (10, [r"family.owned"]),
    (10, [r"since 19\d\d", r"since 200\d"]),
    (10, [r"serving .{0,40}for over \d+ years"]),
    (8,  [r"we partner with skilled nursing"]),
    (8,  [r"weekly visits", r"weekly rounds"]),
    (8,  [r"medicare.certified", r"medicare part b"]),
    (8,  [r"contracted services", r"partner facilities"]),
    (5,  [r"multi.state", r"regional"]),
    (5,  [r"team of psychiatrists and nurse practitioners"]),
    (5,  [r"guide model", r"guide program"]),
    (5,  [r"\bf.tag\b", r"f.tag compliance"]),
]

RISK_DEDUCTIONS = [
    (-10, [r"telehealth"]),
    (-10, [r"fewer than 5 employees", r"under 5 employees", r"\b[1-4] employees\b"]),
    (-15, [r"\bvc\b", r"\bventure\b", r"private equity", r"pe.backed"]),
]

# ── Search queries ────────────────────────────────────────────────────────────
# Plain-language queries that match how small practices actually describe themselves.

SEARCH_QUERIES = [
    '{state_name} psychiatrist nursing home visits',
    '{state_name} psychologist senior living services',
    '{state_name} behavioral health nursing facility contracted',
    '{state_name} geriatric mental health services',
    '{state_name} psychiatric services assisted living',
    '{state_name} mobile psychiatry elderly care',
    '{state_name} mental health senior care facility',
    '{state_name} psychology group practice nursing home',
    '{state_name} psychiatrist SNF contracted services',
    '{state_name} behavioral health memory care',
]

PRIORITY_STATES = ["TX", "FL", "GA", "NC", "SC", "PA", "OH", "MI", "IL", "TN", "AZ", "VA", "CO", "MN", "IN"]

STATE_NAMES = {
    "TX": "Texas", "FL": "Florida", "GA": "Georgia", "NC": "North Carolina",
    "SC": "South Carolina", "PA": "Pennsylvania", "OH": "Ohio", "MI": "Michigan",
    "IL": "Illinois", "TN": "Tennessee", "AZ": "Arizona", "VA": "Virginia",
    "CO": "Colorado", "MN": "Minnesota", "IN": "Indiana",
}

# ── HTTP helpers ──────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch(url, timeout=12):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout,
                         allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        logger.debug("Fetch error %s: %s", url, e)
    return ""


def _text_from_html(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).lower().split())


def _extract_contact(html):
    phone = email = None
    if not html:
        return phone, email
    phone_m = re.search(r'(\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})', html)
    if phone_m:
        phone = phone_m.group(1)
    email_m = re.search(
        r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', html)
    if email_m:
        cand = email_m.group(0).lower()
        if not any(x in cand for x in ["example.", "test@", "noreply", "no-reply"]):
            email = cand
    return phone, email


def _extract_address(html):
    """Try to pull city/state/zip from structured address markup."""
    soup = BeautifulSoup(html or "", "html.parser")
    city = state = zip_ = address = None

    itemprop_city  = soup.find(attrs={"itemprop": "addressLocality"})
    itemprop_state = soup.find(attrs={"itemprop": "addressRegion"})
    itemprop_zip   = soup.find(attrs={"itemprop": "postalCode"})
    itemprop_addr  = soup.find(attrs={"itemprop": "streetAddress"})

    if itemprop_city:  city    = itemprop_city.get_text(strip=True)
    if itemprop_state: state   = itemprop_state.get_text(strip=True)
    if itemprop_zip:   zip_    = itemprop_zip.get_text(strip=True)
    if itemprop_addr:  address = itemprop_addr.get_text(strip=True)

    # Fallback: regex for "City, ST 00000"
    if not city:
        m = re.search(r'([A-Z][a-z]+(?: [A-Z][a-z]+)*),\s+([A-Z]{2})\s+(\d{5})', html or "")
        if m:
            city, state, zip_ = m.group(1), m.group(2), m.group(3)

    return address, city, state, zip_


def _extract_description(html):
    soup = BeautifulSoup(html or "", "html.parser")
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        d = meta["content"].strip()
        if 20 < len(d) < 400:
            return d
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        d = og["content"].strip()
        if 20 < len(d) < 400:
            return d
    for tag in soup.find_all(["p"]):
        t = tag.get_text(strip=True)
        if 50 < len(t) < 350:
            return t
    return ""


def _extract_name(html, url):
    """Try to get real company name from page title or h1."""
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if 3 < len(t) < 80 and not any(c.isdigit() for c in t[:3]):
            return t
    title_tag = soup.find("title")
    if title_tag:
        t = title_tag.get_text(strip=True)
        for sep in ["|", " - ", " – ", " — ", ":"]:
            parts = t.split(sep)
            name = parts[0].strip()
            if 3 < len(name) < 80:
                return name
    domain = _base_domain(url)
    return domain.split(".")[0].replace("-", " ").replace("_", " ").title()


def _base_domain(url):
    try:
        parsed = urlparse(url if url.startswith("http") else "https://" + url)
        host = parsed.netloc or parsed.path
        return host.replace("www.", "").lower()
    except Exception:
        return ""


# ── Keyword matching ──────────────────────────────────────────────────────────

def _matches_any(text, patterns):
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False


def _find_matches(text, patterns):
    found = []
    for pat in patterns:
        if re.search(pat, text):
            found.append(pat.replace(r"\b", "").replace("\\", "").strip("."))
    return found


def _qualifies(text_full, text_core=None):
    """
    Returns (qualifies: bool, flag_review: bool, signals: list, excl_flags: list).

    text_core  — homepage + /about only: used for hard-exclude check.
                 If None, falls back to text_full (backward-compat).
    text_full  — all scraped pages: used for include keyword check.
    """
    if text_core is None:
        text_core = text_full

    # Named competitor — check both texts
    combined = text_core + " " + text_full
    for comp in NAMED_COMPETITORS:
        if comp in combined:
            return False, False, [], [f"competitor: {comp}"]

    # Hard exclude — only applied to core text (homepage + /about)
    # so a /services page listing ADHD for adult patients doesn't kill a geriatric practice
    hard_hits = _find_matches(text_core, HARD_EXCLUDE)
    if hard_hits:
        return False, False, [], hard_hits

    # Franchise/national chain signals — applied to full text
    franchise_hits = _find_matches(text_full, FRANCHISE_EXCLUDE)
    if franchise_hits:
        return False, False, [], franchise_hits

    # Include check — use full site text
    clinical_hits = _find_matches(text_full, CLINICAL_TERMS)
    senior_hits   = _find_matches(text_full, SENIOR_TERMS)
    setting_hits  = _find_matches(text_full, SETTING_TERMS)

    if not (clinical_hits and senior_hits and setting_hits):
        return False, False, [], []

    # Soft flags — check full text
    soft_hits = _find_matches(text_full, SOFT_FLAG)
    if soft_hits:
        return True, True, clinical_hits + senior_hits + setting_hits, soft_hits

    return True, False, clinical_hits + senior_hits + setting_hits, []


# ── Ranking ───────────────────────────────────────────────────────────────────

def _score(text):
    score = 50
    positives = []
    for pts, patterns in POSITIVE_BOOSTS:
        for pat in patterns:
            if re.search(pat, text):
                score += pts
                positives.append(pat.replace(r"\b", "").replace("\\", "").strip("."))
                break
    for pts, patterns in RISK_DEDUCTIONS:
        for pat in patterns:
            if re.search(pat, text):
                score += pts
                break
    return max(1, min(100, score)), positives


# ── Classify ──────────────────────────────────────────────────────────────────

def _classify_type(text):
    if re.search(r"\bneuropsycholog", text):
        return "neuropsychology"
    if re.search(r"\bpsychiatr", text):
        return "psychiatry"
    if re.search(r"\bpsycholog", text):
        return "psychology"
    if re.search(r"\bbehavioral health\b", text):
        return "behavioral_health"
    return "combined"


def _classify_setting(text):
    settings = []
    if re.search(r"snf|skilled nursing|nursing home|long.term care|post.acute", text):
        settings.append("snf")
    if re.search(r"assisted living|alf", text):
        settings.append("alf")
    if re.search(r"memory care", text):
        settings.append("memory_care")
    if re.search(r"in.home|house calls|home visits", text):
        settings.append("in_home")
    if len(settings) > 1:
        return "multi_setting"
    return settings[0] if settings else "multi_setting"


# ── Website scraper ───────────────────────────────────────────────────────────

def scrape_company_website(url):
    """
    Scrape homepage + subpages.

    Returns a dict with:
      text_core  — homepage + /about text only  (used for hard-exclude check)
      text_full  — all pages                    (used for include keyword check)
      ...contact fields...
    """
    base = url if url.startswith("http") else "https://" + url

    # Always fetch homepage first
    homepage_html = _fetch(base)
    core_text = _text_from_html(homepage_html) + " "
    full_text = core_text

    # Fetch /about-us separately (also counts as "core")
    about_html = _fetch(urljoin(base, "/about")) or _fetch(urljoin(base, "/about-us"))
    if about_html:
        about_text = _text_from_html(about_html)
        core_text += about_text + " "
        full_text  += about_text + " "

    all_html = homepage_html + (about_html or "")

    # Remaining subpages — add to full_text only (NOT core_text)
    remaining = [s for s in SUBPAGES if s not in ("/about", "/about-us")]
    for sub in remaining:
        sub_html = _fetch(urljoin(base, sub))
        if sub_html:
            all_html += sub_html
            full_text += _text_from_html(sub_html) + " "
        time.sleep(0.4)

    phone, email         = _extract_contact(all_html)
    address, city, state, zip_ = _extract_address(all_html)
    description          = _extract_description(homepage_html)
    company_name         = _extract_name(homepage_html, url)

    return {
        "text_core":    core_text,   # homepage + about only — for hard-excludes
        "text_full":    full_text,   # all pages — for include check
        "html":         homepage_html,
        "company_name": company_name,
        "phone":        phone,
        "email":        email,
        "address":      address,
        "city":         city,
        "state_found":  state,
        "zip":          zip_,
        "description":  description,
    }


# ── Main discovery function ───────────────────────────────────────────────────

def discover_companies_by_state(state_abbr, company_type_filter, flask_app,
                                 progress_cb=None):
    """
    Run all queries for one state, scrape qualifying URLs, insert into DB.
    progress_cb(msg: str) is called for each progress line.
    Returns list of dicts with new company info.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        msg = "ERROR: ddgs not installed. Run: pip install ddgs"
        if progress_cb:
            progress_cb(msg)
        logger.error(msg)
        return []

    state_name = STATE_NAMES.get(state_abbr, state_abbr)
    new_companies = []

    with flask_app.app_context():
        from models import Company, db

        seen_domains = {
            _base_domain(u) for (u,) in
            db.session.query(Company.website_url)
            .filter(Company.website_url.isnot(None)).all()
            if u
        }

        for q_idx, query_tpl in enumerate(SEARCH_QUERIES, 1):
            query = query_tpl.replace("{state_name}", state_name)
            before_count = len(new_companies)

            try:
                with DDGS() as ddgs:
                    raw = list(ddgs.text(query, max_results=12))
                urls = [r["href"] for r in raw if r.get("href")]
            except Exception as e:
                msg = f"  Search error [{query[:50]}]: {e}"
                if progress_cb:
                    progress_cb(msg)
                logger.warning(msg)
                time.sleep(10)
                continue

            for url in urls:
                domain = _base_domain(url)
                if not domain:
                    continue
                if any(skip in domain for skip in SKIP_DOMAINS):
                    continue
                if any(url.find(tld) >= 0 for tld in SKIP_TLDS):
                    continue
                # Skip deep-path content pages (blogs, news, job posts, facility subpages)
                url_lower = url.lower()
                if any(frag in url_lower for frag in SKIP_PATH_FRAGMENTS):
                    continue
                # Skip URLs deeper than 2 path segments (e.g. /community/memory-care/behavioral-health)
                try:
                    path = urlparse(url).path.strip("/")
                    if path.count("/") > 1:
                        continue
                except Exception:
                    pass
                if domain in seen_domains:
                    continue

                seen_domains.add(domain)
                time.sleep(2)

                try:
                    data = scrape_company_website(url)
                except Exception as e:
                    logger.debug("Scrape error %s: %s", url, e)
                    continue

                qualifies, flag_review, signals, excl = _qualifies(data["text_full"], data["text_core"])

                if not qualifies:
                    continue

                rank, positive_phrases = _score(data["text_full"])
                ctype   = company_type_filter or _classify_type(data["text_full"])
                setting = _classify_setting(data["text_full"])
                status  = "flagged_for_review" if flag_review else "uncontacted"

                # Skip pages that look like articles/directories, not company homepages
                extracted_name = data["company_name"]
                junk_prefixes = (
                    "the ", "top ", "best ", "how ", "what ", "why ", "when ",
                    "understanding ", "exploring ", "a guide ", "resources ",
                    "mental health resources", "technology-enabled",
                )
                if any(extracted_name.lower().startswith(pfx) for pfx in junk_prefixes):
                    continue
                if len(extracted_name.split()) > 8:
                    continue  # Too many words = article title

                # State override: use the searched state
                final_state = state_abbr

                company = Company(
                    company_name     = data["company_name"][:255],
                    website_url      = url,
                    phone            = data.get("phone"),
                    email            = data.get("email"),
                    address          = data.get("address"),
                    city             = data.get("city"),
                    state            = final_state,
                    zip              = data.get("zip"),
                    description      = (data.get("description") or "")[:500] or None,
                    company_type     = ctype,
                    delivery_setting = setting,
                    funding_status   = "unknown",
                    acquirable       = True,
                    rank_score       = rank,
                    status           = status,
                    verified         = False,
                    positive_signals = "; ".join(positive_phrases) if positive_phrases else None,
                    exclude_flags    = "; ".join(excl) if excl else None,
                    last_scraped     = datetime.utcnow(),
                    last_updated     = datetime.utcnow(),
                )
                db.session.add(company)
                new_companies.append({
                    "name":    data["company_name"],
                    "state":   final_state,
                    "score":   rank,
                    "flagged": flag_review,
                    "url":     url,
                })
                logger.info("  + %s (%s, score=%d%s)",
                            data["company_name"], final_state, rank,
                            " FLAGGED" if flag_review else "")

            db.session.commit()

            added = len(new_companies) - before_count
            total_so_far = len(new_companies)
            msg = f"{state_abbr} Query {q_idx}/{len(SEARCH_QUERIES)} | +{added} new companies | Running total: {total_so_far}"
            if progress_cb:
                progress_cb(msg)

            time.sleep(2)

        time.sleep(5)

    return new_companies


NPI_TAXONOMIES = ["Geriatric Psychiatry", "Geropsychiatry"]


def discover_from_npi_by_state(state_abbr, flask_app, progress_cb=None):
    """
    Pull type-2 (organization) NPIs for geriatric psychiatry in a state.
    For each org, DDGs-search for their website then scrape it.
    NPI is an authoritative source — these are registered group practices.
    """
    NPI_API = "https://npiregistry.cms.hhs.gov/api/"
    new_companies = []

    with flask_app.app_context():
        from models import Company, db

        seen_domains = {
            _base_domain(u) for (u,) in
            db.session.query(Company.website_url)
            .filter(Company.website_url.isnot(None)).all()
            if u
        }
        seen_names = {
            n.lower() for (n,) in
            db.session.query(Company.company_name).all()
            if n
        }

        for taxonomy in NPI_TAXONOMIES:
            try:
                r = requests.get(NPI_API, params={
                    "version": "2.1",
                    "taxonomy_description": taxonomy,
                    "state": state_abbr,
                    "enumeration_type": "NPI-2",
                    "limit": 200,
                }, timeout=15, headers=HEADERS)
                results = r.json().get("results", [])
            except Exception as e:
                if progress_cb:
                    progress_cb(f"NPI error [{taxonomy}]: {e}")
                continue

            if progress_cb:
                progress_cb(f"NPI [{taxonomy}] → {len(results)} orgs found")

            for result in results[:20]:
                basic = result.get("basic") or {}
                if basic.get("status") != "A":
                    continue
                name = basic.get("organization_name", "").strip().title()
                if not name or name.lower() in seen_names:
                    continue

                addrs = result.get("addresses", [])
                addr = next(
                    (a for a in addrs if a.get("address_purpose") == "LOCATION"),
                    addrs[0] if addrs else {}
                )
                city    = addr.get("city", "").title()
                zip_    = addr.get("postal_code", "")[:5]
                phone   = addr.get("telephone_number", "")
                address = addr.get("address_1", "").title()

                # Find website via DDGs
                website_url = None
                domain = None
                try:
                    with DDGS() as ddgs:
                        hits = list(ddgs.text(
                            f'"{name}" {state_abbr} psychiatry psychology behavioral health',
                            max_results=5
                        ))
                    for h in hits:
                        u = h.get("href", "")
                        d = _base_domain(u)
                        if not d:
                            continue
                        if any(skip in d for skip in SKIP_DOMAINS):
                            continue
                        if any(tld in u for tld in SKIP_TLDS):
                            continue
                        if d not in seen_domains:
                            website_url = u
                            domain = d
                            break
                    time.sleep(2)
                except Exception:
                    pass

                seen_names.add(name.lower())
                if domain:
                    seen_domains.add(domain)

                rank = 55
                positive_phrases = ["npi-verified group practice"]
                ctype = "psychiatry" if "psychiatr" in taxonomy.lower() else "psychology"
                setting = "multi_setting"
                description = f"NPI-registered {taxonomy} group practice"
                status = "uncontacted"
                flag_review = False

                if website_url:
                    try:
                        data = scrape_company_website(website_url)
                        scraped_rank, scraped_positives = _score(data["text_full"])
                        rank = max(rank, scraped_rank)
                        positive_phrases += scraped_positives
                        ctype = _classify_type(data["text_full"])
                        setting = _classify_setting(data["text_full"])
                        description = (data.get("description") or description)[:500]
                        _, flag_review, _, excl = _qualifies(data["text_full"], data["text_core"])
                        if excl:
                            status = "flagged_for_review"
                            flag_review = True
                        phone = phone or data.get("phone") or ""
                    except Exception:
                        pass

                company = Company(
                    company_name     = name[:255],
                    website_url      = website_url,
                    phone            = phone or None,
                    address          = address or None,
                    city             = city or None,
                    state            = state_abbr,
                    zip              = zip_ or None,
                    company_type     = ctype,
                    delivery_setting = setting,
                    funding_status   = "unknown",
                    acquirable       = True,
                    rank_score       = rank,
                    status           = status,
                    verified         = False,
                    positive_signals = "; ".join(positive_phrases) or None,
                    description      = description,
                    last_scraped     = datetime.utcnow(),
                    last_updated     = datetime.utcnow(),
                )
                db.session.add(company)
                new_companies.append({
                    "name":    name,
                    "state":   state_abbr,
                    "score":   rank,
                    "flagged": flag_review,
                    "url":     website_url or "",
                })

            db.session.commit()
            time.sleep(3)

    return new_companies


def discover_from_directories(flask_app, progress_cb=None):
    """
    Fetch AAGP member directory and Psychology Today groups listing.
    Extract practice links, scrape qualifying ones.
    These pages may be JS-rendered; failures are handled gracefully.
    """
    DIRECTORY_URLS = [
        "https://www.aagpgp.org/find-a-geriatric-psychiatrist",
        "https://www.psychologytoday.com/us/groups/geriatric",
    ]
    new_companies = []

    with flask_app.app_context():
        from models import Company, db
        seen_domains = {
            _base_domain(u) for (u,) in
            db.session.query(Company.website_url)
            .filter(Company.website_url.isnot(None)).all()
            if u
        }

        for dir_url in DIRECTORY_URLS:
            if progress_cb:
                progress_cb(f"Directory: {dir_url}")
            html = _fetch(dir_url)
            if not html or len(html) < 500:
                if progress_cb:
                    progress_cb(f"  → No content (JS-rendered or blocked)")
                continue

            soup = BeautifulSoup(html, "html.parser")
            links = []
            base_host = urlparse(dir_url).netloc
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("http"):
                    continue
                if urlparse(href).netloc == base_host:
                    continue
                d = _base_domain(href)
                if d and not any(skip in d for skip in SKIP_DOMAINS) and d not in seen_domains:
                    links.append(href)

            seen_in_dir = set()
            added = 0
            for url in links[:30]:
                domain = _base_domain(url)
                if domain in seen_in_dir or domain in seen_domains:
                    continue
                seen_in_dir.add(domain)
                seen_domains.add(domain)
                time.sleep(2)

                try:
                    data = scrape_company_website(url)
                    qualifies, flag_review, signals, excl = _qualifies(data["text_full"], data["text_core"])
                    if not qualifies:
                        continue
                    rank, positive_phrases = _score(data["text_full"])
                    ctype = _classify_type(data["text_full"])
                    setting = _classify_setting(data["text_full"])
                    status = "flagged_for_review" if flag_review else "uncontacted"

                    extracted_name = data["company_name"]
                    junk_prefixes = ("the ", "top ", "best ", "how ", "what ", "why ",
                                     "when ", "understanding ", "exploring ", "a guide ")
                    if any(extracted_name.lower().startswith(pfx) for pfx in junk_prefixes):
                        continue
                    if len(extracted_name.split()) > 8:
                        continue

                    company = Company(
                        company_name     = extracted_name[:255],
                        website_url      = url,
                        phone            = data.get("phone"),
                        email            = data.get("email"),
                        address          = data.get("address"),
                        city             = data.get("city"),
                        state            = data.get("state_found") or "??",
                        zip              = data.get("zip"),
                        description      = (data.get("description") or "")[:500] or None,
                        company_type     = ctype,
                        delivery_setting = setting,
                        funding_status   = "unknown",
                        acquirable       = True,
                        rank_score       = rank,
                        status           = status,
                        verified         = False,
                        positive_signals = "; ".join(signals) if signals else None,
                        exclude_flags    = "; ".join(excl) if excl else None,
                        last_scraped     = datetime.utcnow(),
                        last_updated     = datetime.utcnow(),
                    )
                    db.session.add(company)
                    new_companies.append({
                        "name":    extracted_name,
                        "state":   data.get("state_found") or "??",
                        "score":   rank,
                        "flagged": flag_review,
                        "url":     url,
                    })
                    added += 1
                except Exception as e:
                    logger.debug("Directory scrape error %s: %s", url, e)

            db.session.commit()
            if progress_cb:
                progress_cb(f"  → {added} new companies added")

    return new_companies


def find_owner_linkedin(company_name, state):
    try:
        from googlesearch import search as google_search
        query = f'site:linkedin.com/in "{company_name}" {state} founder OR owner OR president OR "medical director"'
        return [r for r in google_search(query, num_results=5, sleep_interval=1)
                if "linkedin.com/in/" in r]
    except Exception as e:
        logger.error("LinkedIn search error: %s", e)
        return []
