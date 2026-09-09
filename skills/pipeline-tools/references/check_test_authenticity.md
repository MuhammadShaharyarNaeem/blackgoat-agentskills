# check_test_authenticity.py — reference

Depth for the `check_test_authenticity.py` section of `../SKILL.md`.

## Why RED/GREEN cannot catch a fake test

Every other test gate in this family verifies a **transition**:

- `check_red_green.py` verifies that the SAME command failed before the fix and passed after it, token-list compared under three tokenizations so a substituted command cannot pass for the declared one.
- `check_runtime_evidence.py` verifies that a capture on disk hashes to its provenance sidecar, so the recorded run is the run that happened.
- `check_quick_close.py` verifies that the declared check ran AFTER the edit and that no test was quietly edited into agreement.

A fake test satisfies every one of them perfectly, and that is the whole problem. Take the shape this gate was built from: a spec that opens with

```ts
export function getBackupItemStatus(backup: any): string { /* 20 statements */ }
```

and then asserts against it. Before the function is written the spec is red. After it is written the spec is green. The transition is real, the capture is real, the sidecar hashes, the command matches the declared one, and the coupling to the shipped `getBackupItemStatus` — a method on a Vue class in `src/asset/`, which the spec imports nothing from — is exactly zero. A rename, a regression or a deletion in the shipped method leaves the suite green forever.

So the tautology is not a broken test. It is a **correct test of the test file**, and running it harder is precisely what it is good at. Nothing dynamic separates it from a real spec. What separates it is structural: what the file imports, what it navigates to, and whether the symbol under assertion is defined in the file or somewhere the product also reads it from. Hence a gate that reads the test file instead of its result.

## The four tiers

Observed across a twenty-file Playwright suite in which thirteen specs were fake. Each tier is a strictly weaker coupling than the one above it, and each was written by someone who believed they were writing a test.

**Tier A — tautology.** The spec defines the function, class or object it tests, inside the test file, and asserts its own copy. Two placements: at the top of the file (`export function getBackupItemStatus(...)`, often with a candid comment — *"Helpers duplicating the pure dialog logic for hermetic verification (transcribed from map-slide-clients-dialog.ts)"*), or inside a `page.evaluate(() => { function computeShowSlideData(...) {...} ... })` body, where it looks like browser-side setup. Detected as `test_inline_reimplementation`.

**Tier B — source-text eval.** The spec reads a production file as TEXT (`fs.readFileSync(path.resolve(__dirname, '../../src/alert/helpers/alert-helper.ts'))`), extracts a slice with a regex or a brace-matching scan, and executes the slice with `new Function(...)` or after `ts.transpileModule`, against hand-built fake objects. This one is *almost* a real test — the executed bytes really did come from production — and it is the most dangerous because of that. The regex slice is pinned to text the author saw once: a rename or a refactor **outside** the sliced expression leaves the slice valid, the test green and the product broken; a rename **inside** it throws a "could not find ... in alert-helper.ts" error the spec itself raises, which reads as an environment problem rather than a real failure. Detected as `test_source_eval`.

**Tier C — synthetic DOM.** The spec calls `page.setContent('<div id="app">…')` with no `page.goto` anywhere, then asserts on the markup it just wrote. The assertions are about the test's own HTML and CSS classes; the component that would have produced them never runs. Detected as `test_synthetic_dom`.

**Tier D — the fallback.** The spec tries the application and, when that fails, injects dummy HTML from the `catch` block:

```ts
try { await page.goto(baseUrl, { timeout: 30000 }); }
catch (e) { await page.setContent(`<html>…<div id="notification-root"></div>…`); }
```

This is Tier C with a green tick on exactly the runs where the app is down — which is the run the author was trying to survive. It is the hardest tier to see in review because the file genuinely contains a `page.goto`, and CI genuinely goes green.

**A fifth shape is deliberately NOT a code here: static source inspection** — reading production source as text and asserting with a regex, without executing anything (`expect(/hasActiveSlideActionInitiated/.test(source)).toBe(true)`). It is a weak test, but it is a *true* statement about the shipped file, and firing on it would put the gate in the business of judging assertion quality. Such files are caught by `test_no_production_import` or `test_synthetic_dom` when they also have those properties, and pass when they do not.

## The heuristics, and what each one costs

### `test_no_production_import`

Fires when the file has **no** import resolving under a src root **and** no reference to a running surface. Doing either passes.

Import resolution: relative specifiers (`./`, `../`) resolve from the test file's directory across `.ts`, `.tsx`, `.d.ts`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.vue`, `.json`, `.py` and `index.*`; `@/x` and `~/x` are tried against every src root; a bare specifier (`@playwright/test`, `vitest`, `jest`, `node:fs`, `dotenv`) is never production. For C# an import is a `using X.Y;` whose first segment matches a top-level name under a src root or a `.csproj` stem; for Python a `from pkg.mod import x` / `import pkg.mod` whose first segment matches a package or module under a src root.

