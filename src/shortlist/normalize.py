"""Turn a search agent's raw JSON into tracker rows and enforce the freshness rule.

Every text field is treated as untrusted: it is sanitised (HTML, hidden characters, length) and
scanned for instruction-like text, which is redacted and flagged. Jobs with an invalid link or
that fail the freshness rule are dropped and logged with a reason.

Outputs:
    <dest>                               kept jobs, ready for ``shortlist add``
    <logs_dir>/rejected_<raw stem>.json  dropped jobs with the reason
    <logs_dir>/safety_<raw stem>.json    sanitiser warnings (only if any)
    <logs_dir>/runs.csv                  one line per run: date, file, found, kept, dropped
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .config import Settings
from .rules import passes
from .safety import is_injection_warning, sanitize_text, validate_url
from .scoring import SAFETY_MARKER

# Fields the agent returns that are folded into Notes rather than kept as columns.
FOLDED_FIELDS = ("Key Requirements", "Date Source", "Visa Evidence")
# Fields the tracker computes itself; values supplied by an agent are ignored.
COMPUTED_FIELDS = ("ID", "Days Old", "Priority", "Keyword Match", "Flags", "Follow-up Date")
# Statuses an agent may set; anything else becomes "Found".
AGENT_STATUSES = ("Found", "Shortlisted")
FIELD_MAX_LENGTH = 2000


class RawJobsError(ValueError):
    """Raised when the raw agent output cannot be read as a JSON array of jobs."""


@dataclass
class NormalizeResult:
    """Outcome of normalising one batch of raw jobs."""

    kept: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def found(self) -> int:
        return len(self.kept) + len(self.dropped)


def load_raw_jobs(path: str | Path) -> list[Any]:
    """Read a JSON array from ``path``.

    Agents sometimes wrap the array in prose ("Here are the jobs: [...] Rejected: ..."), so if the
    whole file is not valid JSON, the first JSON array in it is used.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        if start < 0:
            raise RawJobsError(f"{path}: no JSON array found") from None
        try:
            data, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            raise RawJobsError(f"{path}: could not parse the JSON array ({exc})") from exc
    if not isinstance(data, list):
        raise RawJobsError(f"{path}: expected a JSON array of jobs, got {type(data).__name__}")
    return data


def _clean_fields(job: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Sanitise every string value. Returns (clean_job, warnings, fields_with_injections)."""
    clean: dict[str, Any] = {}
    warnings: list[str] = []
    injected: list[str] = []
    for key, value in job.items():
        name, _ = sanitize_text(key, max_length=100)
        if not name:
            continue
        if isinstance(value, str) and name != "Job URL":
            text, w = sanitize_text(value, max_length=FIELD_MAX_LENGTH, redact=True)
            if w:
                warnings.extend(f"{name}: {x}" for x in w)
            if is_injection_warning(w):
                injected.append(name)
            clean[name] = text
        elif isinstance(value, (int, float, bool)) or value is None or name == "Job URL":
            clean[name] = value
        else:
            # Nested structures are not expected from the agent; keep a flattened, sanitised copy.
            text, w = sanitize_text(json.dumps(value, ensure_ascii=False), max_length=FIELD_MAX_LENGTH, redact=True)
            warnings.extend(f"{name}: {x}" for x in w)
            if is_injection_warning(w):
                injected.append(name)
            clean[name] = text
    return clean, warnings, injected


def _match_score(value: Any) -> int | None:
    try:
        score = round(float(value))
    except (TypeError, ValueError):
        return None
    return score if 1 <= score <= 10 else None


def normalize_job(job: dict[str, Any], today: date, settings: Settings | None = None,
                  injected: list[str] | None = None) -> dict[str, Any]:
    """Map one (already sanitised) raw job to tracker columns."""
    s = settings or Settings()
    out = {k: v for k, v in job.items() if k not in FOLDED_FIELDS and k not in COMPUTED_FIELDS}
    out["Date Found"] = today.isoformat()
    applicants = re.sub(r"\s*applicants?$", "", str(job.get("Applicants") or "").strip(), flags=re.I)
    out["Applicants"] = applicants or "Not shown"
    if not out.get("Resume Version"):
        out["Resume Version"] = s.resume_for_role(job.get("Role Type"))
    if out.get("Status") not in AGENT_STATUSES:
        out["Status"] = "Found"
    score = _match_score(job.get("Match Score (1-10)"))
    if score is None:
        out.pop("Match Score (1-10)", None)
    else:
        out["Match Score (1-10)"] = score
    notes = [
        n
        for n in (
            job.get("Notes"),
            job.get("Visa Evidence") and f"Visa: {job['Visa Evidence']}",
            job.get("Key Requirements") and f"Key: {job['Key Requirements']}",
        )
        if n
    ]
    if notes:
        out["Notes"] = " | ".join(str(n) for n in notes)
    if injected:
        marker = f"{SAFETY_MARKER} instruction-like text removed from {', '.join(injected)}; check the page yourself"
        out["Red Flags"] = f"{out['Red Flags']}; {marker}" if out.get("Red Flags") else marker
    return out


def normalize_jobs(raw_jobs: list[Any], today: date, settings: Settings | None = None) -> NormalizeResult:
    """Sanitise, validate and filter raw jobs (no file I/O)."""
    s = settings or Settings()
    result = NormalizeResult()
    for i, raw in enumerate(raw_jobs):
        if not isinstance(raw, dict):
            result.dropped.append({"Index": i, "Reason": "not a JSON object"})
            continue
        job, warnings, injected = _clean_fields(raw)
        label = {"Company": job.get("Company"), "Role Title": job.get("Role Title"), "Job URL": job.get("Job URL")}
        if warnings:
            result.warnings.append({**label, "Warnings": warnings})
        ok_url, url_reason = validate_url(job.get("Job URL"))
        if not ok_url:
            result.dropped.append({**label, "Date Posted": job.get("Date Posted"),
                                   "Applicants": job.get("Applicants"), "Reason": f"invalid link: {url_reason}"})
            continue
        if not job.get("Company") or not job.get("Role Title"):
            result.dropped.append({**label, "Reason": "missing company or role title"})
            continue
        ok, _age, reason = passes(job, today, s)
        if not ok:
            result.dropped.append({**label, "Date Posted": job.get("Date Posted"),
                                   "Applicants": job.get("Applicants"), "Reason": reason})
            continue
        result.kept.append(normalize_job(job, today, s, injected))
    return result


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def normalize_file(raw_path: str | Path, dest_path: str | Path, today: date | None = None,
                   settings: Settings | None = None) -> NormalizeResult:
    """Normalise ``raw_path`` into ``dest_path`` and write the logs. Returns the result."""
    s = settings or Settings()
    today = today or date.today()
    raw_path, dest_path = Path(raw_path), Path(dest_path)
    result = normalize_jobs(load_raw_jobs(raw_path), today, s)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(dest_path, result.kept)
    s.logs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(s.logs_dir / f"rejected_{raw_path.stem}.json", result.dropped)
    if result.warnings:
        _write_json(s.logs_dir / f"safety_{raw_path.stem}.json", result.warnings)
    log = s.logs_dir / "runs.csv"
    new_file = not log.exists()
    with log.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["run_date", "source_file", "found", "kept", "dropped"])
        writer.writerow([today.isoformat(), raw_path.name, result.found, len(result.kept), len(result.dropped)])
    return result
