from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

PRIORITY_STATES = [
    ("Texas",          "TX",  1),
    ("Florida",        "FL",  2),
    ("Georgia",        "GA",  3),
    ("North Carolina", "NC",  4),
    ("South Carolina", "SC",  5),
    ("Pennsylvania",   "PA",  6),
    ("Ohio",           "OH",  7),
    ("Michigan",       "MI",  8),
    ("Illinois",       "IL",  9),
    ("Tennessee",      "TN", 10),
    ("Arizona",        "AZ", 11),
    ("Virginia",       "VA", 12),
    ("Colorado",       "CO", 13),
    ("Minnesota",      "MN", 14),
    ("Indiana",        "IN", 15),
]

COMPANY_TYPES = [
    ("psychiatry",        "Psychiatry"),
    ("psychology",        "Psychology"),
    ("behavioral_health", "Behavioral Health"),
    ("neuropsychology",   "Neuropsychology"),
    ("combined",          "Combined"),
]

DELIVERY_SETTINGS = [
    ("snf",           "Skilled Nursing (SNF)"),
    ("alf",           "Assisted Living (ALF)"),
    ("memory_care",   "Memory Care"),
    ("in_home",       "In-Home"),
    ("multi_setting", "Multi-Setting"),
]

REVENUE_ESTIMATES = [
    ("$1M-3M",   "$1M–$3M"),
    ("$3M-10M",  "$3M–$10M"),
    ("$10M-20M", "$10M–$20M"),
    ("unknown",  "Unknown"),
]

FUNDING_STATUSES = [
    ("founder_operated", "Founder Operated"),
    ("unknown",          "Unknown"),
    ("flagged_pe",       "Flagged — PE"),
    ("flagged_vc",       "Flagged — VC"),
]

PIPELINE_STATUSES = [
    ("uncontacted",        "Uncontacted"),
    ("contacted",          "Contacted"),
    ("responded",          "Responded"),
    ("meeting_scheduled",  "Meeting Scheduled"),
    ("passed",             "Passed"),
    ("flagged_for_review", "Flagged for Review"),
]

CHANNELS = [
    ("email",      "Email"),
    ("phone",      "Phone"),
    ("linkedin",   "LinkedIn"),
    ("conference", "Conference"),
    ("referral",   "Referral"),
]

OUTCOMES = [
    ("no_response",    "No Response"),
    ("positive",       "Positive"),
    ("negative",       "Negative"),
    ("meeting_set",    "Meeting Set"),
    ("not_interested", "Not Interested"),
]


class Company(db.Model):
    __tablename__ = "companies"

    id                      = db.Column(db.Integer, primary_key=True)
    company_name            = db.Column(db.String(255), nullable=False)
    website_url             = db.Column(db.String(500))
    phone                   = db.Column(db.String(50))
    email                   = db.Column(db.String(255))
    address                 = db.Column(db.String(500))
    city                    = db.Column(db.String(100))
    state                   = db.Column(db.String(10))
    zip                     = db.Column(db.String(20))
    description             = db.Column(db.Text)
    company_type            = db.Column(db.String(50), default="behavioral_health")
    delivery_setting        = db.Column(db.String(50), default="multi_setting")
    employee_count_estimate = db.Column(db.String(50))
    year_founded            = db.Column(db.String(10))
    revenue_estimate        = db.Column(db.String(20), default="unknown")
    funding_status          = db.Column(db.String(30), default="unknown")
    acquirable              = db.Column(db.Boolean, default=True)
    rank_score              = db.Column(db.Integer, default=50)
    status                  = db.Column(db.String(50), default="uncontacted")
    verified                = db.Column(db.Boolean, default=False)
    positive_signals        = db.Column(db.Text)
    exclude_flags           = db.Column(db.Text)
    notes                   = db.Column(db.Text)
    last_scraped            = db.Column(db.DateTime)
    last_updated            = db.Column(db.DateTime, default=datetime.utcnow,
                                        onupdate=datetime.utcnow)

    contacts      = db.relationship("Contact",     backref="company", lazy="select",
                                    cascade="all, delete-orphan")
    outreach_logs = db.relationship("OutreachLog", backref="company", lazy="select",
                                    cascade="all, delete-orphan")

    @property
    def primary_contact(self):
        for c in self.contacts:
            if c.is_primary:
                return c
        return self.contacts[0] if self.contacts else None

    @property
    def score_tier(self):
        if self.rank_score is None:
            return "medium"
        if self.rank_score >= 70:
            return "high"
        if self.rank_score >= 50:
            return "medium"
        return "low"

    def to_dict(self):
        pc = self.primary_contact
        return {
            "id":                      self.id,
            "company_name":            self.company_name,
            "website_url":             self.website_url,
            "phone":                   self.phone,
            "email":                   self.email,
            "address":                 self.address,
            "city":                    self.city,
            "state":                   self.state,
            "zip":                     self.zip,
            "description":             self.description,
            "company_type":            self.company_type,
            "delivery_setting":        self.delivery_setting,
            "employee_count_estimate": self.employee_count_estimate,
            "year_founded":            self.year_founded,
            "revenue_estimate":        self.revenue_estimate,
            "funding_status":          self.funding_status,
            "acquirable":              self.acquirable,
            "rank_score":              self.rank_score,
            "status":                  self.status,
            "verified":                self.verified,
            "positive_signals":        self.positive_signals,
            "exclude_flags":           self.exclude_flags,
            "notes":                   self.notes,
            "last_scraped":            self.last_scraped.isoformat() if self.last_scraped else None,
            "last_updated":            self.last_updated.isoformat() if self.last_updated else None,
            "owner_name":              pc.name if pc else None,
            "owner_title":             pc.title if pc else None,
        }


class Contact(db.Model):
    __tablename__ = "contacts"

    id           = db.Column(db.Integer, primary_key=True)
    company_id   = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    name         = db.Column(db.String(255))
    title        = db.Column(db.String(255))
    phone        = db.Column(db.String(50))
    email        = db.Column(db.String(255))
    linkedin_url = db.Column(db.String(500))
    is_primary   = db.Column(db.Boolean, default=False)
    notes        = db.Column(db.Text)

    def to_dict(self):
        return {
            "id":           self.id,
            "company_id":   self.company_id,
            "name":         self.name,
            "title":        self.title,
            "phone":        self.phone,
            "email":        self.email,
            "linkedin_url": self.linkedin_url,
            "is_primary":   self.is_primary,
            "notes":        self.notes,
        }


class OutreachLog(db.Model):
    __tablename__ = "outreach_log"

    id             = db.Column(db.Integer, primary_key=True)
    company_id     = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    contact_id     = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=True)
    date           = db.Column(db.DateTime, default=datetime.utcnow)
    channel        = db.Column(db.String(50))
    outcome        = db.Column(db.String(50))
    notes          = db.Column(db.Text)
    follow_up_date = db.Column(db.Date)

    contact = db.relationship("Contact", foreign_keys=[contact_id])

    def to_dict(self):
        return {
            "id":             self.id,
            "company_id":     self.company_id,
            "contact_id":     self.contact_id,
            "date":           self.date.isoformat() if self.date else None,
            "channel":        self.channel,
            "outcome":        self.outcome,
            "notes":          self.notes,
            "follow_up_date": self.follow_up_date.isoformat() if self.follow_up_date else None,
        }
