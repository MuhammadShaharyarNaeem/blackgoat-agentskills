# Reporting — Implementation Plan

## Task 1: Export generation service

**Requirements covered:** FR-1

**Boundary contracts:** provides: export.artifact

Builds the export file from a saved report and stores it in object storage.

## Task 2: Signed download link delivery (supersedes scheduled email per D-3)

**Requirements covered:** FR-2, NFR-1

**Boundary contracts:** consumes: export.artifact; provides: export.download-link

Issues a short-lived signed link for a completed export and surfaces it to the
requesting analyst. Link lifetime is 15 minutes.
