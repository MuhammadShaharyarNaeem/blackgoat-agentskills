# Runtime capture: Slide agent uninstalled from asset X

- Milestone: M5 — Policy distribution [device]
- Acceptance step: AS-3.5 (inverse of AS-3.3)
- Requirement IDs: FR-6
- Surface: device
- Transport: out-of-process SSH to the device
- Device: asset-X (win11-lab-04)
- Probe command: `ssh lab@asset-x "sc query SlideAgent; slide --version"`
- Captured: 2026-08-12T15:31:47Z
- Exit code: 1
- Duration: 1.6s

## Captured output

```
[SC] EnumQueryServicesStatus:OpenService FAILED 1060:
The specified service does not exist as an installed service.
'slide' is not recognized as an internal or external command
```
