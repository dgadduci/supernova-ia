# Capability: Admin/Pilot emulator browser submission

## Purpose

Define the browser-side contract that the Admin/Pilot console uses to drive
the dedicated Twilio emulator test action through the existing JSON routes
and to poll the existing read-only status projection. The contract keeps the
emulator form independent from the local-test form and forbids any
fallback to the local channel, T-C or a real provider.

## Requirements

### Requirement: The Admin/Pilot emulator action SHALL use the existing JSON and status-polling contract

When the emulator action is visible, the browser SHALL intercept the dedicated
emulator form instead of performing native form navigation. It SHALL submit a
JSON object containing only `message` to the existing emulator action route
with `credentials: same-origin` and `X-Emulator-Test-Origin: same-origin`.
After a successful response, it SHALL use the returned
`synthetic_inbound_id` to call the existing status route with a JSON object
containing only that identifier. It SHALL render only the bounded response
fields and SHALL keep the local-test action independent.

#### Scenario: Valid emulator submission reaches the JSON route contract

- WHEN an authenticated operator enters a non-empty message in the visible emulator form and submits it
- THEN the browser prevents native form navigation
- AND the browser sends `Content-Type: application/json` with `{"message": "..."}`
- AND the browser sends `X-Emulator-Test-Origin: same-origin` with same-origin credentials
- AND the existing route receives a dictionary-shaped request and can return a bounded `synthetic_inbound_id`

#### Scenario: Successful submission starts bounded status polling

- WHEN the emulator action returns a non-empty `synthetic_inbound_id`
- THEN the browser posts `{"synthetic_inbound_id": "..."}` to the existing status route
- AND transitional statuses are polled only within a bounded interval/count or deadline
- AND terminal statuses stop polling
- AND only the bounded status, outbound text and synthetic provider SID are rendered when present

#### Scenario: Submission or polling failure is bounded

- WHEN the submit response, status response or response shape is invalid
- THEN the browser displays a generic emulator failure/status message
- AND it stops polling and re-enables the emulator form
- AND it does not fall back to the local channel, T-C or a real provider

#### Scenario: The existing local form remains isolated

- WHEN the operator submits the existing local-test form
- THEN its current JSON request, local transcript and local route behavior remain unchanged
- AND no emulator status request or emulator-specific result is created

#### Scenario: Disabled emulator remains unavailable

- WHEN emulator configuration causes the detail page to hide the emulator action
- THEN no emulator form handler is active for that page
- AND the browser cannot create an emulator request through the detail page
