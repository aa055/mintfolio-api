# Mintfolio — Database Schema (Phase 1 MVP)

> **STATUS: REVISION 2 — awaiting user re-review.** No SQLAlchemy models or Alembic migrations have been written from this yet. Once you approve, I will translate this into `app/models/*.py` and an initial migration.

This document defines the Phase 1 schema. It covers the **7 core tables** locked in the plan (the original 6 plus a `purchases` table introduced in this revision so a single dealer order can contain multiple line items).

---

## What changed in Revision 2

| # | Change | Driver |
|---|---|---|
| 1 | Added `purchases` table; `holdings` now references it | Multi-item orders (1 receipt, N items from same dealer/date) |
| 2 | Moved `dealer`, `purchase_date`, `purchase_currency`, `payment_method`, `card_premium_percentage` to `purchases` | They describe the order, not the item |
| 3 | `uploaded_files` now references `purchases` instead of `holdings` | One receipt covers all items in an order |
| 4 | Weight now split into 3 columns: `weight_value`, `weight_unit`, `weight_grams` (canonical) | User-friendly: pick unit → type value; we store canonical grams for math |
| 5 | Added `'bullion'` to the `form` CHECK list | Your request |
| 6 | Added `payment_method` (`cash`/`card`) and `card_premium_percentage` (default 2.5) to `purchases` | Your request |
| 7 | `price_history.purity` confirmed kept; daily GoldAPI cron stores rates for **all** purities returned | Your answer to Q4 |
| 8 | `holdings.spot_rate_at_purchase` confirmed optional + form-level verification rule documented | Your answer to Q6 |
| 9 | `users` row creation locked to `POST /auth/sync` endpoint | Your answer to Q1 |
| 10 | Cross-currency conversion confirmed deferred to Phase 2 (with recommended API) | Your answer to Q3 |

---

## Global Conventions

| Concern | Choice | Rationale |
|---|---|---|
| Primary keys | `UUID`, server-generated via `gen_random_uuid()` | No leaked sequence info, easy merging |
| Timestamps | `timestamptz` (timezone-aware), stored UTC | Render in user's tz |
| Money / prices | `numeric(14, 2)` totals, `numeric(14, 4)` per-unit rates | Floats are wrong for money |
| Weight (canonical) | `numeric(12, 4)`, **always grams** | Conversion happens on write |
| Currency codes | `text` (no DB enum) | Adding new currencies later = no migration |
| Metal | `text` + `CHECK IN ('gold', 'silver')` | MVP-locked per your answer |
| Soft delete | **None** | Hard delete with cascade |
| `created_at` / `updated_at` | Every mutable table | DB-managed |
| Naming | `snake_case`, **plural** | Standard SQLAlchemy |
| RLS | **Enabled, no policies** | FastAPI service-role key bypasses; defense-in-depth against anon-key leaks |

---

## Table 1 — `users`

Mirrors `auth.users` from Supabase. The `id` matches the Supabase user UUID; no cross-schema FK into `auth.users` (fragile). Row is created by `POST /auth/sync` right after Supabase signup.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `uuid` | PK | = `auth.users.id` |
| `email` | `text` | NOT NULL | Denormalized |
| `display_name` | `text` | NULL | |
| `avatar_url` | `text` | NULL | |
| `preferred_currency` | `text` | NOT NULL, DEFAULT `'AED'`, CHECK in (`'AED','USD','EUR','GBP','SAR','INR'`) | |
| `timezone` | `text` | NOT NULL, DEFAULT `'Asia/Dubai'` | IANA tz |
| `default_pricing_mode` | `text` | NOT NULL, DEFAULT `'live'`, CHECK in (`'live','manual'`) | |
| `manual_gold_rate_per_gram` | `numeric(14, 4)` | NULL | Per-gram rate the user last entered for gold |
| `manual_silver_rate_per_gram` | `numeric(14, 4)` | NULL | Same for silver |
| `manual_rates_currency` | `text` | NULL | Currency the manual rates are in |
| `created_at` | `timestamptz` | NOT NULL, DEFAULT `now()` | |
| `updated_at` | `timestamptz` | NOT NULL, DEFAULT `now()`, ON UPDATE `now()` | |

**Indices:** PK only.

---

## Table 2 — `portfolios`