**Resolution is lexical when the file is missing.** A specifier that points at a moved or deleted file still counts as production if its normalized path is under a src root. This is deliberate: making a real spec look fake because a module was renamed is worse than missing a fake that imports a path nobody has.

- **False positive risk** — a project whose main code is somewhere `--src-roots` discovery does not find, or one that aliases `@` to a directory the gate does not try. The mitigation is `--src-roots`, and the refusal when discovery finds nothing at all (exit 2) exists so this failure surfaces as an error rather than as a wall of findings.
- **False negative risk** — a file that imports a production TYPE only (`import type { Agent } from '../../src/...'`) and reimplements every function passes this check. `automapping.spec.ts` in the observed suite does exactly that; `test_inline_reimplementation` is what catches it, and that is why the name-match branch does **not** require the absence of an import.
- **False negative risk** — a file that navigates to a URL that is not the application under test (a third-party page, a static fixture served from disk) passes. The gate cannot tell one http URL from another; `check_runtime_evidence.py`'s verification-surface registry is where "which surface was that" is settled.

Comments and string bodies are blanked before any of these signals are matched, so a commented-out `page.goto` does not count as navigation.

### `test_inline_reimplementation`

Two branches, and the discriminators matter more than the patterns.

**Branch 1 — name match.** A definition in the test file whose name is also defined under a src root. Fires regardless of what the file imports, because the transcribed-helpers shape (Tier A with a real type import) is the one that most looks like a real test.

**Branch 2 — ≥ 2 distinct definitions with no production contact.** No name match required. At two independent logic definitions in a file that imports nothing production and navigates nowhere, the file is a module of its own with tests attached, whatever the symbols are called.

