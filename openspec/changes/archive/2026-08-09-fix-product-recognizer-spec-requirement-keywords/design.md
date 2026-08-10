# Design

## Objective

Make the two canonical requirements accepted by OpenSpec's normative-language validator without changing their meaning.

## Current execution path

The invalid text is in the canonical `product-recognizer` specification. No application execution path is involved.

## Decision

Replace only the introductory prose of `Unavailable handling` and `Unknown products` with equivalent `SHALL` statements. Copy every existing scenario unchanged into the modified delta so an archive cannot drop coverage.

## Boundaries

- No code, test, configuration, deployment, or data changes.
- No transaction ownership or fallback behavior changes.
- No archive is performed by this documentation correction.

## Reversibility

The change is a small, reviewable specification wording update and can be reverted independently.
