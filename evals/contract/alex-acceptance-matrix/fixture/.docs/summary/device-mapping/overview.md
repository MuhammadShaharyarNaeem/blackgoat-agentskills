# Feature Overview — device-mapping (as it behaves today)

Reverse-engineered by Echo during discovery. This records the **current** system, before
the mapping/rollout work in `.docs/device-mapping/requirements.md`.

## Surfaces involved
- `console-web` — the Clients list and the Devices list. Mapping is read-only today: the
  group column renders whatever `device-api` returns and offers no way to change it.
- `device-api` — `GET /api/clients/{id}/group` (read), `GET /api/devices?groupId=` (read),
  `POST /api/devices/{id}/agent/install` (exists, single device, no group awareness).
- `agent-host` — the on-device service (`monitoring-agent`). Install is a package drop
  plus a service registration; there is no uninstall path in the product today, only a
  runbook an engineer follows by hand.

## What exists today
- Client-to-group mapping rows are seeded by a migration and edited directly in the
  database by support. No API writes them.
- Agent install works per device and is invoked from the device detail page.
- Alert routing already reads the mapping table, so routing behavior changes the moment a
  mapping row changes.

## Known gaps carried into this change
- No unmap path at all. Support deletes the row by hand.
- No uninstall path in the product; the runbook leaves the service registered on the
  device about a third of the time, which is why reinstall currently fails on a
  previously-enrolled device.
