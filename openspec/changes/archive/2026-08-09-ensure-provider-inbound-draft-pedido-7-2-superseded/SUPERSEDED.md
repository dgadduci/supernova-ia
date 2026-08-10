# Superseded

This change is retired without applying its specification delta.

It assumed that provider webhook acceptance owns session and draft-pedido
staging. That design was superseded by deferred provider processing, whose
acceptance boundary commits only the receipt and its pending work item.

The implemented and canonical replacement is archived as
`2026-08-09-specify-deferred-provider-draft-pedido-7-2-1`, which documents
draft-pedido staging in the leased deferred-processing transaction before the
existing message pipeline.
