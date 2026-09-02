# summarize_run.py — reference

Depth for the `summarize_run.py` section of `../SKILL.md`: aggregation semantics, the third gate bucket, and the self-test inventory.

## Aggregation semantics

- Every bucket aggregates over **all** records; `delegations` counts `event=delegation` only, so a run log carrying gate and phase records does not inflate the delegation count.
- `duration_s_total` sums the **known** durations only and is always reported alongside `duration_known_count` and `duration_unknown_count`. A total with no known/unknown split is indistinguishable from a complete one, which is exactly the fabrication `record_run.py`'s null-not-zero rule exists to prevent.
- `rounds_max` is a **maximum, not a sum** — rounds are per-unit cycles, and adding them across units produces a number that describes nothing.
- `duration_mean_s` (agents bucket only) averages over known durations, and is `null` when none are known.
- `tokens_total` is reported with `tokens_unknown_count` for the same reason as duration.

## The three gate buckets

`fired` and `rubber_stamped` are the two halves of the metric the shipping game tape used to write from memory. The third, `inconclusive`, exists because an `ERROR` verdict is a gate **failing to run**, not a gate catching something: counting it as fired would credit a broken invocation with a save, and counting it as rubber-stamped would credit it with a clean pass. Neither is true, so it gets its own bucket.

`rubber_stamped` is a **description, not a verdict**. A gate that never failed may be redundant, or may be the one holding the line that nothing has crossed yet. The classification is the input to Forge's Incident Test — *a removal must cite fired-vs-rubber-stamped counts, a proposal must name the incident that would have fired it* — never its answer.

## Scoping and tolerance

- `--unit` matches **case-insensitively on the whole value**, not a substring — the same exact-equality discipline `check_blockers.py --milestone` uses.
- A ledger entry with a `null` milestone falls **out** of a unit view by design (it cannot be attributed to one unit) and appears in the whole-log roll-up.
- A malformed run-log line is counted in `malformed_lines` and skipped, never fatal: a truncated final line from an interrupted session must not take the whole summary down. An unopenable `--run-log` is exit 2.
- An unreadable or absent `--ledger` yields `gates: null` plus a warning, exit unchanged — the run-log half of the summary is still worth having.

## Markdown output

ASCII punctuation only (cp1252 console safety), and pipe characters in any value are escaped so a milestone title containing `|` cannot break the table it lands in.

## Self-test inventory

`python scripts/summarize_run.py --self-test` runs **14** cases, covering the empty log, per-pipeline/unit/agent bucketing, the known/unknown duration and token splits, `rounds_max` as a maximum, the three gate classifications, `--unit` scoping including the null-milestone ledger entry falling out, a malformed line counted and survived, an absent ledger warning, exit 2 on a missing and on an unopenable `--run-log`, and the markdown rendering.
