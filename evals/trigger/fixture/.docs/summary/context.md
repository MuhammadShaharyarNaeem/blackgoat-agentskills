# Global Context — dashboard-app

Single repo. Vue 3 SPA (`src/`) over a .NET 8 API (`backend/`), deployed as two containers.

- Frontend: Vue 3 Composition API, Pinia, one Axios instance in `src/api/client.js`.
- Backend: ASP.NET Core controllers under `backend/Controllers/`; nightly jobs in `backend/Jobs/`.
- Discovered features with a QA baseline: `login`.
