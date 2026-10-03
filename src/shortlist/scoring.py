"""Transparent ranking: warning flags, resume keyword match and the 0-100 priority score.

Priority = fit (Match Score x fit weight, max 50)
         + freshness (max 20, falls linearly to 0 at ``window_days``)
         + competition (max 20: <=50 applicants 100%, <=100 75%, <=200 50%, unknown 25%, more 10%)
         + keyword match (max 10, share of key requirements found in the resume)
         - penalty per serious flag (default 6), clamped to 0-100.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .config import Settings
from .rules import applicant_count, as_date, company_key

STOP_WORDS = frozenset(
    """and the for with from into your our you are was were have has had this that these those will would
can could should able ability experience experienced years year yrs plus strong good excellent knowledge understanding
working work using use used etc including across within other skills skill team teams role roles preferred required
must nice have based""".split()
)

SAFETY_MARKER = "[safety]"
SERIOUS_FLAGS = ("Possible repost", "Recruiter / hidden employer", "Rejected here recently", "Suspicious page text")
ACTIVE_STATUSES = ("Applied", "Screening", "Interviewing", "Offer")
REMOTE_VISA_VALUE = "Remote from home country"

_TIMEZONE_RE = re.compile(r"\b(us shift|night shift|est|pst|pacific hours|arizona)\b")
_JUNIOR_RE = re.compile(r"entry.level|\bjunior\b")
_ASSOCIATE_RE = re.compile(r"\bassociate\b")
_SENIOR_TITLE_RE = re.compile(r"\b(director|manager|lead|head)\b")
_CERT_RE = re.compile(r"\b(pmp|cspo|pspo|prince2|csm|psm)\b")
_SAFE_CERT_RE = re.compile(r"\bSAFe\b")  # case-sensitive: the word "safe" is not the SAFe certification
_EXPERIENCE_RE = re.compile(r"(\d+)\s*(\+|-|to)")
_TAILORED_RESUME_RE = re.compile(r"resumes/([\w.-]+)\.(?:pdf|docx)")
_WORD_RE = re.compile(r"[a-z][a-z0-9+#/.&-]{2,}")


def _text(job: dict[str, Any], *keys: str) -> str:
    return " ".join(str(job.get(k) or "") for k in keys)


def tailored_resume(notes: Any) -> str | None:
    """Return a resume file stem referenced in Notes as ``resumes/<name>.pdf``, if any."""
    match = _TAILORED_RESUME_RE.search(str(notes or ""))
    return match.group(1) if match else None


def key_requirements(notes: Any) -> list[str]:
    """Requirements listed in Notes after ``Key:`` and separated by ``;`` or ``|``."""
    match = re.search(r"Key:\s*(.*)", str(notes or ""))
    if not match:
        return []
    return [p for p in re.split(r"[;|]", match.group(1)) if p.strip()]


def keyword_match(job: dict[str, Any], resume_text: str) -> int | None:
    """% of the job's key requirements whose main words appear in the resume text.

    A requirement counts as matched when at least half of its non-stop-words appear in the resume.
    Returns None if the job lists no requirements or the resume text is empty.
    """
    phrases = key_requirements(job.get("Notes"))
    text = (resume_text or "").lower()
    if not phrases or not text:
        return None
    hit = 0
    for phrase in phrases:
        words = [w.strip(".,()") for w in _WORD_RE.findall(phrase.lower())]
        words = [w for w in words if w and w not in STOP_WORDS]
        if words and sum(has_word(w, text) for w in words) / len(words) >= 0.5:
            hit += 1
    return round(100 * hit / len(phrases))


def has_word(word: str, text: str) -> bool:
    """Whole-word match (a simple plural "s"/"es" allowed): "agile" is not found in "fragile"."""
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?:s|es)?(?![a-z0-9])", text) is not None


def job_flags(
    job: dict[str, Any],
    by_company: dict[str, list[dict[str, Any]]],
    today: date,
    settings: Settings | None = None,
) -> list[str]:
    """Automatic warnings for one job. ``by_company`` maps company_key -> all tracker rows for it."""
    s = settings or Settings()
    txt = _text(job, "Red Flags", "Notes", "Role Title", "Salary Listed").lower()
    company = str(job.get("Company") or "").lower()
    out: list[str] = []
    recruiter_text = company + " " + str(job.get("Red Flags") or "").lower()
    if any(p.lower() in recruiter_text for p in s.recruiter_patterns):
        out.append("Recruiter / hidden employer")
    if "repost" in txt:
        out.append("Possible repost")
    if _TIMEZONE_RE.search(txt):
        out.append("US / night hours")
    title = str(job.get("Role Title") or "").lower()
    # "Associate" signals a junior role unless the title is a Director/Manager/Lead/Head one.
    if _JUNIOR_RE.search(txt) or (_ASSOCIATE_RE.search(txt) and not _SENIOR_TITLE_RE.search(title)):
        out.append("Junior level")
    m = _EXPERIENCE_RE.search(str(job.get("Experience Required") or ""))
    if m and int(m.group(1)) >= s.flag_experience_years:
        out.append(f"Asks {m.group(1)}+ yrs")
    raw_txt = _text(job, "Red Flags", "Notes", "Role Title", "Salary Listed")
    if _CERT_RE.search(txt) or _SAFE_CERT_RE.search(raw_txt):
        out.append("Certification mentioned")
    if job.get("Visa / Sponsorship") == "Sponsorship unclear":
        out.append("Visa unclear")
    if job.get("Visa / Sponsorship") == REMOTE_VISA_VALUE and not re.search(r"\d", str(job.get("Salary Listed") or "")):
        out.append("Check pay vs floor")
    others = [o for o in by_company.get(company_key(job.get("Company")), []) if o is not job]
    if any(o.get("Status") in ACTIVE_STATUSES for o in others):
        out.append("Already applied here")
    cutoff = today - timedelta(days=s.reapply_cooldown_days)
    if any(
        o.get("Status") == "Rejected"
        and (as_date(o.get("Response Date")) or as_date(o.get("Date Applied")) or today) >= cutoff
        for o in others
    ):
        out.append("Rejected here recently")
    if SAFETY_MARKER in txt:
        out.append("Suspicious page text")
    return out


def competition_share(applicants: Any) -> float:
    """Share of the competition weight earned for a given applicant text."""
    c = applicant_count(str(applicants or ""))
    if c is None:
        return 0.25
    if c <= 50:
        return 1.0
    if c <= 100:
        return 0.75
    if c <= 200:
        return 0.5
    return 0.1


def priority(
    job: dict[str, Any],
    flags: list[str],
    km: int | None,
    today: date,
    settings: Settings | None = None,
) -> int:
    """Transparent ranking score (0-100): fit + freshness + low competition + keyword match - serious flags."""
    s = settings or Settings()
    w = s.priority_weights
    fit = job.get("Match Score (1-10)") or 5
    try:
        fit = float(fit)
    except (TypeError, ValueError):
        fit = 5.0
    posted = as_date(job.get("Date Posted"))
    age = max(0, (today - posted).days) if posted else s.window_days  # a future date counts as today
    fresh = max(0.0, 1 - age / s.window_days) * w["freshness"]
    comp = w["competition"] * competition_share(job.get("Applicants"))
    kw = w["keywords"] * (km or 0) / 100
    pen = w["serious_flag_penalty"] * sum(f in SERIOUS_FLAGS for f in flags)
    return max(0, min(100, round(fit * w["fit"] + fresh + comp + kw - pen)))


def explain_priority(job: dict[str, Any], flags: list[str], km: int | None, today: date,
                     settings: Settings | None = None) -> str:
    """One-sentence explanation of how a job's priority was computed."""
    s = settings or Settings()
    w = s.priority_weights
    posted = as_date(job.get("Date Posted"))
    age = max(0, (today - posted).days) if posted else s.window_days
    serious = [f for f in flags if f in SERIOUS_FLAGS]
    return (
        f"fit {job.get('Match Score (1-10)') or 5}x{w['fit']:g}"
        f" + freshness {max(0.0, 1 - age / s.window_days) * w['freshness']:.0f}"
        f" + competition {w['competition'] * competition_share(job.get('Applicants')):.0f}"
        f" + keywords {w['keywords'] * (km or 0) / 100:.0f}"
        f" - {len(serious)} serious flag(s) x {w['serious_flag_penalty']:g}"
        f" = {priority(job, flags, km, today, s)}"
    )
