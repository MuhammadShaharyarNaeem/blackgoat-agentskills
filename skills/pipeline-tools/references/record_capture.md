# record_capture.py — reference

Depth for `record_capture.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show record_capture`); this page holds only the reasoning behind it.

## The incident this closes

A UI builder could not reach the running application, so it rendered a static mockup of the page, opened that file in a browser and screenshotted it. The screenshot was a real PNG, recently written, correctly named and cited in the right place. Every check that existed at the time — the magic bytes, the modification time, the citation resolving on disk — passed it cleanly, because nothing recorded **where the pixels came from**.

A rendered-evidence screenshot is a claim about the running application. A file that proves only "a PNG exists" cannot back that claim, and no amount of checking the PNG harder can recover the origin it never carried.

## What the sidecar adds, and its one hard rule

This is the write side of the provenance pair `check_commit_gate.py --require-rendered-evidence` reads back: it records the URL the browser had open at capture time, the tool that took it, when, and the PNG's hash as recorded.

The origin must be `http`/`https`. Everything else — a local file, a browser internal page, an inline data document, an empty value — is refused, because each of those is precisely the mockup case: a static document was open, not a served application. The refusal is a failed check rather than a usage error, since supplying a local-file origin is an honest answer to the question that happens to be the wrong answer.

The recorded hash is what makes a swap visible afterwards. Without it a sidecar could be recorded against a genuine capture and the PNG replaced later, and the pair would still agree on everything else.

## Why recording is once per PNG

An existing sidecar is a refusal rather than a silent overwrite. A capture is recorded once; re-recording without re-taking the screenshot is the shape of a sidecar being fitted to a file after the fact. The override flag exists for the legitimate case — the PNG was genuinely re-taken — and makes that a stated act rather than a default.

## The limit it shares with the rest of the family

Every field here is typeable, and the hash is unkeyed. A sufficiently determined author writes a sidecar naming a URL nobody visited, exactly as they can write a capture and its sidecar for a command that never ran (the spine's *unkeyed-sidecar limit*). What this buys is the same thing that limit buys everywhere else: the mockup screenshot stops passing by **omission**, and passing it now requires a written act that is attributable. Closing it needs a secret the runtime does not have.
