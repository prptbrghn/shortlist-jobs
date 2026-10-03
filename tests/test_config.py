from __future__ import annotations

import json

import pytest

from shortlist.config import DEFAULT_WEIGHTS, ConfigError, Settings, from_dict, load_settings

from .conftest import EXAMPLES


def test_defaults():
    s = load_settings(None)
    assert (s.fresh_days, s.window_days, s.max_applicants, s.follow_up_days, s.top_n,
            s.reapply_cooldown_days) == (2, 7, 500, 7, 10, 90)
    assert s.priority_weights == DEFAULT_WEIGHTS


def test_example_settings_load_and_paths_resolve():
    s = load_settings(EXAMPLES / "settings.example.json")
    assert s.base_dir == EXAMPLES.resolve()
    assert s.tracker_path == EXAMPLES.resolve() / "Job_Search_Tracker.xlsx"
    assert s.logs_dir == EXAMPLES.resolve() / "logs"
    assert s.standard_answers_path is None
    assert "Target roles" in s.criteria


def test_partial_weights_are_merged(tmp_path):
    s = from_dict({"priority_weights": {"fit": 3}}, tmp_path)
    assert s.priority_weights["fit"] == 3
    assert s.priority_weights["freshness"] == 20


def test_resume_for_role():
    s = Settings()
    assert s.resume_for_role("Product Owner") == "Product"
    assert s.resume_for_role("Program Manager") == "Project_Delivery"
    assert s.resume_for_role(None) == "Project_Delivery"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"fresh_dayz": 2}, "unknown setting"),
        ({"fresh_days": -1}, "whole number"),
        ({"window_days": "7"}, "whole number"),
        ({"max_applicants": True}, "whole number"),
        ({"fresh_days": 8, "window_days": 7}, "cannot be larger"),
        ({"window_days": 0, "fresh_days": 0}, "at least 1"),
        ({"priority_weights": {"luck": 5}}, "unknown priority weight"),
        ({"priority_weights": {"fit": -1}}, "number >= 0"),
        ({"priority_weights": []}, "must be an object"),
        ({"resumes": {}}, "non-empty"),
        ({"resumes": {"A": ""}}, "non-empty file name"),
        ({"default_resume_version": "Missing"}, "not in 'resumes'"),
        ({"resume_by_role_type": {"PM": "Nope"}}, "unknown resume"),
        ({"lists": {"Colour": ["a"]}}, "unknown list"),
        ({"lists": {"Source": ["a,b"]}}, "commas"),
        ({"lists": {"Source": []}}, "non-empty list"),
        ({"recruiter_patterns": [""]}, "recruiter_patterns"),
        ({"criteria": {"Roles": 5}}, "criteria"),
        ({"tracker_path": ""}, "path string"),
    ],
)
def test_invalid_settings(data, message):
    with pytest.raises(ConfigError, match=message):
        from_dict(data)


def test_comment_keys_allowed(tmp_path):
    assert from_dict({"_comment": "hi", "$schema": "x"}, tmp_path).fresh_days == 2


def test_missing_and_malformed_files(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_settings(bad)
    not_obj = tmp_path / "list.json"
    not_obj.write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON object"):
        load_settings(not_obj)


def test_round_trip(tmp_path):
    s = Settings(base_dir=tmp_path, max_applicants=250)
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(s.to_dict()), encoding="utf-8")
    again = load_settings(p)
    assert again.max_applicants == 250
    assert again.tracker_path == s.tracker_path
