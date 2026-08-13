# Runtime capture: Slide agent reinstalled on asset X

- Milestone: M5 — Policy distribution [device]
- Acceptance step: AS-3.6
- Requirement IDs: FR-5
- Surface: device
- Transport: out-of-process SSH to the device
- Device: asset-X (win11-lab-04)
- Probe command: `ssh lab@asset-x "sc query SlideAgent && slide --version"`
- Captured: 2026-08-12T15:39:12Z
- Exit code: 0
- Duration: 2.1s

## Captured output

```
SERVICE_NAME: SlideAgent
        STATE              : 4  RUNNING
slide 1.4.2+sha.9f2c1ab
```
