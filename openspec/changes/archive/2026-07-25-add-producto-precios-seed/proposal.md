## Why

`producto_precios` needs deterministic initial prices for every seeded product-presentation so catalog flows have complete price data in development and test databases.

## What Changes

- Add a JSON dataset containing one valid price per seeded product-presentation.
- Add an idempotent script that validates the dataset and inserts only missing prices into the selected database.
- Keep category-dependent price policy in dataset generation rather than in the persistence script.

## Capabilities

### New Capabilities
- `seeds-producto-precios`: Seed the current price for each product-presentation from a validated JSON dataset.

### Modified Capabilities

- None.

## Impact

- Adds `backend/db/seeds/data/precios.json` and `backend/db/seeds/seeds/producto_precios.py`.
- Requires existing `producto_presentaciones` rows.
- Does not modify models, migrations, API behavior, or product-presentation records.
