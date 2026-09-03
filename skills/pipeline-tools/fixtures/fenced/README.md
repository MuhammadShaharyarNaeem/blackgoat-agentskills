# fixture: fenced

Reuses `../happy/requirements.md`. Its `test-report.md` records an honest
`FR-2: FAIL`, then quotes the ledger grammar in a fenced block whose example
line reads `- FR-2: PASS — exit 0`. Latest mention wins, so before fences were
stripped the pasted example overwrote the real failure.

Expected (test mode, against ../happy/requirements.md): exit **1**, `FR-2` in
`uncovered`.
