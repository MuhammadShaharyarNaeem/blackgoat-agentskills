# Runtime capture: Slide agent installed on asset X

- Milestone: M5 — Policy distribution [device]
- Acceptance step: AS-3.3
- Requirement IDs: FR-5, FR-6
- Surface: device
- Transport: out-of-process SSH to the device
- Device: asset-X (win11-lab-04)
- Probe command: `ssh lab@asset-x "sc query SlideAgent && slide --version"`
- Captured: 2026-08-12T15:22:04Z
- Exit code: 0
- Duration: 1.8s

## Captured output

```
SERVICE_NAME: SlideAgent
        STATE              : 4  RUNNING
slide 1.4.2+sha.9f2c1ab
```
