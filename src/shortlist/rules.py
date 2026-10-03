"""Deterministic filtering rules: applicant counts, the freshness rule, duplicate keys.

Freshness rule (defaults). Age is counted in whole calendar days (today minus the posting date),
not hours:
- posted today or within the previous ``fresh_days`` (2) calendar days -> keep;
- posted up to ``window_days`` (7) calendar days ago -> keep only if a specific applicant count of
  ``max_applicants`` (500) or fewer is shown;
- older, undated, or dated in the future -> drop.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .config import Settings

_CAPPED_MARKERS = ("over", "more than", "más de", "+")
_COUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)(?:\s*(k)(?![a-z]))?")


def applicant_count(text: str | None) -> int | None:
    """Return the applicant count if the text states one we can trust as an upper bound, else None.

    Capped or hidden counts ("Over 200", "200+", "More than 200", "Más de 200", "Not shown")
    are unknown (None), never a number. "Be among the first 25 applicants" counts as 25.
    """
    t = (text or "").lower()
    if any(m in t for m in _CAPPED_MARKERS) or not re.search(r"\d", t):
        return None
    if "first" in t:
        match = re.search(r"\d+", t)
        return int(match.group()) if match else None
    # B-001: "1.2K applicants" is 1,200, not 1.
    match = _COUNT_RE.search(t)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    return round(number * 1000) if match.group(2) else int(number)


def as_date(value: Any) -> date | None:
    """Coerce a date, datetime or ISO string (``YYYY-MM-DD...``) to a date; otherwise None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def passes(job: dict[str, Any], today: date, settings: Settings | None = None) -> tuple[bool, int | None, str]:
    """Apply the freshness rule to one job.

    Returns ``(keep, age_in_days, reason)``. Jobs without a valid "Date Posted" are dropped.
    """
    s = settings or Settings()
    posted = as_date(job.get("Date Posted"))
    if posted is None:
        return False, None, "no valid posting date"
    age = (today - posted).days
    if age < 0:
        return False, age, "posted date in the future"
    if age <= s.fresh_days:
        return True, age, "fresh"
    if age > s.window_days:
        return False, age, f"older than {s.window_days} days"
    band = f"{s.fresh_days + 1}-{s.window_days} days old"
    count = applicant_count(str(job.get("Applicants") or ""))
    if count is None:
        return False, age, f"{band} and applicant count not confirmed"
    if count > s.max_applicants:
        return False, age, f"{band} and {count} applicants"
    return True, age, f"{band} with confirmed low applicants"


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def job_key(company: Any, title: Any) -> tuple[str, str]:
    """Company + role title, normalised, so the same job posted twice under different links is caught.

    Anything in brackets in the company name (e.g. "(for a client)") is ignored.
    """
    return _norm(re.sub(r"\(.*?\)", "", str(company or ""))), _norm(title)


def company_key(name: Any) -> str:
    """Normalised company name used for same-company checks."""
    return job_key(name, "")[0]


def is_stale(job: dict[str, Any], today: date, settings: Settings | None = None) -> bool:
    """True if a job not yet acted on should be pruned: Skipped, undated, too old, or too crowded."""
    s = settings or Settings()
    if job.get("Status") == "Skipped":
        return True
    posted = as_date(job.get("Date Posted"))
    if posted is None:
        return True
    age = (today - posted).days
    if age < 0 or age > s.window_days:  # a future date is invalid
        return True
    count = applicant_count(str(job.get("Applicants") or ""))
    return age > s.fresh_days and (count is None or count > s.max_applicants)


def self_check(today: date | None = None) -> list[tuple[str, bool, Any, Any]]:
    """Built-in rule checks (used by ``shortlist test-rules``). Returns (name, ok, got, expected)."""
    today = today or date(2026, 9, 29)
    s = Settings()

    def job(posted: str, applicants: str) -> dict[str, str]:
        return {"Date Posted": posted, "Applicants": applicants}

    def ago(days: int) -> str:
        return date.fromordinal(today.toordinal() - days).isoformat()

    cases: list[tuple[str, Any, Any]] = [
        ("Over 200 is unknown", applicant_count("Over 200 applicants"), None),
        ("200+ is unknown", applicant_count("200+"), None),
        ("More than 200 is unknown", applicant_count("More than 200"), None),
        ("Spanish capped count is unknown", applicant_count("Más de 200 solicitudes"), None),
        ("Not shown is unknown", applicant_count("Not shown"), None),
        ("Exact count", applicant_count("54 applicants"), 54),
        ("Count with comma", applicant_count("1,234 applicants"), 1234),
        ("Be among the first 25", applicant_count("Be among the first 25 applicants"), 25),
        ("1.2K is 1200 (B-001)", applicant_count("1.2K applicants"), 1200),
        ("Posted in the future: drop", passes(job(ago(-1), "10"), today, s)[0], False),
        ("Posted today, crowded: keep", passes(job(ago(0), "Over 200"), today, s)[0], True),
        ("2 days old, unknown count: keep", passes(job(ago(2), "Not shown"), today, s)[0], True),
        ("3 days old, unknown count: drop", passes(job(ago(3), "Over 200"), today, s)[0], False),
        ("5 days old, 180 applicants: keep", passes(job(ago(5), "180"), today, s)[0], True),
        ("5 days old, 600 applicants: drop", passes(job(ago(5), "600"), today, s)[0], False),
        ("7 days old, 54 applicants: keep", passes(job(ago(7), "54"), today, s)[0], True),
        ("8 days old: drop", passes(job(ago(8), "10"), today, s)[0], False),
        ("Same job, recruiter suffix ignored",
         job_key("Acme", "Delivery Manager") == job_key("Acme (for a client)", "Delivery Manager"), True),
        ("Different roles differ", job_key("Acme", "Delivery Manager") == job_key("Acme", "Project Manager"), False),
    ]
    return [(name, got == expected, got, expected) for name, got, expected in cases]
