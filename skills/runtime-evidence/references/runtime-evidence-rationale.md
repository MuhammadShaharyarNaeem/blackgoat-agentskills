# Runtime Evidence — Rationale and Worked Examples

Load on demand. The operational contract is in [`../SKILL.md`](../SKILL.md); nothing here overrides it.

## 1. Why the in-process tier is the most dangerous false pass

Ranked by how convincing a wrong answer looks:

| Evidence | Why a wrong answer is caught | Why it is missed |
|---|---|---|
| "I read the code" | Obviously not an observation. Reviewers challenge it reflexively. | — |
| "The types line up" | Visibly a proxy. | Occasionally accepted under time pressure |
| **A green in-process suite** | — | **Nothing about it looks wrong.** Real handlers ran. Real queries executed. Real assertions passed. The transcript is indistinguishable from a genuine verification |
| An out-of-process capture | — | Only the stale-process hazard (§3) |

The middle rows fail loudly. The third row fails silently, and it fails silently *while producing a document that reads as proof*. That asymmetry is the entire reason this tier exists as a separate contract with its own gate rather than as a bullet in a testing checklist.

A useful test when you are unsure which tier a claim needs: **ask what the requirement's subject is.** If the subject is a function ("the total is computed correctly"), Tier 1 or 2 owns it. If the subject is something a client, device, or person *receives* ("the response carries the envelope", "the tick appears", "the agent is installed"), only Tier 3 can pass it. The grammatical subject of the requirement names the tier.

## 2. The 2026-08 response-envelope incident, traced

**What happened.** A milestone added a standard response envelope to a public API gateway. Every gate passed. A developer opened local Swagger, called the endpoint, and got a bare payload.

**Why every gate passed.** Each one was individually correct and collectively blind:

1. The stack contract mandated integration tests through an **in-process host client**. A comment in the contract's own example called this *"real HTTP"*. It is not: no socket, no server process, no host startup/config chain, no contract surface rendered. That one word taught every reader that the tier proved the wire.
2. The example assertion bound the response straight into the envelope type and asserted a member. Binding an **unwrapped** body into an envelope type throws nothing — no property matches, every member takes its default. The test does fail, but it fails *looking exactly like a logic bug*, and the cheapest way to make it green is to change the generic parameter to the bare payload type. That "fix" makes the test pass and leaves the API wrong.
3. The repo's cross-cutting rule — that a runtime exit criterion must exercise *"the built application as a user reaches it, started, driven, and the asserted effect read back"* — was in force and unenforced. No script read it, and it was never routed into the QA agent's brief.
4. The one-directional doctrine and its mechanical enforcer both existed, wired exclusively to the UI surface. The API surface had the doctrine's logic available and none of its wiring.
5. The QA agent's own strongest evidence rule — every pass carries the verbatim command and its captured output — was satisfied completely by a test-runner invocation. The rule constrains *honesty about a command*, never *which command*.

**The generalizable lesson.** Nobody lied and nobody was lazy. The failure was that the tier which could falsify the claim was never named as mandatory, so the tier which could not falsify it was allowed to stand in. Every gate downstream then inherited that substitution without any of them being wrong.

**A second, quieter lesson.** The consuming frontend's HTTP layer unwrapped responses without checking whether an envelope was present, so a missing envelope silently produced `undefined` for every caller rather than an error. The bug had no symptom until a human opened the contract surface by hand. When a client is tolerant, the absence of complaints is not evidence.

## 3. The stale-process hazard

Freshness is checked by comparing the capture file's mtime against the changed files' mtimes. That proves the capture was *written* after the edit. It does **not** prove the process that answered was running the edited code.

The failure shape: a service is started, the code is changed, the service is never restarted, the probe runs. The capture is fresh, non-empty, well-formed, names a real out-of-process transport, and reports the old behavior. Every mechanical check passes.

Mitigations, in descending strength:

1. **A build marker echoed by the running service** — a version, commit, or build id the service reports and the capture records. This is the only real closure, and it requires the service to expose one. Where a service does, gate on it.
2. **A launch log under `evidence/runtime/`, freshness-checked** — catches the ordinary case where the process was started before the edit. Misses a restart that happened between the edit and the probe, and misses hot-reload runtimes whose log never rotates.
3. **Restarting as a matter of routine** — cheap for a single service, expensive and easy to do partially in a multi-service estate, which is precisely where the hazard is worst.

State this openly in reports rather than assuming it away. A multi-service local environment where only some services were restarted is the most likely way a green Tier-3 capture is still wrong.

## 4. Why captures gate on freshness, not authorship

The gate cannot prove a human produced a capture rather than typing it. Neither can the rendered-evidence gate it is modeled on, which documents the same limit: it proves a cited file exists in the right place, not that anyone looked at it.

This is accepted deliberately. Mechanical gates raise the cost of a false claim; they do not make one impossible. What closes the remaining gap is not a cleverer parser but the surrounding obligations: captures are written by the capture tool rather than by hand, so the load-bearing fields are not agent-authored; the verbatim command and its output are required in the durable session record; and fabricating a capture requires composing a plausible response body, which is materially harder than writing the word "verified".

Chasing authorship proof mechanically leads somewhere worse — signed artifacts, hash chains, a gate that is harder to satisfy honestly than dishonestly. Freshness plus provenance plus content assertion is the point where the cost curve of honesty stays below the cost curve of faking.

## 5. Worked captures

### API surface — success and failure, both required

A wrapper can shape the success path and miss the failure path, because they typically travel different code (a result mapper versus an exception handler). One capture proves half a claim.

