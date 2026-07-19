# Demo — Test Report

#Task [1]:

- FR-1: PASS — auth flow verified (test_login_success)
- NFR-1: PASS — login endpoint responded in 180ms (test_login_performance)

#Task [2]:

- FR-2: FAIL — logout did not clear the session cookie (test_logout_clears_session)

Retest after fix:

- FR-2: PASS — logout clears the session cookie (test_logout_clears_session)
