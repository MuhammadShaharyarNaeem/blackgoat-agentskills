# Acceptance Matrix — slide-integration (plan-time draft)

A matrix as it looks at plan time: authored, not yet executed, so there is no
`acceptance-results.md` beside it. Every structural condition is satisfied
EXCEPT one — AL-2.2 distributes a policy and nothing in the scenario undoes it,
and nothing declares the step one-way. `--lint-only` exits 1 on it.

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
| 2 | Asset policies | distribute the policy to asset X | 202 + job queued | api, queue | auto |
| 3 | Device X console | verify the Slide agent is present | agent 1.4.2 present, service running | device | manual |
| 4 | Asset policies | remove the policy from asset X [inverse of 1] | 200 + policy row gone | api, db | auto |
