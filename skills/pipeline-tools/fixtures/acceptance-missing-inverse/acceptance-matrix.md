# Acceptance Matrix — slide-integration

FIXTURE: AS-2.3 declares `[inverse of 7]` but scenario AS-2 has only steps 1-3.
The matrix is lying about its own coverage -> dangling_inverse, exit 1.
Executed by Quinn at the end of build into `acceptance-results.md`.

## AS-1 Integration connect lifecycle — P0 — (FR-1, EC-1)
Surface: web+api | Preconditions: Slide sandbox credentials in the vault

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Integrations page | connect Slide with a valid key | 200 + connection row, status Connected | api, db | auto |
| 2 | Integrations page | reload | Connected badge rendered | ui | auto |
| 3 | Integrations page | disconnect Slide [inverse of 1] | 200 + connection row gone | api, db | auto |

## AS-2 Client mapping lifecycle — P0 — (FR-3, FR-4, EC-2)
Surface: web+api | Preconditions: integration connected (AS-1)

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Clients list | map client A to a Slide client | 200 + mapping row | api, db | auto |
| 2 | Clients list | reload | green tick on A | ui | auto |
| 3 | Clients list | unmap A [inverse of 7] | 200 + mapping row gone | api, db | auto |

## AS-3 Policy distribution and agent lifecycle — P0 — (FR-5, FR-6, NFR-2)
Surface: web+api+device | Preconditions: client A mapped (AS-2), asset X online

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Asset policies | add the Slide policy to asset X | 200 + policy row | api, db | auto |
| 2 | Asset policies | distribute the policy to asset X | 202 + job queued | api, queue | auto |
| 3 | Device X console | verify the Slide agent installed | agent 1.4.2 present, service running | device | manual |
| 4 | Asset policies | remove the policy from asset X [inverse of 1] | 200 + policy row gone | api, db | auto |
| 5 | Device X console | verify the Slide agent uninstalled [inverse of 3] | agent absent, service deregistered | device | manual |
| 6 | Asset policies | redistribute to reinstall the agent | agent 1.4.2 present again | device | manual |

## AS-4 Bulk mapping import — P2 — (FR-9)
Surface: web+api | Preconditions: integration connected (AS-1)

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Clients list | import a 3-row mapping CSV | 200 + 3 mapping rows | api, db | auto |
| 2 | Clients list | delete the imported mappings [inverse of 1] | 200 + rows gone | api, db | auto |
