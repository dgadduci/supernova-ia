# Tasks

- [x] 1.1 Inspect existing settings/session factory and provider ORM models;
  reuse them without adding a database abstraction.
- [x] 1.2 Implement a standalone read-only polling CLI with bounded interval
  and duration arguments and clean Ctrl-C termination.
- [x] 1.3 Project only safe receipt, processing, LLM timing, state/category
  and outbound-count fields; hash the opaque provider receipt key.
- [x] 1.4 Emit first and changed snapshots, including processed-with-zero-
  outbound as an observable terminal condition without claiming root cause.
- [x] 1.5 Add focused tests for projection, filtering, transitions, privacy,
  duration/interrupt handling and no database writes.
- [x] 1.6 Document the Railway shell command and how to interpret the timeline
  alongside Twilio timestamps.
- [x] 1.7 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report all output and pre-existing failures.
- [x] 1.8 Stop after the diagnostic. Do not modify runtime flow, Railway
  configuration, variables, secrets, worker state or Twilio settings.
