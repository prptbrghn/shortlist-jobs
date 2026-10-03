from __future__ import annotations

from datetime import date

import pytest

from shortlist.config import Settings
from shortlist.rules import applicant_count, as_date, company_key, is_stale, job_key, passes, self_check

from .conftest import TODAY


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Over 200 applicants", None),
        ("200+", None),
        ("More than 200", None),
        ("Más de 200 solicitudes", None),
        ("Not shown", None),
        ("", None),
        (None, None),
        ("54 applicants", 54),
        ("1,234 applicants", 1234),
        ("Be among the first 25 applicants", 25),
        ("Among the first 25 applicants", 25),
        ("180", 180),
    ],
)
def test_applicant_count(text, expected):
    assert applicant_count(text) == expected


def job(posted, applicants):
    return {"Date Posted": posted, "Applicants": applicants}


@pytest.mark.parametrize(
    ("posted", "applicants", "keep"),
    [
        ("2026-09-29", "Over 200", True),   # posted today, crowded: keep
        ("2026-09-27", "Not shown", True),  # 2 days old, unknown count: keep
        ("2026-09-26", "Over 200", False),  # 3 days old, unknown count: drop
        ("2026-09-26", "200+", False),
        ("2026-09-25", "Más de 200", False),
        ("2026-09-25", "Be among the first 25", True),
        ("2026-09-24", "180", True),        # 5 days old, 180 applicants: keep
        ("2026-09-24", "600", False),       # 5 days old, 600 applicants: drop
        ("2026-09-24", "500", True),        # exactly at the limit: keep
        ("2026-09-24", "501", False),
        ("2026-09-22", "54", True),         # 7 days old (boundary), 54 applicants: keep
        ("2026-09-21", "10", False),        # 8 days old: drop
    ],
)
def test_freshness_rule(posted, applicants, keep):
    assert passes(job(posted, applicants), TODAY)[0] is keep


def test_passes_reasons_and_age():
    assert passes(job("2026-09-29", "Over 200"), TODAY) == (True, 0, "fresh")
    ok, age, reason = passes(job("2026-09-21", "10"), TODAY)
    assert (ok, age) == (False, 8) and "older than 7 days" in reason
    assert "not confirmed" in passes(job("2026-09-26", "Over 200"), TODAY)[2]
    assert "600 applicants" in passes(job("2026-09-24", "600"), TODAY)[2]


def test_passes_missing_or_bad_date():
    assert passes({"Applicants": "10"}, TODAY) == (False, None, "no valid posting date")
    assert passes(job("yesterday", "10"), TODAY)[0] is False


def test_passes_respects_settings():
    strict = Settings(fresh_days=0, window_days=3, max_applicants=100)
    assert passes(job("2026-09-28", "Not shown"), TODAY, strict)[0] is False
    assert passes(job("2026-09-28", "90"), TODAY, strict)[0] is True
    assert passes(job("2026-09-25", "90"), TODAY, strict)[0] is False


def test_job_key_dedupe():
    assert job_key("Acme", "Client Project Management Manager") == job_key(
        "Acme (for a client)", "Client Project Management Manager"
    )
    assert job_key("ACME ", "Delivery  Manager!") == job_key("acme", "delivery manager")
    assert job_key("Acme", "Delivery Manager") != job_key("Acme", "Project Manager")
    assert company_key("Acme (for Globex)") == "acme"


def test_as_date():
    assert as_date("2026-09-29T10:00:00") == date(2026, 9, 29)
    assert as_date("") is None
    assert as_date("not a date") is None
    assert as_date(None) is None


def test_is_stale():
    assert is_stale({"Status": "Skipped", "Date Posted": "2026-09-29"}, TODAY)
    assert is_stale({"Date Posted": None}, TODAY)
    assert is_stale({"Date Posted": "2026-09-20", "Applicants": "10"}, TODAY)
    assert is_stale({"Date Posted": "2026-09-25", "Applicants": "Over 200"}, TODAY)
    assert not is_stale({"Date Posted": "2026-09-25", "Applicants": "100"}, TODAY)
    assert not is_stale({"Date Posted": "2026-09-28", "Applicants": "Not shown"}, TODAY)


def test_self_check_all_pass():
    results = self_check(TODAY)
    assert len(results) >= 17
    assert all(ok for _, ok, _, _ in results)
