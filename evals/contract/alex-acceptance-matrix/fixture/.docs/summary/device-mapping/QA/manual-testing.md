# Manual Test Baseline — device-mapping (behavior today)

Reverse-engineered by Echo during discovery. These are cases the system is presumed to
**still** satisfy. Alex reconciles each one against the change: it either still holds
(carry it forward as a regression obligation), is invalidated by the change, or is
superseded by a new requirement. A case dropped silently is behavior nobody decided to
stop supporting.

## MT-1 Client group column renders the seeded mapping — P0

| GO | DO | ASSERT |
|----|----|--------|
| Clients list | open the list with at least one seeded mapping | each mapped client's row shows its group name, unmapped clients show an em dash |
| Client detail | open a mapped client | the group name matches the Clients list value |

## MT-2 Alert routing follows the mapping table — P0

| GO | DO | ASSERT |
|----|----|--------|
| Alerts stream | raise a test alert on a device in a mapped group | the alert carries the mapped client's routing key |
| Database | delete the mapping row by hand (current support workflow) | the next test alert carries no routing key |

## MT-3 Per-device agent install from the device detail page — P1

| GO | DO | ASSERT |
|----|----|--------|
| Devices list | open a device with no agent | the Install action is enabled |
| Device detail | trigger Install | the device shows as reporting within 2 minutes and the monitoring-agent service is running on the machine |

## MT-4 Device list filter by agent state — P2

| GO | DO | ASSERT |
|----|----|--------|
| Devices list | filter by "not reporting" | only devices without a healthy agent are listed |

## MT-5 Manual uninstall runbook (no product path) — P1

| GO | DO | ASSERT |
|----|----|--------|
| Target machine | follow the uninstall runbook by hand | the monitoring-agent package is gone; **known defect** — the service registration remains about a third of the time, and a later install on that device then fails |
