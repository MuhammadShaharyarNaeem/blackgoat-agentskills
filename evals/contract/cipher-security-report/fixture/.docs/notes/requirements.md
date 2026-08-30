# Requirements — notes

## Functional Requirements

### FR-1 — A caller reads their own notes (Must-Have)
**Given** an authenticated caller
**When** they list notes
**Then** only their own notes are returned with status `200`.

### FR-2 — A caller creates a note (Must-Have)
**Given** an authenticated caller
**When** they create a note with non-empty text
**Then** the service returns `201` with the new note's `id`.

## Non-Functional Requirements

### NFR-1 — Requests without a valid token are refused (Must-Have)
Any request without a validly signed bearer token receives `401` and no data.

### NFR-2 — The service is safe for public deployment (Must-Have)
The service passes the squad's pre-launch security audit: no hardcoded secrets,
boundaries configured for production exposure.
