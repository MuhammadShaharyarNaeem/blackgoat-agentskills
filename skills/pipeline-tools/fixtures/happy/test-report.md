# Demo — Test Report

#Task [1]:

- FR-1: PASS — `pytest tests/auth` — exit 0 — tests/auth/test_login.py::test_login_success
- NFR-1: PASS — `pytest tests/auth` — exit 0 — tests/auth/test_login.py::test_login_performance (180ms)

#Task [2]:

- FR-2: FAIL — logout did not clear the session cookie (tests/auth/test_logout.py::test_logout_clears_session)

Retest after fix:

- FR-2: PASS — `pytest tests/auth` — exit 0 — tests/auth/test_logout.py::test_logout_clears_session
