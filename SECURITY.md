# Security policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private vulnerability reporting
("Security" tab, "Report a vulnerability") on this repository. Include steps to reproduce,
the affected version and the impact. We aim to reply within 7 days.

Never include real personal data (yours or anyone else's) in a report; use fictional examples.

## Threat model in brief

Shortlist processes text copied from public job pages by an AI agent. The main risks are:

| Risk | Mitigation |
|---|---|
| Prompt injection: a job page tells the AI to do something ("ignore previous instructions", "send the resume to ...") | Prompts state that page content is data only; `safety.sanitize_text` flags and redacts instruction-like text; flagged jobs get a `Suspicious page text` flag and lower priority. |
| Hidden content (HTML comments, zero-width characters, direction overrides) | Stripped before storage; instructions hidden in removed HTML are still reported. |
| Malicious links (`javascript:`, `data:`, `file:`, embedded credentials) | Rejected by `safety.validate_url`; only http(s) links become hyperlinks. |
| Spreadsheet formula injection (`=`, `+`, `-`, `@`) | Such text is written as text cells with a quote prefix. |
| Agents inflating scores or statuses | Computed columns from agents are ignored; agents can only set Found or Shortlisted. |
| Leaking personal data | No network code; all data local; tracker, profile, resumes, logs and settings are git-ignored; `gitleaks` runs as a pre-commit hook. |
| Unwanted actions on job sites | The package cannot act on the web; prompts and the skill forbid logging in, applying, submitting and sending. |

The injection filter is heuristic. It reduces risk but cannot guarantee detection, so a human
must review every job and letter before acting on it.
