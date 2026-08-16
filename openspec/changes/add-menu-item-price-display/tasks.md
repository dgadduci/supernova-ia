# Tasks: display prices in customer menu responses

## 1. Deterministic Projection

- [x] 1.1 Reuse the existing valid-price formatter while building `ver_menu`
  items from the current commerce sellable catalog.
- [x] 1.2 Preserve category filtering, full-menu fallback, item order and
  absence fallback without a second query or wider catalog scope.

## 2. Deterministic Rendering

- [x] 2.1 Render an optional stable price beside each valid full-menu item.
- [x] 2.2 Render the same optional price in a selected-category menu while
  preserving legacy text for entries without a valid price.

## 3. Focused Coverage and Validation

- [x] 3.1 Cover full/category price display, missing/malformed/negative
  fallback, commerce isolation, pure rendering and no transaction control.
- [ ] 3.2 Run the validation commands in `proposal.md`, strict OpenSpec
  validation and `git diff --check`.

## 4. Pilot Gate (post-deploy only)

- [x] 4.1 Verify the complete menu and one category menu show expected
  current prices in the pilot, with no missing/foreign products.
