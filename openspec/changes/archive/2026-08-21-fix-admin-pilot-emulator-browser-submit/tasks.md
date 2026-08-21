# Tasks: fix Admin/Pilot Twilio Emulator browser submission

## 1. Confirm the defect

- [x] 1.1 Confirm the emulator form is rendered as a native form while the route expects a Pydantic JSON body.
- [x] 1.2 Confirm the existing browser handler binds only the local-test selector and does not handle the emulator form.

## 2. Browser implementation

- [x] 2.1 Expose the existing emulator status URL through a non-secret data attribute when the action is enabled.
- [x] 2.2 Add a dedicated emulator-form handler that prevents native submission and sends the existing JSON payload and origin header.
- [x] 2.3 Parse only the bounded submit response and start bounded status polling with the synthetic inbound identifier.
- [x] 2.4 Render bounded status/text/SID results and handle errors without raw details or fallback behavior.
- [x] 2.5 Preserve the existing local-test handler and selectors unchanged.

## 3. Tests and validation

- [x] 3.1 Add focused template/script regression assertions for the emulator JSON submission contract.
- [x] 3.2 Add focused assertions for status URL exposure, polling request shape and terminal/transitional behavior where the existing test surface permits.
- [x] 3.3 Preserve coverage that the local form remains independent.
- [x] 3.4 Run the focused pytest, Ruff, compileall, strict OpenSpec validation and diff checks from the proposal.
- [x] 3.5 Report exact files changed, complete outputs and unresolved limitations.

## 4. Operational handoff

- [x] 4.1 Do not modify Railway variables or deploy from this change.
- [ ] 4.2 After merge and deploy, submit one test-panel message and verify the emulator action reaches the T-C/NovaOrders pipeline and polls to a bounded terminal status.

## 5. Out of scope

- [x] 5.1 Do not change FastAPI request/response schemas or accept form-urlencoded input as a second contract.
- [x] 5.2 Do not modify T-C, emulator service, worker, dispatcher, outbox, database or production/calibration.
- [x] 5.3 Do not run OpenSpec sync or archive until implementation review and explicit user direction.
