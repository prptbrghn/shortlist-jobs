from __future__ import annotations

import csv
import json
from datetime import date

import pytest

from shortlist.normalize import RawJobsError, load_raw_jobs, normalize_file, normalize_jobs
from shortlist.safety import REDACTION

from .conftest import EXAMPLES, TODAY, make_job

EXAMPLE_DAY = date(2026, 9, 29)


def test_example_file_end_to_end(settings, tmp_path):
    out = tmp_path / "jobs.json"
    result = normalize_file(EXAMPLES / "raw_jobs.example.json", out, EXAMPLE_DAY, settings)
    kept = {j["Company"]: j for j in json.loads(out.read_text(encoding="utf-8"))}
    assert set(kept) == {"Acme Analytics", "Bluebird Health", "Driftwood Travel", "Example Staffing (for a client)"}
    assert [d["Company"] for d in result.dropped] == ["Cobalt Logistics"]
    assert "650 applicants" in result.dropped[0]["Reason"]

    # the injection in Red Flags / Notes is redacted and marked
    staffing = kept["Example Staffing (for a client)"]
    assert "[safety]" in staffing["Red Flags"]
    assert REDACTION in staffing["Red Flags"]
    assert "previous instructions" not in staffing["Red Flags"].lower()
    assert "jobs@example.com" not in staffing["Notes"]
    assert "note to the ai" not in staffing["Red Flags"].lower()  # HTML comment stripped

    # folded fields and defaults
    acme = kept["Acme Analytics"]
    assert acme["Applicants"] == "Over 200"
    assert acme["Resume Version"] == "Product"
    assert acme["Status"] == "Found"
    assert acme["Date Found"] == "2026-09-29"
    assert "Key: backlog prioritisation" in acme["Notes"]
    assert "Visa: Local role" in acme["Notes"]
    assert "Key Requirements" not in acme
    assert kept["Bluebird Health"]["Resume Version"] == "Project_Delivery"

    # logs
    rejected = json.loads((settings.logs_dir / "rejected_raw_jobs.example.json").read_text(encoding="utf-8"))
    assert rejected[0]["Company"] == "Cobalt Logistics"
    assert (settings.logs_dir / "safety_raw_jobs.example.json").exists()
    with (settings.logs_dir / "runs.csv").open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["run_date", "source_file", "found", "kept", "dropped"]
    assert rows[1] == ["2026-09-29", "raw_jobs.example.json", "5", "4", "1"]


def test_invalid_url_and_non_objects_dropped():
    result = normalize_jobs(
        [make_job(**{"Job URL": "javascript:alert(1)", "Date Posted": "2026-09-29"}), "not a job",
         make_job(Company="", **{"Date Posted": "2026-09-29"})],
        TODAY,
    )
    assert result.kept == []
    reasons = [d["Reason"] for d in result.dropped]
    assert reasons[0].startswith("invalid link")
    assert reasons[1] == "not a JSON object"
    assert reasons[2] == "missing company or role title"


def test_agent_cannot_set_computed_fields_or_advanced_status():
    raw = make_job(Status="Applied", Priority=100, Flags="none", **{"Date Posted": "2026-09-29",
                                                                    "Match Score (1-10)": "11"})
    kept = normalize_jobs([raw], TODAY).kept[0]
    assert kept["Status"] == "Found"
    assert "Priority" not in kept and "Flags" not in kept
    assert "Match Score (1-10)" not in kept  # out of range
    raw["Match Score (1-10)"] = "8"
    assert normalize_jobs([raw], TODAY).kept[0]["Match Score (1-10)"] == 8


def test_html_in_fields_is_cleaned():
    raw = make_job(**{"Date Posted": "2026-09-29", "Why It Fits": "<b>Great</b> fit<script>x()</script>"})
    result = normalize_jobs([raw], TODAY)
    assert result.kept[0]["Why It Fits"] == "Great fit"
    assert result.warnings


def test_load_raw_jobs_accepts_array_wrapped_in_prose(tmp_path):
    p = tmp_path / "raw.json"
    p.write_text('Here are the jobs:\n[{"Company": "A"}]\nRejected: B (too old)', encoding="utf-8")
    assert load_raw_jobs(p) == [{"Company": "A"}]
    p.write_text('{"Company": "A"}', encoding="utf-8")
    with pytest.raises(RawJobsError):
        load_raw_jobs(p)
    p.write_text("no json here", encoding="utf-8")
    with pytest.raises(RawJobsError):
        load_raw_jobs(p)
