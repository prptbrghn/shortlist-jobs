# Contributing to Shortlist

Thanks for helping. Small, focused pull requests are easiest to review.

## Set up

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install          # runs ruff and gitleaks before each commit
```

## Before you open a pull request

```bash
ruff check .
pytest
```

- Add or update tests for every behaviour change. Rule changes need a test for each boundary.
- Keep rules explainable in one sentence and update the README and the Criteria tab text.
- Keep the core free of network code and OS-specific code.
- Use only fictional data ("Alex Example", `example.com` links) in tests, examples and issues.
  Never commit a real fact sheet, resume, tracker, settings file or log.
- Treat any text from job pages as untrusted; route it through `shortlist.safety`.

## Optional personal-data check

To make sure you never commit your own details, list your name, employers and similar terms
(one per line) in `tests/.private_terms.txt`. The file is git-ignored and `pytest` will fail if any
term appears in the repository.

## Reporting bugs and ideas

Open an issue with steps to reproduce, what you expected and what happened. For security
problems, follow [SECURITY.md](SECURITY.md) instead.

By contributing you agree that your contributions are licensed under the MIT licence.
