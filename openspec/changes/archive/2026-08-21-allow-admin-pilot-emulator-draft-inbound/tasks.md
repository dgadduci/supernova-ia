# Tasks: allow Twilio Emulator inbound on active draft orders

## 0. Approval and boundaries

- [x] 0.1 Approve the narrow extension of the existing detail-page emulator action.
- [x] 0.2 Keep migrations, Railway configuration, secrets, production and calibration out of scope.

## 1. Exact active-draft eligibility

- [x] 1.1 Extend `load_active_emulator_target` to accept an exact `BORRADOR`
  Pedido only when it has the associated active Session.
- [x] 1.2 Preserve the existing Pedido/Session/client/commerce identity,
  dedicated-channel, commerce-availability, active-installation and explicit
  emulator-mode guards.
- [x] 1.3 Leave the bootstrap action's active-session guard unchanged.

## 2. Detail action and status projection

- [x] 2.1 Allow the existing detail POST action to submit a valid active draft
  through the standalone emulator and the existing T-C/provider pipeline.
- [x] 2.2 Allow the existing bounded status projection to poll the exact active
  draft without creating state or searching for another Session.
- [x] 2.3 Preserve generic rejection, fail-closed behavior and the absence of
  fallback to local processing or real Twilio.
- [x] 2.4 Update detail-page copy to state that active draft orders are eligible;
  keep the local-only action separate.

## 3. Focused tests and safe outcomes

- [x] 3.1 Test acceptance of an exact active draft and rejection of detached,
  inactive, closed, cross-client and cross-commerce targets.
- [x] 3.2 Test two sequential draft messages through the existing receipt,
  worker and outbox pipeline without creating a replacement Session/Pedido.
- [x] 3.3 Test exact status scoping, duplicate synthetic-provider handling and
  no route-owned transaction completion or direct business mutation.
- [x] 3.4 Test bounded observability and unchanged local/non-draft behavior.

## 4. Validation and handoff

- [x] 4.1 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output.
- [x] 4.2 Review the implementation against this change and its non-goals.
- [x] 4.3 Do not run OpenSpec sync/archive, commit, create a PR, modify Railway
  or deploy as part of implementation.
