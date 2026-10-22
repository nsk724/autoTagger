# B3.5 security gate demo

Run on 2026-10-22 on throwaway branch `b/b3-security-demo` (deleted afterwards, never merged).
Each bad commit was checked with the exact command of its Jenkins stage, then reverted.

| # | Bad commit | Stage / command | Result |
|---|---|---|---|
| 1 | `leak-demo.txt` with a fake AWS key (`AKIA` + 16 base32 chars) | Secrets scan: `gitleaks git --redact --no-banner .` | **fails**: `leaks found: 1`, exit 1 |
| 2 | f-string SQL in `services/backend-api/app/db.py` | SAST: `bandit -r services ml scripts -x "*/tests/*" -ll -ii` | **fails**: `B608:hardcoded_sql_expressions` at `db.py:61`, exit 1 |
| 3 | `requests==2.19.0` in `services/backend-api/requirements.txt` | Dependency audit: `pip-audit -r ...` | **pending**: PyPI timed out from this network; re-run when connected |

Note for #1: real AWS key IDs use only `A-Z` and `2-7` after the prefix. A key containing `8`, `9`,
`0` or `1` does not match gitleaks' `aws-access-token` rule, so a "fake" key must use the base32
alphabet to prove the gate.

Jenkins screenshots of the three red builds are still to be taken once Jenkins builds from GitHub.
