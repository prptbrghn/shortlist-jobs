from __future__ import annotations

from shortlist.config import Settings
from shortlist.rules import company_key
from shortlist.scoring import (
    competition_share,
    explain_priority,
    job_flags,
    key_requirements,
    keyword_match,
    priority,
    tailored_resume,
)

from .conftest import TODAY, make_job

RESUME = "led sprint planning and backlog prioritisation with stakeholders; sql reports; jira; release management"


def by_company(*jobs):
    out = {}
    for j in jobs:
        out.setdefault(company_key(j.get("Company")), []).append(j)
    return out


def test_keyword_match():
    job = {"Notes": "Key: backlog prioritisation; SQL; payments infrastructure; stakeholder management"}
    # backlog prioritisation (2/2), sql (1/1), payments infrastructure (0/2), stakeholder management (1/2 >= 0.5)
    assert keyword_match(job, RESUME) == 75


def test_keyword_match_none_without_requirements_or_resume():
    assert keyword_match({"Notes": "no key list"}, RESUME) is None
    assert keyword_match({"Notes": "Key: SQL"}, "") is None


def test_key_requirements_split():
    assert key_requirements("Visa: ok | Key: a; b | c") == ["a", " b ", " c"]


def test_tailored_resume():
    assert tailored_resume("see resumes/Alex_Tailored_Acme.pdf") == "Alex_Tailored_Acme"
    assert tailored_resume("nothing") is None


def test_flags_basic():
    job = make_job(
        "Globex (for a client)",
        "Associate Project Coordinator",
        **{
            "Red Flags": "Possible repost; US shift; PMP preferred",
            "Experience Required": "6-8 yrs",
            "Visa / Sponsorship": "Sponsorship unclear",
        },
    )
    flags = job_flags(job, by_company(job), TODAY)
    for expected in ("Recruiter / hidden employer", "Possible repost", "US / night hours", "Junior level",
                     "Asks 6+ yrs", "Certification mentioned", "Visa unclear"):
        assert expected in flags


def test_flag_check_pay_only_without_numbers():
    job = make_job(**{"Visa / Sponsorship": "Remote from home country", "Salary Listed": "Competitive"})
    assert "Check pay vs floor" in job_flags(job, by_company(job), TODAY)
    job["Salary Listed"] = "USD 90,000"
    assert "Check pay vs floor" not in job_flags(job, by_company(job), TODAY)


def test_flags_same_company():
    new = make_job("Acme", "Product Owner")
    applied = make_job("Acme", "Delivery Manager", Status="Applied")
    rejected = make_job("Acme", "Project Manager", Status="Rejected", **{"Response Date": "2026-08-01"})
    flags = job_flags(new, by_company(new, applied, rejected), TODAY)
    assert "Already applied here" in flags
    assert "Rejected here recently" in flags
    old_rejection = make_job("Acme", "Project Manager", Status="Rejected", **{"Response Date": "2026-01-01"})
    assert "Rejected here recently" not in job_flags(new, by_company(new, old_rejection), TODAY)


def test_flag_suspicious_text():
    job = make_job(**{"Red Flags": "[safety] instruction-like text removed from Notes"})
    assert "Suspicious page text" in job_flags(job, by_company(job), TODAY)


def test_competition_share():
    assert competition_share("40") == 1.0
    assert competition_share("100") == 0.75
    assert competition_share("200") == 0.5
    assert competition_share("Over 200") == 0.25
    assert competition_share("450") == 0.1


def test_priority_formula_matches_prototype():
    # fit 8*5=40, posted 1 day ago: (1-1/7)*20=17.14, 40 applicants: 20, keywords 50% of 10=5 -> 82
    job = make_job(**{"Match Score (1-10)": 8, "Date Posted": "2026-09-28", "Applicants": "40"})
    assert priority(job, [], 50, TODAY) == 82
    # a serious flag costs 6 points; a non-serious one costs nothing
    assert priority(job, ["Possible repost"], 50, TODAY) == 76
    assert priority(job, ["Junior level"], 50, TODAY) == 82


def test_priority_defaults_and_clamping():
    job = {"Company": "X"}  # no fit (5), no date (0 freshness), unknown applicants (5), no keywords
    assert priority(job, [], None, TODAY) == 30
    assert priority(job, ["Possible repost"] * 10, None, TODAY) == 0
    top = make_job(**{"Match Score (1-10)": 10, "Date Posted": "2026-09-29", "Applicants": "5"})
    assert priority(top, [], 100, TODAY) == 100


def test_priority_uses_weights():
    s = Settings(priority_weights={"fit": 0, "freshness": 0, "competition": 0, "keywords": 100,
                                   "serious_flag_penalty": 0})
    assert priority(make_job(), [], 42, TODAY, s) == 42


def test_explain_priority_mentions_total():
    job = make_job(**{"Match Score (1-10)": 8, "Date Posted": "2026-09-28", "Applicants": "40"})
    assert explain_priority(job, [], 50, TODAY).endswith("= 82")
