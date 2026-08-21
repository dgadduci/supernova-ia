# Tasks: add Admin/Pilot Emulator conversation history

## 0. Approval and boundaries

- [x] 0.1 Approve the UI-only conversation-history change.
- [x] 0.2 Keep backend, database, Railway, secrets, production and calibration out of scope.

## 1. Scrollable conversation surface

- [x] 1.1 Add a dedicated Emulator conversation list with fixed height,
  independent vertical scrolling and accessible labels.
- [x] 1.2 Preserve the existing Emulator form, result/status selectors and
  local-only transcript behavior.
- [x] 1.3 Add copy explaining that the visible history is limited to the
  current page and can be selected for handoff.

## 2. Browser turn rendering

- [x] 2.1 Append each submitted operator message once as an `Enviado` turn.
- [x] 2.2 Associate status polling with the exact synthetic inbound identifier.
- [x] 2.3 Add at most one received response or bounded error per turn, without
  duplicating rows on repeated polling.
- [x] 2.4 Keep safe text rendering, bounded display values and a bounded list;
  do not use browser storage or URL state.
- [x] 2.5 Scroll to the newest visible entry after each append/update.

## 3. Focused tests

- [x] 3.1 Test the list structure, accessibility markers and fixed scroll CSS.
- [x] 3.2 Test sent/received/error rendering contracts and preservation of
  previous turns.
- [x] 3.3 Test synthetic-id deduplication and absence of storage/HTML sinks.
- [x] 3.4 Test unchanged local transcript, Emulator form and generic failure
  contracts.

## 4. Validation and handoff

- [x] 4.1 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output.
- [ ] 4.2 Review the implementation against this change and its non-goals.
- [ ] 4.3 Do not run OpenSpec sync/archive, commit, create a PR, modify Railway
  or deploy as part of implementation.