Branch 2's condition is `no production import AND no running surface` — the same condition as `test_no_production_import`, and **deliberately tighter than the flag contract's plain reading of "no production import"** (convention #8). The looser reading fails `reinstall.spec.ts` in the observed suite: a genuine end-to-end spec that `page.goto`s the app, imports nothing from `src/`, and carries half a dozen pure formatting helpers (`diffEndpointState`, `renderMapping`). A spec that drives the real application is not a tautology because it also formats its output.

Three filters decide what counts as a definition at all:

1. **≥ 3 statements.** C-family: `;` terminators plus control-flow keywords, anywhere in the body. Python: non-blank, non-comment lines. Both over-count slightly (a `for (a; b; c)` header counts three), which is the safe direction — the size test is a *floor*, and the discrimination comes from the other two filters. A two-statement wrapper that delegates to the shipped class is below it and passes.
2. **No driving surface in the body.** A definition whose body references `page`, `browser`, `context`, `locator`, `request`, `driver`, `client`, `expect`, `execSync`, `spawn`, `HttpClient`, `WebApplicationFactory`, `TestServer`, `requests`, `httpx`, `axios` or `superagent` is a **test harness helper**, never a transcription of production logic. This is the load-bearing filter. Without it, every real end-to-end spec's `login(page, email, pw)`, `openNavDrawer(page)` and `pollSlideIntegrationGetter(page)` becomes a finding, the gate fails the entire suite, and the gate gets deleted. The `evals/contract/test-authenticity-adversarial/` case pins it with `real-e2e-helpers.spec.ts`, five such helpers in one file.
3. **Name ≥ 4 characters, not a keyword, not `test`-prefixed.** `id`, `fn` and `cb` matching something in `src/` is noise; a `test_*` / `TestX` function is the test itself.

**The `STOPWORDS` list is a cost, not a decoration.** The src symbol index is built from *definitions*, not only exports, because the pattern this gate was built from is a class METHOD (`getBackupItemStatus(backup: any) {`) with no `export` keyword anywhere near it. Widening to methods means the line-anchored `<name>(` pattern also matches `if (`, `for (`, `switch (` and Vue's `data() {` / `render() {` / `mounted() {`. So the list excludes language keywords, framework lifecycle names and object-literal boilerplate — and the price is exact and stated: **a production symbol genuinely named `render`, `data`, `handle`, `run`, `init` or `dispose` is invisible to branch 1.** A test transcribing one of those is caught only if it also trips branch 2 or another code. Narrowing the index to `export`ed symbols only would trade that miss for a much larger one: the entire Vue/TS class-method surface, which is where the observed evidence lived.

**Definitions are found at any nesting depth**, including inside `page.evaluate` and `describe` callbacks, because a tautology hides just as well one level down. The arrow-binding scanner requires only whitespace or a return-type annotation between the parameter list and the `=>`, which is what keeps `const result = await page.evaluate(async () => {...})` from reading as an arrow named `result` — before that bound existed, three of the observed files reported `result` as reimplemented logic.

- **False positive risk** — a test fixture builder or a data factory with a name that collides with a production symbol and no `page`/`expect` in its body. This is the most likely legitimate finding, and it is what `--allow ... --reason` is for.
- **False negative risk** — a transcription renamed away from its production counterpart (`computeShowSlideData` for something the product calls something else) escapes branch 1 entirely. Two of the observed fakes did exactly this; they were caught by branch 2 instead. A single renamed transcription in a file that also navigates the app is a genuine miss.

### `test_source_eval`

Requires all three in one file: a read-family call, a string literal naming a path under a src root, and an eval-family construct.

The literal is checked separately from the call because of how these are actually written: `const p = path.resolve(__dirname, '../../src/x.ts'); const source = fs.readFileSync(p, 'utf-8')`. The read call sees only a variable, so pairing the call with its own argument would catch none of the observed files. **Import specifiers are excluded from the literal set** — `import BackupCard from '../src/asset/backup-card'` is also a literal naming a path under a src root, and counting it would fire on any spec that legitimately imports production code and separately reads a JSON fixture.

`exec(` and `compile(` count only in `.py` files, so `child_process`'s `exec` is not confused for Python's. `execSync(` never matches `\bexec\s*\(`.

- **False positive risk** — a build-output test that reads a generated file from under a src root and evaluates it (a bundled artifact check, a generated-client smoke test). Legitimate, rare, and waivable.
- **False negative risk** — a spec that reads production source from a path built entirely at runtime with no literal segment naming a src root (a glob, a directory walk) is missed. So is one that reads and evaluates a production file that lives outside every src root.

### `test_synthetic_dom`

Two shapes. The plain one: `page.setContent(` or `document.body.innerHTML =` present, with no navigation anywhere in the file. The fallback one: a `try` block whose body contains a navigation and whose `catch` block contains a `setContent` or an `innerHTML` assignment — found by brace-matching the `try`, then requiring a `catch` immediately after it.

- **False positive risk** — `page.setContent` on markup the application produced (`const html = await page.content(); await page.setContent(html)`) is a legitimate round-trip, and it passes only because the file also has a `page.goto`. A test that loads markup from a fixture file and asserts a component renders against it — a legitimate pattern in some component-test setups — fires, and is waivable.
- **False negative risk** — the fallback rule requires the `catch` to *immediately* follow its `try`. A fallback expressed as `if (!(await tryGoto(page))) { await page.setContent(...) }`, or one where the catch only sets a flag that a later block reads, is missed. Mocking with `route.fulfill` is out of scope here by design — `playwright-skill` owns what may be mocked and what may not.

## The empty-index refusal

If no src root is discoverable and none is given, the gate is **exit 2**, never a verdict. An empty symbol index matches nothing, so branch 1 of `test_inline_reimplementation` can never fire, and every import resolves to "not production" — which would fire `test_no_production_import` on every file in the tree while reporting `PASS` on the tautology axis. Reporting a tree the gate never read is the same class of lie `check_openapi_diff.py` refuses under `unanalyzable_schema`, and it is refused the same way.

## What the waiver buys

`--allow <file> --reason "<text>"` exits 0 over that file's problems, keeps the findings in the report under `verdict: "ALLOWED"`, and writes the reason into the ledger record as `allow_reasons`. It buys **durability and attributability, not verification** — no script can judge whether "the DOM IS the artifact here" is true. It is hand-typed for the same reason `check_commit_gate.py --waiver` and `check_openapi_diff.py --allow-breaking` are (convention #8), and a blank reason is exit 2 on the same grounds: an unreasoned waiver is indistinguishable from an omission.

A waiver naming a file that was not judged in that run is a `warnings` entry rather than an error, because the changed set shrinks between runs and a stale waiver in a lane's stored command should not become a hard stop.

## Self-test inventory

**83 cases.** Grouped: src-root discovery (defaults, a `.csproj` beside its code, an explicit override, noise directories); test-file classification (each default glob family, an override, the basename fallback, a non-test file ignored rather than judged); each of the four codes in **both** directions across TypeScript, JavaScript, C# and Python; the near-miss pairs (`setContent` after a `goto`, a fixture read beside a `new Function`, a two-statement helper of a production name, one local definition instead of two, five `page`-driving helpers); the arrow-binding and repeated-definition regressions; waivers (clears, keeps the findings, does not leak to another file, warns when unmatched, blank reason, unpaired `--allow`); CLI paths (Windows backslashes, absolute paths, duplicates, a UTF-8 BOM, missing file, missing `--repo`, empty set, no src root); the ledger (a chained PASS, chaining across runs, an ERROR record, `problem_codes` + `failing_files`, `allow_reasons`, real input hashes); and the masking pass (offsets preserved, literal values kept, a commented-out `goto` not counted).

The end-to-end half — the gate as a subprocess against a real tree, the exact code set per file, and the ledger chain a hand edit breaks — is `evals/contract/test-authenticity-adversarial/`.
