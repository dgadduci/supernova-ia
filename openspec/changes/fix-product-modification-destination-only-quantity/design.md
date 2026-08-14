# Design: destination-only quantity semantics

## Decision

Reuse the paired-quantity data shape already deployed. Change only the
recognizer branch where source has no explicit positive amount and destination
has one:

```text
source explicit?  destination explicit?  resolved_data
no                yes                     cantidad=None, cantidad_destino=M
```

The existing handler then re-reads source quantity just before service
delegation, and the existing service already applies source amount and
destination amount independently. No new service method, transaction path, or
response format is necessary.

## Invariants

- Candidate source/destination scopes and pending IDs do not change.
- Pending resolution copies `cantidad=None` and `cantidad_destino=M` exactly.
- An old pending payload with `cantidad=N` and absent `cantidad_destino`
  remains N -> N.
- Invalid destination quantity stays rejected before pending.
- The handler's source re-read is the authority for “full source”; no cached
  or inferred source quantity is substituted.
- All existing validation precedes mutation in the caller-owned transaction.

## Test strategy

- Unit: destination-only word/digit yields `None/M`, while source-only,
  paired, omitted, invalid and historical shapes keep their fields.
- Pending: ambiguous destination then `grande` preserves `None/M`.
- End-to-end: source one / destination existing one plus `por dos` ends source
  removed and destination at three; source larger case proves full-source
  removal and exact destination increment.
- Response: distinct full-source operation shows actual source and destination
  amounts; N -> N and N -> M remain unchanged.