One per user in MVP (enforced by UNIQUE on `user_id`). Schema is multi-portfolio ready for Phase 2.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `user_id` | `uuid` | NOT NULL, FK → `users.id` ON DELETE CASCADE, **UNIQUE** | MVP guard |
| `name` | `text` | NOT NULL, DEFAULT `'My Portfolio'` | |
| `created_at` | `timestamptz` | NOT NULL, DEFAULT `now()` | |
| `updated_at` | `timestamptz` | NOT NULL, DEFAULT `now()`, ON UPDATE `now()` | |

**Indices:** PK + UNIQUE on `user_id`.

---

## Table 3 — `purchases` (NEW in Rev 2)

A single dealer order. Owns the metadata that's shared across all items bought together: dealer, date, currency, payment method, receipt.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `portfolio_id` | `uuid` | NOT NULL, FK → `portfolios.id` ON DELETE CASCADE | |
| `purchase_date` | `date` | NOT NULL | |
| `dealer` | `text` | NULL | Free text, e.g. "Emirates Gold", "BullionByPost" |
| `purchase_currency` | `text` | NOT NULL | Currency for ALL line items in this purchase |
| `payment_method` | `text` | NOT NULL, DEFAULT `'cash'`, CHECK in (`'cash','card'`) | Your request |
| `card_premium_percentage` | `numeric(5, 2)` | NULL, CHECK (`>= 0 AND <= 100`) | Only meaningful when `payment_method='card'`. Default at form level = `2.50`. Stored NULL when cash. |
| `notes` | `text` | NULL | |
| `created_at` | `timestamptz` | NOT NULL, DEFAULT `now()` | |
| `updated_at` | `timestamptz` | NOT NULL, DEFAULT `now()`, ON UPDATE `now()` | |

**Check constraint:**
- `payment_method = 'cash' AND card_premium_percentage IS NULL` OR
- `payment_method = 'card' AND card_premium_percentage IS NOT NULL`

**Indices:**
- `(portfolio_id, purchase_date DESC)` — for the "recent purchases" view

**Computed (not stored):** Total amount = `SUM(holdings.purchase_price)` for all holdings in this purchase. The frontend's purchase form shows a running total as line items are added. We don't denormalize because it can drift.

---

## Table 4 — `holdings` (REVISED in Rev 2)

The line items. One row per item. A purchase can have N holdings.

**What moved to `purchases`:** `dealer`, `purchase_date`, `purchase_currency`, `payment_method`, `card_premium_percentage`. They describe the order, not the item.

**What's new:** the weight is now stored as three columns — what the user typed (`weight_value`), what unit they picked (`weight_unit`), and the canonical grams (`weight_grams`) used for all math.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `purchase_id` | `uuid` | NOT NULL, FK → `purchases.id` ON DELETE CASCADE | Every holding belongs to a purchase |
| `metal` | `text` | NOT NULL, CHECK in (`'gold','silver'`) | |
| `purity` | `text` | NULL | `'24K'`, `'22K'`, `'999'`, `'925'`, etc. |
| `form` | `text` | NULL, CHECK in (`'coin','bar','bullion','jewelry','round','other'`) | `'bullion'` added per your request |
| `weight_value` | `numeric(12, 4)` | NOT NULL, CHECK `> 0` | What the user typed: 1, 0.5, 31.1, etc. |
| `weight_unit` | `text` | NOT NULL, CHECK in (`'g','kg','oz'`) | What the user picked. (We can add 'tola' later — common in UAE/India.) |
| `weight_grams` | `numeric(12, 4)` | NOT NULL, CHECK `> 0` | Canonical, computed from `value × unit_factor` on write. 1 oz = 31.1035 g (troy). 1 kg = 1000 g. |
| `quantity` | `integer` | NOT NULL, DEFAULT `1`, CHECK `>= 1` | e.g. "5 coins of the same kind" |
| `brand` | `text` | NULL | "PAMP Suisse", "Emirates Gold", etc. |
| `purchase_price` | `numeric(14, 2)` | NOT NULL, CHECK `>= 0` | THIS item's portion of the order total. In `purchases.purchase_currency`. |
| `spot_rate_at_purchase` | `numeric(14, 4)` | NULL | Per gram. Optional. See verification rule below. |
| `premium_paid` | `numeric(14, 2)` | NULL | Premium over spot for this item, in purchase_currency. |
| `storage_location` | `text` | NULL | |
| `status` | `text` | NOT NULL, DEFAULT `'active'`, CHECK in (`'active','sold'`) | Phase 2 adds `'partial'` |
| `comments` | `text` | NULL | |
| `created_at` | `timestamptz` | NOT NULL, DEFAULT `now()` | |
| `updated_at` | `timestamptz` | NOT NULL, DEFAULT `now()`, ON UPDATE `now()` | |

