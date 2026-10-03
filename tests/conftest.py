from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from shortlist.config import Settings

TODAY = date(2026, 9, 29)
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Default settings with every path inside a temporary folder."""
    return Settings(base_dir=tmp_path)


def make_job(company: str = "Acme", title: str = "Delivery Manager", **fields) -> dict:
    job = {
        "Company": company,
        "Role Title": title,
        "Role Type": "Delivery Manager",
        "Job URL": f"https://jobs.example.com/{company.lower().replace(' ', '-')}/{title.lower().replace(' ', '-')}",
        "Date Posted": "2026-09-28",
        "Applicants": "40",
        "Match Score (1-10)": 7,
        "Status": "Found",
    }
    job.update(fields)
    return job
