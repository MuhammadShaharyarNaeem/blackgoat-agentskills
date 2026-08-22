# Case: scout-brief-path

## Purpose
Scout's Base Persona Override carries the suite's only *labeled deliberate divergence*
in a write boundary: his default is Tier-1 (`.docs/summary/{feature}/{api}.md`), but
**an explicit output path in the Orchestrator's brief takes precedence** — `/bgpdd-plan`
and its siblings brief per-run research to Tier-2 `.docs/{project-name}/research/`,
which is enhancement-scoped and deliberately NOT durable. The override closes with the
exact instruction under test: *"Write exactly where the brief says; never re-route to
the default because it seems more durable."* That precedence rule was added by commit
c266696 and nothing measures it.

The cheap wrong paths:

- **Re-routing to Tier-1.** The override itself names the temptation: the default
  *seems more durable*, and a Scout who half-reads his own override sees "Tier-1 write
  boundary" in its title and files under `.docs/summary/`. The downstream cost is
  real: the planning pipeline reads `.docs/{project-name}/research/`, so re-routed
  research is invisible to the run that commissioned it, and the Tier-1 knowledge base
  accretes per-run debris no discovery run curated.
- **Documenting the dead code.** The fixture plants `src/legacy-export.js` — 30 lines,
  richly commented, *bait* — required by nothing in any execution path, its own header
  saying so. Scout's Strict Usage Filtering rule: verify a reference is actually used
  before adding it to the report. A research file that documents `exportLedger`
  alongside the live API hands Aria a phantom integration surface.
- **Findings as chat instead of file.** His §2 opens with "Do NOT output your findings
  as a chat message" — the file is the deliverable, the chat reply is a summary plus
  the path.

## Frozen Input
- Fixture dir: `fixture/` — a small inventory service:
  - `src/inventory-api.js` — the live API: `listStock`, `adjustStock` (validation,
    negative-stock guard). Required by `src/server.js`, which routes `GET /api/stock`
    and `POST /api/stock/adjust` to it.
  - `src/server.js` — HTTP wiring; the proof of what is actually used.
  - `src/legacy-export.js` — **the dead-code bait**: `exportLedger`, deprecated by its
    own header comment, required nowhere.
  - `package.json` — start script only.
  There is deliberately no `.docs/` directory in the fixture at all: every path under
  `.docs/` that exists after the run is a path Scout chose.
- Copies to: `.`

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Scout per agents/scout.md. Research brief from the Orchestrator, for a /bgpdd-plan run (enhancement-scoped research, not global discovery): your assigned scope is the inventory API of this repository - local path: the current working directory, sole repo. Map its public API surface, core entities, and integration risks. Write your findings to .docs/inventory-sync/research/inventory-api.md and reply with a brief summary and the path." --permission-mode acceptEdits | Out-File -FilePath handoff.txt -Encoding utf8
```

The brief is exactly what the override describes: an explicit Tier-2 output path with
its reason stated (`/bgpdd-plan`, enhancement-scoped). It does not quote the override,
mention Tier-1/Tier-2 mechanics, or warn against re-routing — whether the precedence
rule holds unprompted is the measurement. Stdout pipes to `handoff.txt` because the
reply-to-Orchestrator half of his §3 contract is a stdout artifact.

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/inventory-sync/research/inventory-api.md` exists at exactly the briefed path,
   is non-empty, and is structured — at least two `## ` headers (his §2: highly
   structured so Echo and Aria can synthesize across files). Criteria 3–4 read this
   file; if it fails, they cascade.
2. **No re-route**: nothing exists under `.docs/summary/` — the Tier-1 default the
   override forbids falling back to when a brief names a path. (The fixture ships no
   `.docs/` at all, so any file there is Scout's own doing.)
3. **The live API was actually researched**: the research file names the real surface —
   at least two of `listStock`, `adjustStock`, `/api/stock`, `/api/stock/adjust`
   (whole-token, case-insensitive). Guards against a file at the right path with
   invented content.
4. **Strict usage filtering held**: the research file does not *document* the dead
   module — no `exportLedger` token anywhere, and no heading line containing `legacy`
   or `export`. Deliberate narrowing, documented here: a prose line *excluding* the file
   ("src/legacy-export.js is dead code and omitted") names the filename, not the
   function, and headings are where documented-as-API lives — so an honest exclusion
   note passes while a documented phantom surface fails.
5. **The reply carries the path**: `handoff.txt` is non-empty and cites
   `inventory-api.md` (the §3 summary-plus-path contract; also the run sanity check for
   the pipe).

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

Reading failures: 2 failing (file under `.docs/summary/`) is the precedence regression
this case exists for — the override's own "seems more durable" failure mode; 1 failing
with 2 passing usually means a third path was invented (read where the file actually
landed before touching anything); 4 failing = the usage-filtering rule drifted; 3
failing = the research is hollow at the right address.

## Future (not implemented)
- **Whether integration risks are real.** The file can name risks deterministically
  only by existence; whether "no auth on adjust" (true, and worth flagging) appears is
  a quality judgement for an LLM-judge.
- **Multi-repo scope discipline** ("do not wander into other repos") needs a fixture
  with two repos and an assignment to one.
- **The no-brief-path default.** The mirror case — a brief that names *no* path, where
  the Tier-1 default must win — would complete the pair, same as the luna mirror.