**Indices:**
- `(purchase_id)` — for "show me the items in this purchase"
- `(metal, status)` — when combined with a portfolio_id join, the dashboard's "active gold" query
- `purchase_id` (covered by FK)

Indirect to portfolio: dashboard queries `holdings JOIN purchases ON purchase_id = purchases.id WHERE purchases.portfolio_id = ?`.

### Verification rule (form-level, not a DB constraint)

When the user provides `spot_rate_at_purchase`, the frontend computes:

```
expected_total = (weight_grams × spot_rate_at_purchase × quantity) + COALESCE(premium_paid, 0)
```

Then compares against the entered `purchase_price`:

- If `payment_method = 'cash'`: tolerance = **5%** of expected_total.
- If `payment_method = 'card'`: tolerance = **5% + card_premium_percentage**, because the card fee may or may not be baked into purchase_price depending on how the dealer wrote the receipt.

If `|expected_total - purchase_price|` exceeds the tolerance, the form shows a soft warning ("These numbers don't add up — double-check the spot rate or premium") with a "Save anyway" option. We **don't** block the save. We **don't** enforce this at the DB level — the user might be entering an old/incomplete record where the math is genuinely off.

---

## Table 5 — `sales`

Unchanged from Rev 1. One row per sold holding. UNIQUE on `holding_id` keeps "no partial sales in MVP."

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `holding_id` | `uuid` | NOT NULL, FK → `holdings.id` ON DELETE CASCADE, **UNIQUE** | |
| `sale_price` | `numeric(14, 2)` | NOT NULL, CHECK `>= 0` | |
| `sale_currency` | `text` | NOT NULL | |
| `sale_date` | `date` | NOT NULL | |
| `sold_to` | `text` | NULL | |
| `spot_rate_at_sale` | `numeric(14, 4)` | NULL | Per gram |
| `fees` | `numeric(14, 2)` | NOT NULL, DEFAULT `0`, CHECK `>= 0` | |
| `comments` | `text` | NULL | |
| `created_at` | `timestamptz` | NOT NULL, DEFAULT `now()` | |
| `updated_at` | `timestamptz` | NOT NULL, DEFAULT `now()`, ON UPDATE `now()` | |

**Indices:** PK + UNIQUE on `holding_id`.

---

## Table 6 — `price_history`

Append-only daily snapshots. **Per your answer:** the daily GoldAPI cron stores rates for **all** purities GoldAPI returns (24K, 22K, 21K, 18K, 14K, 10K for gold; .999 for silver). The dashboard's "live rate" lookup picks the row that matches the holding's purity.

Two sources still coexist: `goldapi` (system-wide, user_id NULL) and `manual` (per-user).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `metal` | `text` | NOT NULL, CHECK in (`'gold','silver'`) | |
| `purity` | `text` | NOT NULL | `'24K'`, `'22K'`, etc. for gold; `'999'` for silver. **Not nullable** because we now store all purities. |
| `currency` | `text` | NOT NULL | GoldAPI returns USD; manual entries use user's currency |
| `rate_per_gram` | `numeric(14, 4)` | NOT NULL, CHECK `>= 0` | |
| `source` | `text` | NOT NULL, CHECK in (`'goldapi','manual'`) | |
| `user_id` | `uuid` | NULL, FK → `users.id` ON DELETE CASCADE | Required when `manual`, NULL when `goldapi` |
| `fetched_at` | `timestamptz` | NOT NULL, DEFAULT `now()` | |
| `created_at` | `timestamptz` | NOT NULL, DEFAULT `now()` | |

**Check constraint:**
`(source = 'goldapi' AND user_id IS NULL) OR (source = 'manual' AND user_id IS NOT NULL)`

**Indices:**
- `(metal, purity, source, fetched_at DESC)` — the "latest live 22K gold rate" lookup
- `(user_id, metal, purity, fetched_at DESC) WHERE source = 'manual'` — partial index for "latest user manual rate"

No `updated_at` — rows are immutable.

---

## Table 7 — `uploaded_files` (REVISED in Rev 2)

