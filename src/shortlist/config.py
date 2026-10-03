"""Load and validate Shortlist settings.

Settings live in a JSON file (see ``examples/settings.example.json``). Every key is optional;
anything missing falls back to the defaults below. Relative paths in the file are resolved
against the folder that contains the settings file (or the current directory when no file is used).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_WEIGHTS: dict[str, float] = {
    "fit": 5,
    "freshness": 20,
    "competition": 20,
    "keywords": 10,
    "serious_flag_penalty": 6,
}

DEFAULT_RESUMES: dict[str, str] = {
    "Product": "Resume_Product",
    "Project_Delivery": "Resume_Project_Delivery",
}

DEFAULT_RESUME_BY_ROLE_TYPE: dict[str, str] = {
    "Product Manager": "Product",
    "Product Owner": "Product",
    "Project Manager": "Project_Delivery",
    "Delivery Manager": "Project_Delivery",
}

DEFAULT_RECRUITER_PATTERNS: list[str] = [
    "(for ",
    "undisclosed",
    "confidential",
    "recruiter post",
    "end client",
]

# Dropdown lists that may be overridden with the "lists" key.
LIST_NAMES = ("Role Type", "Source", "Work Mode", "Visa / Sponsorship", "Status", "Response Type")

_INT_KEYS = {
    "fresh_days": 2,
    "window_days": 7,
    "max_applicants": 500,
    "follow_up_days": 7,
    "top_n": 10,
    "reapply_cooldown_days": 90,
    "flag_experience_years": 6,
}
_PATH_KEYS = ("tracker_path", "logs_dir", "resume_dir", "standard_answers_path")
_OTHER_KEYS = (
    "priority_weights",
    "resumes",
    "resume_by_role_type",
    "default_resume_version",
    "recruiter_patterns",
    "lists",
    "criteria",
)
KNOWN_KEYS = frozenset(_INT_KEYS) | frozenset(_PATH_KEYS) | frozenset(_OTHER_KEYS)


class ConfigError(ValueError):
    """Raised when a settings file is missing, unreadable or invalid."""


@dataclass
class Settings:
    """All tunable rules and paths. Defaults reproduce the original prototype's behaviour.

    Ages are whole calendar days (today minus "Date Posted"), not hours:
    - ``fresh_days`` (2): a job posted today or within the previous 2 calendar days is kept whatever
      its applicant count. This is what "48 hours" means in the product brief.
    - ``window_days`` (7): a job posted up to 7 calendar days ago is kept only with a confirmed
      applicant count of ``max_applicants`` (500) or fewer. Older jobs are dropped.
    """

    fresh_days: int = 2
    window_days: int = 7
    max_applicants: int = 500
    follow_up_days: int = 7
    top_n: int = 10
    reapply_cooldown_days: int = 90
    flag_experience_years: int = 6
    priority_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    resumes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_RESUMES))
    resume_by_role_type: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_RESUME_BY_ROLE_TYPE))
    default_resume_version: str = "Project_Delivery"
    recruiter_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_RECRUITER_PATTERNS))
    lists: dict[str, list[str]] = field(default_factory=dict)
    criteria: dict[str, str] = field(default_factory=dict)
    base_dir: Path = field(default_factory=Path.cwd)
    tracker_path: Path = Path("Job_Search_Tracker.xlsx")
    logs_dir: Path = Path("logs")
    resume_dir: Path = Path("resumes")
    standard_answers_path: Path | None = None

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        for key in _PATH_KEYS:
            value = getattr(self, key)
            if value is not None:
                p = Path(value).expanduser()
                setattr(self, key, p if p.is_absolute() else self.base_dir / p)

    @property
    def backups_dir(self) -> Path:
        """Backups are written next to the tracker."""
        return self.tracker_path.parent / "backups"

    def resume_for_role(self, role_type: str | None) -> str:
        """Resume version to use for a role type when the agent did not choose one."""
        return self.resume_by_role_type.get(role_type or "", self.default_resume_version)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable view (paths relative to base_dir where possible)."""
        out: dict[str, Any] = {k: getattr(self, k) for k in _INT_KEYS}
        for key in _OTHER_KEYS:
            out[key] = getattr(self, key)
        for key in _PATH_KEYS:
            value = getattr(self, key)
            if value is None:
                out[key] = None
                continue
            try:
                out[key] = Path(value).relative_to(self.base_dir).as_posix()
            except ValueError:
                out[key] = str(value)
        return out


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ConfigError(message)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(data: dict[str, Any]) -> None:
    """Raise ConfigError if ``data`` (a parsed settings dict) is invalid."""
    _require(isinstance(data, dict), "settings must be a JSON object")
    unknown = sorted(k for k in data if k not in KNOWN_KEYS and not str(k).startswith(("_", "$")))
    _require(not unknown, f"unknown setting(s): {', '.join(unknown)}")

    for key in _INT_KEYS:
        if key in data:
            _require(_is_int(data[key]) and data[key] >= 0, f"'{key}' must be a whole number >= 0")
    fresh = data.get("fresh_days", _INT_KEYS["fresh_days"])
    window = data.get("window_days", _INT_KEYS["window_days"])
    _require(window >= 1, "'window_days' must be at least 1")
    _require(fresh <= window, "'fresh_days' cannot be larger than 'window_days'")

    weights = data.get("priority_weights", {})
    _require(isinstance(weights, dict), "'priority_weights' must be an object")
    bad = sorted(set(weights) - set(DEFAULT_WEIGHTS))
    _require(not bad, f"unknown priority weight(s): {', '.join(bad)}")
    for k, v in weights.items():
        _require(_is_number(v) and v >= 0, f"priority weight '{k}' must be a number >= 0")

    resumes = data.get("resumes", DEFAULT_RESUMES)
    _require(isinstance(resumes, dict) and resumes, "'resumes' must be a non-empty object")
    for k, v in resumes.items():
        _require(isinstance(v, str) and v.strip() != "", f"resume '{k}' must be a non-empty file name")
    default_version = data.get("default_resume_version", "Project_Delivery")
    _require(default_version in resumes, f"'default_resume_version' ({default_version!r}) is not in 'resumes'")
    by_role = data.get("resume_by_role_type", DEFAULT_RESUME_BY_ROLE_TYPE)
    _require(isinstance(by_role, dict), "'resume_by_role_type' must be an object")
    for role, version in by_role.items():
        _require(version in resumes, f"'resume_by_role_type' maps {role!r} to unknown resume {version!r}")

    patterns = data.get("recruiter_patterns", [])
    _require(isinstance(patterns, list) and all(isinstance(p, str) and p for p in patterns),
             "'recruiter_patterns' must be a list of non-empty strings")

    lists = data.get("lists", {})
    _require(isinstance(lists, dict), "'lists' must be an object")
    for name, items in lists.items():
        _require(name in LIST_NAMES, f"unknown list {name!r}; allowed: {', '.join(LIST_NAMES)}")
        _require(isinstance(items, list) and items and all(isinstance(i, str) and i for i in items),
                 f"list {name!r} must be a non-empty list of strings")
        _require(all("," not in i for i in items), f"list {name!r}: items cannot contain commas")

    criteria = data.get("criteria", {})
    _require(isinstance(criteria, dict) and all(isinstance(v, str) for v in criteria.values()),
             "'criteria' must be an object of text values")

    for key in _PATH_KEYS:
        if key in data and data[key] is not None:
            _require(isinstance(data[key], str) and data[key].strip() != "", f"'{key}' must be a path string")


def from_dict(data: dict[str, Any], base_dir: Path | None = None) -> Settings:
    """Validate ``data`` and build Settings, filling gaps with defaults."""
    validate(data)
    kwargs: dict[str, Any] = {k: v for k, v in data.items() if k in KNOWN_KEYS}
    kwargs["priority_weights"] = {**DEFAULT_WEIGHTS, **data.get("priority_weights", {})}
    return Settings(base_dir=base_dir or Path.cwd(), **kwargs)


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from a JSON file, or return defaults when ``path`` is None."""
    if path is None:
        return Settings()
    p = Path(path).expanduser()
    if not p.is_file():
        raise ConfigError(f"settings file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{p} is not valid JSON: {exc}") from exc
    return from_dict(data, base_dir=p.resolve().parent)
