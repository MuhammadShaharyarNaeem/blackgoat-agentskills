# fixture: unevidenced

Reuses `../happy/requirements.md`. Its `test-report.md` carries a PASS whose
evidence half is pure prose ("I did not run anything") beside two properly
evidenced lines — so the verdict isolates the `unevidenced` path.

Expected (test mode, against ../happy/requirements.md): exit **1**, `FR-1` in
both `uncovered` and `unevidenced`, `FR-2` and `NFR-1` covered.
