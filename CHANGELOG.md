# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/)
and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-29

First public release of the command line tool, refactored from a personal prototype.

### Added
- `shortlist` CLI: `init`, `normalize`, `add`, `update`, `applied`, `dashboard`, `top`, `prune`,
  `rebuild`, `test-rules`, `check-letters`, `scan`.
- Rules engine: calendar-day freshness rule with a confirmed applicant limit, conservative
  applicant-count parsing (including "1.2K"), company + title duplicate detection, reapply cooldown.
- Transparent 0-100 priority score and automatic flags; weights in `settings.json`.
- Excel tracker with Dashboard, Tracker, Metrics, Criteria (generated from settings) and optional
  Standard Answers (from your own file) tabs; backups before destructive operations.
- `safety` module: sanitising of untrusted page text, prompt-injection flagging and redaction,
  URL validation.
- Cover letter checks (length, dashes, placeholders, "Never say" phrases).
- Generic prompt templates for search and cover letter agents with an untrusted-data section.
- Fictional examples, tests, CI (ruff + pytest on Python 3.10-3.12), pre-commit (ruff, gitleaks).

### Fixed (compared with the prototype)
- "1.2K applicants" was read as 1.
- Future posting dates counted as fresh; they are now dropped.
- Text starting with `=`, `+`, `-` or `@` could become a spreadsheet formula.
- Non-http links could become clickable hyperlinks.
- "Associate Director" and similar titles were flagged as junior.
- The word "safe" triggered the SAFe certification flag.
- Keyword match found words inside other words ("agile" in "fragile").
- `applied` matched substrings of company names ("ola" in "Motorola").
