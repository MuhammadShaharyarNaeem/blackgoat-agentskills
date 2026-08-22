# Device Mapping & Agent Rollout — Requirements

## Vision
Admins map a client to a monitored device group, then roll the monitoring agent out to
the devices in that group — and can reverse both operations cleanly when a client
offboards or a device is repurposed.

## User Personas
- **Platform Admin**: maps clients to device groups and rolls the agent out. Needs every
  operation to be reversible, because onboarding mistakes are routine and offboarding is
  contractual.
- **Support Engineer**: reads a device's agent state to decide whether a health gap is a
  monitoring problem or a real outage.

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a platform admin, I want to map a client to a monitored device group
  and to unmap it again, so that alerts route to the right team and an offboarded client
  stops receiving another tenant's alerts.
  - Given an unmapped client and an existing device group, When I map them, Then the
    mapping is stored, the client's row shows the group, and alerts from the group's
    devices carry the client's routing key.
  - Given a mapped client, When I unmap it, Then the mapping is gone, the client's row
    shows no group, and alerts from that group no longer carry the client's routing key.
  - Unmapping leaves the device group itself untouched.

- [ ] **FR-2** As a platform admin, I want to install the monitoring agent on a device in
  a mapped group, uninstall it, and install it again later, so that a repurposed device
  can be cleaned and re-enrolled.
  - Given a device in a mapped group with no agent, When I install the agent, Then the
    agent service is present and running on that device and the device appears as
    reporting in the console.
  - Given a device with the agent installed, When I uninstall it, Then the agent service
    is absent from the device and the device is deregistered from the console.
  - Given that same device after an uninstall, When I install the agent again, Then it
    reports healthy exactly as a first install does, with no leftover state from the
    previous enrolment.

### Should Have
- [ ] **FR-3** As a support engineer, I want the device list filterable by agent state,
  so that I can find unreporting devices quickly. — Given devices in mixed states, When I
  filter by "not reporting", Then only devices without a healthy agent are listed.

### Won't Have (this version)
- Automatic re-enrolment of devices that drop off for more than 30 days.

## Non-Functional Requirements
- **NFR-1** (Must) Reliability: a failed install leaves no partially-registered device
  behind — either the device is fully enrolled or it is absent from the console.

## Open Questions
- None.
