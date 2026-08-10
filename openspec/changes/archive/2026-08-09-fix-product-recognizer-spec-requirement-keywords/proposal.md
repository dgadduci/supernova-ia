# Fix product-recognizer normative requirements

## Why

The canonical `product-recognizer` specification fails strict OpenSpec validation because the `Unavailable handling` and `Unknown products` requirements lack normative `SHALL` or `MUST` language. This documentation-only defect blocks archival of an unrelated completed change.

## What Changes

- Add `SHALL` language to the two invalid requirements.
- Preserve their scenarios and existing behavior exactly.

## Scope and non-goals

This change updates only the OpenSpec delta for `product-recognizer`. It does not alter implementation, tests, runtime configuration, recognition behavior, or archived changes.

## Validation

The user will run strict validation locally and provide the complete output before this change is considered ready to archive.
