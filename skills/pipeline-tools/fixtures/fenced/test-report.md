# Demo — Test Report

#Task [1]:

- FR-1: PASS — `pytest tests/auth` — exit 0 — tests/auth/test_login.py::test_login_success
- NFR-1: PASS — `pytest tests/auth` — exit 0 — tests/auth/test_login.py::test_login_performance

#Task [2]:

- FR-2: FAIL — logout leaves the session cookie set (tests/auth/test_logout.py::test_logout_clears_session)

The Coverage Ledger grammar, for reference:

```
- FR-2: PASS — exit 0 — tests/auth/test_logout.py::test_logout_clears_session
```