Receipts now attach to **purchases**, not holdings — one receipt covers the whole order.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `purchase_id` | `uuid` | NOT NULL, FK → `purchases.id` ON DELETE CASCADE | Was `holding_id` in Rev 1 |
| `storage_path` | `text` | NOT NULL, UNIQUE | e.g. `user-<uid>/purchase-<pid>/<uuid>.jpg` |
| `filename` | `text` | NOT NULL | |
| `mime_type` | `text` | NOT NULL, CHECK in (`'image/jpeg','image/png','application/pdf'`) | |
| `size_bytes` | `integer` | NOT NULL, CHECK `> 0 AND <= 5242880` | 5 MB cap |
| `uploaded_at` | `timestamptz` | NOT NULL, DEFAULT `now()` | |

**Indices:** PK + `(purchase_id)` + UNIQUE on `storage_path`.

A purchase can have multiple files (e.g. front + back of receipt, or receipt + photo of items). Most will have 1.

---

## ER Diagram

```
users (1) ────< (1) portfolios (1) ────< (∞) purchases (1) ────< (∞) holdings (1) ──── (0..1) sales
                                                │
                                                └────< (∞) uploaded_files

users (1) ────< (∞) price_history       [source='manual']
                  price_history          [source='goldapi', user_id NULL]
```

---

## Math sanity check (with the new structure)

For an active holding:
```
current_rate_per_gram = (
    latest price_history row matching this holding's metal AND purity
    AND source matching user.default_pricing_mode
)

current_value = current_rate_per_gram × weight_grams × quantity
unrealized_pl = current_value - purchase_price
```

For a sold holding:
```
realized_pl = sale_price - (purchase_price + COALESCE(fees, 0))
```

For the dashboard:
```
total_value     = SUM(current_value)   over all active holdings
total_invested  = SUM(purchase_price)  over all holdings (active + sold)
unrealized_pl   = SUM(unrealized_pl)   over active holdings
realized_pl     = SUM(realized_pl)     over sold holdings
```

All in `users.preferred_currency`. Holdings in other currencies show as-is (MVP), Phase 2 adds conversion.

---

## Phase 2 — Currency conversion plan (for reference)

When we add cross-currency totals, the recommended free API is **`frankfurter.app`**:

- Free, no API key required
- Uses European Central Bank reference rates
- Supports historical rates (so a 2024 purchase can be valued at the 2024 rate)
- Reliable (used by many production apps)
- Daily updates, no rate-limit complications

We'd add a `currency_rates` table (similar structure to `price_history`) with daily ECB snapshots and convert at display time. Not in MVP.

---

## RLS posture summary

For each of the 7 tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
-- No policies. Default deny.
```

The FastAPI service uses Supabase's service role key, which **bypasses RLS by design**. The browser never gets the service role key. If the anon key is somehow used to query a table, it gets nothing back. This is purely defense-in-depth.

---

## Resolved decisions (Q&A archive)

| # | Question | Decision |
|---|---|---|
| 1 | How does the `users` row get created? | `POST /auth/sync` from frontend after Supabase signup |
| 2 | How is weight handled in the form? | Three columns: `weight_value` (user types), `weight_unit` (user picks: g/kg/oz), `weight_grams` (canonical) |
| 3 | Currency conversion in MVP? | **Deferred to Phase 2.** Recommended API: `frankfurter.app` (free, ECB rates) |
| 4 | Store all GoldAPI purities or just 24K? | All — per metal × per purity, daily |
| 5 | Metal CHECK constraint scope? | `'gold','silver'` only for MVP |
| 6 | `spot_rate_at_purchase` required? | Optional. When provided, form verifies `weight × spot × qty + premium ≈ purchase_price` and warns on mismatch (with card-premium tolerance when paid by card) |
| 7 | Multi-item purchases? | New `purchases` table; `holdings` are line items belonging to a purchase |
| 8 | `payment_method` field? | On `purchases` table: `'cash'` or `'card'`. Card adds `card_premium_percentage` (default 2.5%) |
| 9 | `'bullion'` as a form option? | Added to `holdings.form` CHECK list |

---

## What happens after you approve

I'll create:

1. `app/models/user.py` — `User`
2. `app/models/portfolio.py` — `Portfolio`
3. `app/models/purchase.py` — `Purchase`
4. `app/models/holding.py` — `Holding`
5. `app/models/sale.py` — `Sale`
6. `app/models/price_history.py` — `PriceHistory`
7. `app/models/uploaded_file.py` — `UploadedFile`
8. `alembic/versions/0001_initial.py` — initial migration (autogenerate, then hand-tune for `gen_random_uuid()`, partial indices, and the cross-column CHECK constraints)

Then `alembic upgrade head` against your Supabase DB.
