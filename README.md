# Shortlist

**An AI-assisted job search co-pilot that keeps you in control.** Shortlist filters job postings
with transparent rules, ranks them with an explainable score, and tracks your applications in a
local Excel workbook. Your AI agent (for example Claude Code) does the searching and drafting;
Shortlist does the deterministic parts: filtering, deduplication, scoring, tracking and safety checks.

**You always review and submit.** Shortlist never logs in to job sites, never applies, never sends
messages.

> Status: v0.1 (alpha). Command line only. Python 3.10+.

## Why

Job seekers lose hours to postings that are stale, reposted or already crowded, then apply late
with generic letters and never learn what works. Shortlist was built first as a personal system
and is now generic:

- apply early to fresh jobs, skip the crowded ones;
- see at a glance why each job ranks where it does;
- keep every claim in a cover letter traceable to one approved fact sheet;
- measure response rates by week, source, resume version and role.

## Principles

1. **Human in the loop.** Draft, never send. Suggest, never submit.
2. **Honesty by design.** Letters use only facts from your fact sheet. Gaps are named, not hidden.
3. **Transparent rules.** Every filter and score is explainable in one sentence.
4. **Respect job sites.** Public pages only, polite request rates, no login automation.
5. **Privacy first.** Everything stays on your computer. No telemetry, no accounts.
6. **Untrusted input stays untrusted.** Job pages are data, never instructions.

## Install

```bash
git clone https://github.com/<you>/shortlist.git
cd shortlist
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e .            # or: pip install -e ".[dev]" for tests and linting
shortlist --help
```

## Quick start (with the fictional example data)

```bash
mkdir my-search && cd my-search
cp ../examples/settings.example.json settings.json         # then edit it
shortlist init --answers ../examples/standard_answers.example.json
shortlist test-rules                                       # 19/19 checks passed
shortlist normalize ../examples/raw_jobs.example.json jobs_today.json --date 2026-09-29
shortlist add jobs_today.json
shortlist top                                              # today's shortlist by priority
shortlist applied "Bluebird"                               # after YOU applied
shortlist dashboard                                        # refresh the Dashboard tab
shortlist prune                                            # drop stale jobs (backs up first)
```

`normalize` keeps 4 of the 5 example jobs, drops the crowded 4-day-old one, and redacts and flags
the instruction-like text planted in another. Open `Job_Search_Tracker.xlsx` to see the result.

For real use:

1. Copy `examples/profile/fact_sheet.example.md` to `profile/fact_sheet.md` and write your own facts.
2. Put your resumes (`.docx`) in `resumes/` and name them in `settings.json` (`resumes`).
3. Ask your AI agent to search using `prompts/search.md`; save its JSON output as a raw file.
4. `shortlist normalize raw.json jobs.json` then `shortlist add jobs.json`.
5. Draft letters with `prompts/cover_letter.md`, check them with
   `shortlist check-letters letters/*.txt --fact-sheet profile/fact_sheet.md`, and edit them yourself.
6. Apply yourself, then `shortlist applied "<company or link>"`.

A packaged Claude Code skill that runs this whole loop lives in the `skill/` folder of the project.

## Commands

| Command | What it does |
|---|---|
| `init [--answers FILE] [--write-settings]` | Create the tracker (refuses to overwrite). |
| `normalize RAW OUT [--date D]` | Sanitise, validate and filter an agent's raw JSON; log rejects. |
| `add JSON...` | Append jobs, skipping duplicate links, duplicate company + title, and companies that rejected you recently. |
| `update JSON` | Set fields on existing rows, matched by `Job URL`. |
| `applied NAME... [--date D]` | Mark a job Applied. NAME is a company, the start of a word in "company role", or the exact link. Ambiguous names change nothing. |
| `dashboard` | Recompute priority and flags, rebuild the Dashboard tab. |
| `top [-n N] [--json]` | Print the top open jobs by priority. |
| `prune` | Remove stale, crowded or skipped jobs you have not acted on (backup first). |
| `rebuild JSON...` | Start a fresh tracker from JSON files (backup first). |
| `test-rules` | Run the built-in rule checks. |
| `check-letters FILES... [--fact-sheet F]` | Check letters: length, dashes, placeholders, "Never say" phrases. |
| `scan FILE` | Sanitise a saved page and report instruction-like text. |

