# Acceptance Matrix — slide-integration (plan-time draft, AL-2.2 exempted)

`acceptance-matrix.md` in this directory with the one-line fix applied: AL-2.2
declares itself genuinely one-way with `[no inverse: <reason>]`. `--lint-only`
exits 0. This is the escape hatch's fixture — the reason text is REQUIRED and
must contain a letter, but the gate cannot check whether the reason is TRUE.

## AL-1 Integration connect lifecycle — P0 — (FR-1, EC-1)
Surface: web+api | Preconditions: Slide sandbox credentials in the vault

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Integrations page | connect Slide with a valid key | 200 + connection row, status Connected | api, db | auto |
| 2 | Integrations page | reload | Connected badge rendered | ui | auto |
| 3 | Integrations page | disconnect Slide [inverse of 1] | 200 + connection row gone | api, db | auto |

## AL-2 Policy distribution — P0 — (FR-5, NFR-2)
Surface: web+api+device | Preconditions: integration connected (AL-1), asset X online

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Asset policies | add the Slide policy to asset X | 200 + policy row | api, db | auto |
| 2 | Asset policies | distribute the policy to asset X [no inverse: a queued distribution job cannot be un-queued; AL-2.4 removes the policy instead] | 202 + job queued | api, queue | auto |
| 3 | Device X console | verify the Slide agent is present | agent 1.4.2 present, service running | device | manual |
| 4 | Asset policies | remove the policy from asset X [inverse of 1] | 200 + policy row gone | api, db | auto |
