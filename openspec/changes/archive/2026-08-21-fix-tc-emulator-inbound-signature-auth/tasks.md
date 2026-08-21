# Tasks: fix T-C emulator inbound signature authentication

## 1. Boundary confirmation

- [x] 1.1 Confirm the current inbound route always uses the real credential and reproduce the emulator-signature mismatch.
- [x] 1.2 Confirm the existing outbound real and emulator credential selection remains unchanged.

## 2. Implementation

- [x] 2.1 Select the mode-appropriate credential at the T-C inbound validation boundary.
- [x] 2.2 Preserve fail-closed configuration behavior and prohibit fallback or retry with the other credential.

## 3. Tests and validation

- [x] 3.1 Add or update a focused test proving a valid emulator signature is accepted with the synthetic credential.
- [x] 3.2 Add or update a focused test proving the real credential is rejected in emulator mode.
- [x] 3.3 Add or update a focused test proving real-mode behavior remains unchanged.
- [x] 3.4 Run the focused pytest, Ruff, compileall, strict OpenSpec validation, and diff checks from the proposal.
- [x] 3.5 Report the exact files changed, complete validation outputs, and any unresolved limitation.

## 4. Operational handoff

- [x] 4.1 Do not configure Railway variables or deploy from this change.
- [ ] 4.2 After merge and deploy, configure the existing test emulator and run E2E under separate operational authorization.

## 5. Out of scope

- [x] 5.1 Do not modify production, calibration, database schema, migrations, worker, outbox, or Admin/Pilot behavior.
- [x] 5.2 Do not rotate real credentials or introduce credential fallback.
- [x] 5.3 Do not run OpenSpec sync or archive until review and explicit user direction.