```markdown
# Runtime capture: POST /api/orders — success

- Milestone: M3 — Order envelope [API] [vs:api]
- Requirement IDs: FR-4
- Surface: api
- Transport: out-of-process HTTP (external client)
- Base URL: http://localhost:5142
- Build marker: 1.4.2+sha.9f2c1ab
- OpenAPI: http://localhost:5142/swagger/v1/swagger.json — 200
- Probe command: `<the milestone's declared probe>`
- Captured: <ISO-8601>
- Exit code: 0

## Captured output

HTTP/1.1 200 OK
content-type: application/json

{"statusCode":200,"isSuccess":true,"data":{...},"dataContext":null,"notifications":[]}
```

The failure sibling probes a deliberately invalid request and asserts the same envelope keys arrive with `notifications` populated. It doubles as the negative-half proof required by `test-driven-development`.

### Device / agent surface

The observable is machine state, not a response body. The capture records the query and its output the same way; only the transport and the assertion differ.

```markdown
# Runtime capture: Slide policy distribution — device state

- Milestone: M7 — Slide policy distribution [API] [vs:rmm]
- Requirement IDs: FR-11, FR-12
- Surface: rmm
- Transport: platform service/package query on the target device
- Device: <identifier>
- Environment: web=<local url>, crm=<local url>, asset=<local url>, integration=<local url>
- Config repointed: each service's config -> the local URLs above (was shared dev)
- Probe command: `<the milestone's declared probe>`
- Captured: <ISO-8601>
- Exit code: 0

## Captured output

<the query's verbatim output, showing the agent present and paired>
```

Two things this example is chosen to make concrete. First, the `Environment` block is doing real work: with several services repointed, a capture taken while one of them still pointed at shared dev proves nothing about local, and nothing else in the artifact would reveal it. Second, the inverse matters more here than anywhere — an install that cannot be undone is a different defect from one that never installed, and only the uninstall probe distinguishes them.

### UI surface

The capture cites the screenshot or accessibility-tree read rather than embedding it, and the transport is the browser skill named in the transport table. Where a requirement spans surfaces — an indicator in the UI that reflects a database row that reflects a device state — each store named by the requirement gets its own read-back. Three assertions, not one assertion and two inferences.

## 6. Why environment facts are caller-supplied

The manifest exists because of an asymmetry in what a wrong answer costs. An agent that cannot find a start command has two moves: escalate, or infer. Inferring is nearly free at the moment of the decision and nearly always produces something plausible — `localhost:5000` for a .NET service, `:3000` for a Node one, the port in the `docker-compose.yml` that may or may not be the one this dev runs. The inferred value then flows into a capture header, where it is indistinguishable from a supplied one. Nobody downstream can tell which fields were known and which were guessed, so a reviewer's only signal that a capture probed the wrong system is that the body looks odd — and on a repointing mistake the body usually looks fine, because shared dev is a working system returning working answers.

The same asymmetry runs one level up, at the capability. An agent that discovers at capture time that it has no browser is standing at the worst possible moment to make an honest call: the code is written, the round is half-spent, and the only action that closes the task is a lower-tier substitution the Tier Ladder forbids. Moving that discovery to the start of the run converts the most expensive decision in the pipeline into a question asked before anyone has invested anything.

This is why the manifest is a **caller** artifact rather than a discovered one. Research into what the repo declares — compose files, launch profiles, `appsettings.*.json`, CI workflows — is legitimate and useful, but it produces candidates, not values. A human confirms which candidate is real, because only a human knows which of the three ports in the repo is the one their machine actually runs.

## 7. Worked example — a multi-service manifest

```markdown
# Environment Manifest — orders-mapping

## Services
| Service | Start command | Local base URL | Readiness check | Calls |
|---|---|---|---|---|
| orders-api | `dotnet run --project src/Orders.Api` | http://localhost:5101 | `GET /health` → 200 | inventory-api |
| inventory-api | `dotnet run --project src/Inventory.Api` | http://localhost:5102 | `GET /health` → 200 | — |
| web | `npm run dev -- --port 5173` | http://localhost:5173 | page title renders | orders-api |
| postgres | `docker compose up -d db` | localhost:55432 | `pg_isready` → exit 0 | — |

## Repointing map
| Config key | File / env var | Owning service | Ships as | Must be locally |
|---|---|---|---|---|
| `Inventory:BaseUrl` | `src/Orders.Api/appsettings.Development.json` | orders-api | https://inventory.dev.internal | http://localhost:5102 |
| `VITE_API_BASE` | `.env.local` | web | https://orders.dev.internal | http://localhost:5101 |
| `ConnectionStrings:Db` | user-secrets | orders-api | dev cluster | localhost:55432 |

## Forbidden hosts
`*.dev.internal`, `*.staging.example.com`

## Capabilities required
| Capability | Needed for | Confirmed by |
|---|---|---|
| Out-of-process HTTP client | `[vs:api]`, `[vs:web+api]` | one real request to a health endpoint |
| Browser automation | `[vs:ui]`, `[vs:web+api]` | one navigation + snapshot |
| psql client | `manual` steps asserting rows | one `SELECT 1` |
| Python 3 | every mechanical gate | `python --version` |

## Secrets
| Secret | Source |
|---|---|
| DB password | `dotnet user-secrets`, key `ConnectionStrings:Db` |
| Test user JWT | minted by `scripts/dev-token.ps1` |
```

Two properties make this manifest load-bearing rather than documentation. The **repointing map's "Ships as" column** is what lets a reviewer see that a capture reading `inventory.dev.internal` was probing the wrong estate — without it, the forbidden-hosts list is a rule with no stated baseline. And the **capability table's "Confirmed by" column** is what turns the preflight into an observation instead of an assertion: each row names the cheapest action that proves the capability exists, so "confirmed" means someone ran something.