Global options: `-s/--settings FILE` (default `$SHORTLIST_SETTINGS`, then `./settings.json`, then
built-in defaults) and `-t/--tracker FILE`.

## How the freshness rule works

Ages are **whole calendar days** (today's date minus the posting date), not hours.

| Posted | Kept? |
|---|---|
| Today or within the previous 2 calendar days (`fresh_days`) | Yes, whatever the applicant count |
| 3 to 7 calendar days ago (`window_days`) | Only with a specific applicant count of 500 or fewer (`max_applicants`) |
| More than 7 days ago, undated, or dated in the future | No |

"48 hours" in earlier write-ups means this calendar-day rule: a job posted two calendar days ago
may be up to about 71 hours old and is still "fresh".

Applicant counts are read conservatively. "Over 200", "200+", "More than 200", "Más de 200" and
"Not shown" are **unknown**, never a number. "Be among the first 25" counts as 25 and "1.2K" as 1,200.

## How priority works (0 to 100)

| Part | Points |
|---|---|
| Fit | Match Score (1-10) x 5, max 50 |
| Freshness | up to 20, falling in a straight line to 0 at 7 days |
| Competition | up to 20: 50 or fewer applicants 20, 100 or fewer 15, 200 or fewer 10, unknown 5, more 2 |
| Keyword match | up to 10: share of the job's key requirements whose words appear in the resume you will send |
| Serious flags | minus 6 each: possible repost, recruiter hiding the employer, rejected there recently, suspicious page text |

All weights are in `settings.json` (`priority_weights`). Other flags (US or night hours, junior
level, asks 6+ years, certification mentioned, visa unclear, check pay, already applied here) are
shown but do not change the score. The Criteria tab of the workbook states the rules in words.

## Safety model

- **No side effects on the web.** The package has no network code at all. The prompt templates
  forbid logging in, applying, submitting forms and sending messages.
- **Untrusted text.** Every field from an agent passes through `shortlist.safety.sanitize_text`:
  HTML, scripts and comments are stripped, zero-width and direction-control characters removed,
  whitespace collapsed, length capped, and instruction-like phrases (such as "ignore previous
  instructions", "send the resume to ...", "rate this 10/10", fake system messages) are redacted
  and flagged `Suspicious page text`. Instructions hidden in removed HTML are reported too.
- **Links.** Only `http(s)` links with a real hostname and no embedded credentials are accepted;
  `javascript:`, `data:` and `file:` links are rejected and never made clickable.
- **Spreadsheet injection.** Text starting with `=`, `+`, `-` or `@` is stored as text, never as
  a formula.
- **Agents cannot set scores.** Priority, flags and computed columns supplied by an agent are ignored;
  agents can only set status Found or Shortlisted.
- **Local data.** Your tracker, fact sheet, resumes, logs and settings are git-ignored by default.

The injection filter is a heuristic. It lowers risk but cannot catch everything, so the prompts
also tell agents to treat page content as data only. See [SECURITY.md](SECURITY.md).

## Limitations

- Searching and letter drafting depend on your AI agent; Shortlist only checks and tracks.
- Applicant counts and posting dates are only as good as what job pages show.
- Keyword match is a simple word overlap, not semantic matching; it needs `.docx` resumes.
- The tracker holds up to 999 jobs; prune regularly.
- Excel formulas (Days Old, Metrics) are computed when the file is opened in a spreadsheet app.
- Pure Python with no OS-specific code; developed on Windows, CI runs on Linux with Python 3.10 to 3.12.

## Roadmap

- v0.1 (this release): CLI, rules engine, scoring, tracker, safety checks, prompt templates.
- v0.2: Claude Code skill that runs search, letters and tracker updates with your profile.
- v1.0: hosted web app for non-technical users (onboarding, daily shortlist, letters, metrics).

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and our
[Code of Conduct](CODE_OF_CONDUCT.md). Never include real personal data in issues, tests or examples.

## Licence

MIT. See [LICENSE](LICENSE).
