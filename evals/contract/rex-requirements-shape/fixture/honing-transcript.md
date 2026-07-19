# Honing Transcript — CSV Export

**Q:** Who initiates the export — any logged-in user, or only certain roles?
**A:** Any logged-in user viewing a report they already have access to. No special role
needed.

**Q:** What's actually in the exported file — the same columns shown on screen, or a
different set?
**A:** Same columns as the on-screen table, in the same order, plus the report's date
range in a header row.

**Q:** What happens when the report has zero rows (empty result set)?
**A:** Still download a valid CSV with just the header row — don't error out.

**Q:** What happens when the report has an enormous number of rows — is there a cap?
**A:** Cap at 50,000 rows for this version. Above that, show an error asking the user to
narrow the date range. A background export with an emailed download link is a "should
have" for a later version, not this one.

**Q:** Any special characters we need to worry about in cell values?
**A:** Yes — report names and notes can contain commas, quotes, and newlines entered by
users. They must be properly CSV-escaped so Excel doesn't mangle them.

**Q:** Does this need to be logged anywhere for compliance?
**A:** Yes — log who exported what report and when. Same audit requirement as our other
data-export features.

**Q:** Performance expectations?
**A:** Exporting a 50,000-row report should complete within 5 seconds.

**Q:** Anything explicitly out of scope?
**A:** Scheduled/recurring exports and exporting to formats other than CSV (e.g. PDF,
XLSX) are out of scope for this version.
