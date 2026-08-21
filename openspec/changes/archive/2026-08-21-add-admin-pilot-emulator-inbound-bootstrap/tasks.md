# Tasks: add Admin/Pilot emulator inbound bootstrap

## 0. Approval and boundary

- [ ] 0.1 Approve the change as an extension of the existing Admin/Pilot
  Twilio Emulator path, with no direct order-creation pipeline.
- [ ] 0.2 Keep Railway, variables, secrets, production and calibration out of
  implementation scope.

## 1. Server-side bootstrap boundary

- [x] 1.1 Add bounded request/response models for positive `cliente_id`,
  positive `comercio_id` and nonblank message text.
- [x] 1.2 Add the authenticated, same-origin Admin/Pilot bootstrap route on
  the order list surface.
- [x] 1.3 Reuse existing client E.164, dedicated-channel, commerce
  availability, active-installation and emulator-configuration seams.
- [x] 1.4 Reject an existing active client/commerce Session without mutating it
  or creating a second order context.
- [x] 1.5 Submit exactly one server-side emulator inbound command and return a
  bounded synthetic inbound identifier.
- [x] 1.6 Preserve fail-closed behavior and forbid fallback to local or real
  provider paths.

## 2. Admin/Pilot UI

- [x] 2.1 Add two ID inputs, a bounded message textarea and an explicit
  `Iniciar inbound de cliente por Twilio Emulator` action to the order list.
- [x] 2.2 Render only bounded accepted/rejected status and synthetic inbound
  identifier; never render secrets, addresses, raw provider payloads or body
  text from a response.
- [x] 2.3 Prevent duplicate submission and provide a clear refresh path for
  the asynchronously created Pedido.
- [x] 2.4 Preserve the existing order-detail emulator action and local-only
  channel unchanged.

## 3. Observability and tests

- [x] 3.1 Emit closed bootstrap outcome/reason categories without PII,
  credentials, URLs, message bodies or exception details.
- [x] 3.2 Add focused service tests for valid identity, invalid/inactive
  client, unavailable commerce, missing channel/installation, active-context
  conflict and server-side E.164 resolution.
- [x] 3.3 Add focused route/template tests for authentication, same-origin,
  bounded payloads, duplicate submission, response shaping and no direct DB
  creation.

## 4. Validation and handoff

- [x] 4.1 Run and report focused pytest, Ruff, compileall, strict OpenSpec and
  `git diff --check` output from `proposal.md`.
- [x] 4.2 Codex reviews implementation, tests, security, transaction
  ownership, async order creation behavior and scope.
- [x] 4.3 Do not run OpenSpec sync/archive, commit, PR, Railway mutation or
  deployment as part of implementation.
