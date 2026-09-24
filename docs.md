# TruePrice

> Crowdsourced price-history system for eBay — protects users from
> misleading "fake discount" claims by building reputation-weighted
> historical price records from real user observations.

TruePrice is a college/research-style project.  It is **not** a
production-scale commercial service.  The goal is to demonstrate a
complete pipeline: browser extension → Flask backend → MongoDB →
lazy hourly computation → reputation-weighted consensus → external
validation when the crowd isn't trusted enough → price-history chart
in the extension.

---

## Table of contents

1. [Selected platform](#1-selected-platform)
2. [Architecture](#2-architecture)
3. [Repository structure](#3-repository-structure)
4. [MongoDB design](#4-mongodb-design)
5. [How price-history computation works](#5-how-price-history-computation-works)
6. [How reputation works](#6-how-reputation-works)
7. [How external validation works](#7-how-external-validation-works)
8. [Environment variables](#8-environment-variables)
9. [Backend setup](#9-backend-setup)
10. [Extension installation](#10-extension-installation)
11. [How to test](#11-how-to-test)
12. [Simulation script (tester.py)](#12-simulation-script-testerpy)
13. [API reference](#13-api-reference)
14. [Known limitations](#14-known-limitations)

---

## 1. Selected platform

**eBay** (`https://www.ebay.com`).

### Why eBay over Amazon / Walmart / BestBuy

| Criterion | Amazon | **eBay** | Walmart | BestBuy |
|---|---|---|---|---|
| URL product ID | ASIN (clean) | `/itm/<numeric_id>` (cleanest) | `/ip/<slug>/<id>` | `/site/<slug>/<sku>` |
| Price extraction (extension) | `.a-price-whole` + fraction | `.x-price-primary` / `#prcIsum` | JSON-LD microdata | `.priceView__price` |
| Backend-side price validation | **Hard** (CAPTCHA, IP blocks) | **Easy** (server-rendered price) | Medium | Medium |
| Bot-detection difficulty | High | Low | Medium | Medium |
| College-project suitability | Low | **High** | Medium | Medium |

eBay wins on every axis that matters for this project: the item ID is
a clean numeric string in the URL, the price is rendered server-side
(so a simple `requests.get` + BeautifulSoup works for the validator),
and eBay's bot detection is far lighter than Amazon's.  The same
platform serves both the extension and the validator, simplifying the
implementation.

The extension and validator are **eBay-only**.  Supporting multiple
platforms is explicitly out of scope (brief §23).

---

## 2. Architecture

```
┌─────────────────┐     observations      ┌──────────────────────────┐
│  Browser        │ ───────────────────▶  │  Flask backend (app.py)  │
│  extension      │   POST /api/          │                          │
│  (eBay)         │   observations        │  ┌────────────────────┐  │
│                 │                       │  │  clientRegister    │  │
│  ┌───────────┐  │   history request     │  │  postHandler       │  │
│  │ content.  │  │ ───────────────────▶  │  │  fetchHandler      │  │
│  │ js        │  │   POST /api/history   │  │  (lazy compute)    │  │
│  └───────────┘  │                       │  └────────────────────┘  │
│  ┌───────────┐  │   ◀─────────────────  │                          │
│  │ popup.js  │  │   computed history    │  ┌────────────────────┐  │
│  │ (chart)   │  │                       │  │  core/ (pure)      │  │
│  └───────────┘  │                       │  │  • reputation.py   │  │
└─────────────────┘                       │  │  • consensus.py    │  │
                                          │  │  • history.py      │  │
                                          │  └────────────────────┘  │
                                          │  ┌────────────────────┐  │
                                          │  │  validators/       │  │
                                          │  │  • ebay_validator  │  │
                                          │  └─────────┬──────────┘  │
                                          └────────────┼─────────────┘
                                                       │
                                          ┌────────────▼─────────────┐
                                          │  MongoDB (5 collections) │
                                          │  clients                 │
                                          │  products                │
                                          │  observations (raw)      │
                                          │  hourlyResults (derived) │
                                          │  clientReputationHistory │
                                          └──────────────────────────┘
```

### Module boundaries

| Layer | Location | Responsibility |
|---|---|---|
| **Pure logic** | `server/core/` | Reputation update, price clustering, weighted consensus, per-hour computation. **No Flask, no MongoDB.** Fully unit-testable. |
| **Validators** | `server/validators/` | External price extraction from eBay. Decoupled from the core via a callable interface. |
| **MongoDB** | `server/util/databaseManager.py` | Connection management, collection accessors, index creation. |
| **Handlers** | `server/util/` | Request processing: registration, observation ingestion, lazy history computation + persistence. |
| **HTTP** | `server/app.py` | Flask routes, JWT auth, response shaping. |

---

## 3. Repository structure

```
TruePrice/
├── README.md                          ← this file
├── .env.example                       ← environment-variable template
├── .gitignore
├── LICENSE
│
├── extension/                         ← Chrome/Brave/Edge MV3 extension
│   ├── manifest.json                  ← eBay host permissions
│   ├── background.js                  ← service worker: auth, API calls
│   ├── content.js                     ← eBay page extraction (item ID, price)
│   ├── popup.html / popup.js          ← product-page popup with chart
│   ├── dashboard.html / dashboard.js  ← multi-product dashboard
│   ├── chart.js                       ← vendored Chart.js v4.5.1
│   └── logo.png
│
└── server/                            ← Flask backend
    ├── app.py                         ← routes, JWT setup
    ├── config.py                      ← env-driven configuration
    ├── requirements.txt               ← production dependencies
    ├── requirements-dev.txt           ← test dependencies (mongomock, pytest)
    ├── tester.py                      ← simulation script (imposters + sleepers)
    ├── pyproject.toml
    ├── reference.md                   ← quick-start commands
    │
    ├── core/                          ← PURE LOGIC (no Flask/Mongo)
    │   ├── __init__.py
    │   ├── reputation.py              ← update_reputation(), bounds, clamp
    │   ├── consensus.py               ← cluster_prices(), weighted_consensus()
    │   └── history.py                 ← compute_hour() — per-hour pipeline
    │
    ├── validators/                    ← external price validators
    │   ├── __init__.py
    │   ├── base.py                    ← PriceValidator ABC + ValidationResult
    │   └── ebay_validator.py          ← eBay HTTP fetch + parse
    │
    ├── util/                          ← Flask/MongoDB integration
    │   ├── __init__.py
    │   ├── databaseManager.py         ← connection, indexes, 5 collections
    │   ├── clientRegister.py          ← UUID + JWT registration
    │   ├── clientIpValidator.py       ← IP validation
    │   ├── postHandler.py             ← observation ingestion
    │   ├── fetchHandler.py            ← lazy history computation orchestrator
    │   └── logicHandler.py            ← DEPRECATED (kept for compat)
    │
    └── tests/                         ← 79 tests, all use mongomock
        ├── conftest.py                ← fixtures, mongomock injection
        ├── test_registerClient.py     ← auth + refresh flow
        ├── test_postData.py           ← observation ingestion
        ├── test_getData.py            ← end-to-end history + lazy compute
        ├── test_reputation.py         ← reputation bounds + updates
        ├── test_consensus.py          ← clustering + weighted median
        ├── test_history_computation.py← per-hour pipeline (with mock validator)
        └── test_validator.py          ← eBay validator (mocked HTTP)
```

---

## 4. MongoDB design

Five collections in a single database (default: `truePriceDb`):

### `clients`
```js
{
  _id:        "<uuid>",            // client UUID
  ipAddress:  "127.0.0.1",
  createdAt:  ISODate,
  reputation: 0.5                  // live reputation (latest across all hours)
}
```
Index: `ipAddress`.

### `products`
```js
{
  _id:          "<ebay-item-id>",  // eBay numeric item ID as _id
  platform:     "ebay",
  externalId:   "<ebay-item-id>",
  url:          "https://www.ebay.com/itm/...",
  title:        "Product Name",
  currency:     "USD",
  firstSeenAt:  ISODate,
  lastSeenAt:   ISODate
}
```
Indexes: `(platform, externalId)` unique, `url`.

### `observations` — **raw observations (source of truth)**
```js
{
  _id:         ObjectId,
  productId:   "<ebay-item-id>",
  clientId:    "<uuid>",
  price:       201.0,
  currency:    "USD",
  observedAt:  ISODate,            // server-set, never client-set
  clientIp:    "127.0.0.1"
}
```
Indexes: `(productId, observedAt)`, `(clientId, observedAt)`.

### `hourlyResults` — **computed per-hour results (derived)**
```js
{
  _id:                     ObjectId,
  productId:               "<ebay-item-id>",
  hour:                    ISODate,        // top-of-hour UTC
  canonicalPrice:          201.0,
  currency:                "USD",
  confidence:              0.93,
  observationCount:        150,            // raw count (before dedup)
  clientCount:             120,            // unique clients after dedup
  validationPerformed:     false,
  validatorPrice:          null,
  clientReputationsBefore: { clientId: rep },  // snapshot for audit
  clientReputationsAfter:  { clientId: rep },
  correctClients:          ["cid1", "cid2"],
  incorrectClients:        ["cid3"],
  clusterCount:            2,
  winningClusterSize:      148,
  computedAt:              ISODate
}
```
Index: `(productId, hour)` **unique** — one document per product-hour pair.

### `clientReputationHistory` — **chronological correctness log**
```js
{
  _id:                ObjectId,
  clientId:           "<uuid>",
  productId:          "<ebay-item-id>",
  hour:               ISODate,
  asOfHour:           ISODate,           // same as `hour` — the hour whose
                                        // computation produced this record
  previousReputation: 0.5,
  newReputation:      0.55,
  reason:             "correct",        // or "incorrect"
  delta:              0.05,
  recordedAt:         ISODate
}
```
Index: `(clientId, asOfHour desc)` — enables efficient "reputation as
of just before hour H" queries.

### Why separate `observations` and `hourlyResults`?

Raw observations are the **source of truth**.  Computed hourly results
are **derived/materialised** data.  They live in separate collections
so that:
* recomputation is possible (delete `hourlyResults`, recompute from `observations`);
* each hour is a queryable, updateable document (no giant arrays);
* the two concepts are never confused (brief §7).

---

## 5. How price-history computation works

### Lazy materialisation (brief §8, §10)

The system does **not** compute every product every hour in the
background.  Computation happens on-demand when a client requests
history:

1. Client requests history for `productId`.
2. `fetchHandler.fetch_history(productId)` loads all observations for
   that product from MongoDB.
3. It finds which hours already have a computed result in
   `hourlyResults`.
4. It identifies **missing** hours (those with observations but no
   result).
5. Missing hours are processed **chronologically** (oldest first).
6. Each computed result is persisted to `hourlyResults`.
7. The full history (existing + newly computed) is returned.

If a product has 30 days of uncomputed history (720 hours), the first
request may compute all 720.  Subsequent requests reuse the stored
results.  `MAX_HOURS_PER_REQUEST` (default 720) caps the work per
request.

### Per-hour pipeline (brief §15)

For each hour, `core/history.py:compute_hour()` executes:

```
1. Load all observations for the hour
2. Dedupe to one effective observation per client (latest by observedAt)
3. Determine price clusters (relative tolerance)
4. Determine reputation-weighted consensus
5. Determine canonical / reference price
6. Determine whether external validation is required
   (trusted-clients ratio < TRUSTED_CLIENT_THRESHOLD)
7. If validation is required, call the validator → use its price
8. Classify each observation as correct / incorrect (relative tolerance)
9. Update client reputations  ← AFTER consensus, never before
10. Build and return the HourResult
```

Reputations are updated **after** consensus so that processing order
within an hour cannot influence the consensus (brief §18).

### Price clustering (brief §11–§12)

Prices are grouped into clusters using **relative tolerance**:
```
(p2 - p1) / p1 <= PRICE_TOLERANCE
```

Clustering is single-linkage on the sorted price sequence: walk
ascending, start a new cluster only when the gap from the preceding
price exceeds the tolerance.  This means `201, 202, 203` (with 2 %
tolerance) form one cluster, while `201, 350` form two.

### Reputation-weighted consensus (brief §12–§13)

Each cluster's **support** = sum of participating client reputations.
The cluster with the highest support wins.  Ties are broken by higher
client count, then by lower representative price (deterministic).

The winning cluster's representative price is the **weighted median**
of its observations (weighted by client reputation) — less sensitive
to outliers than a weighted mean.

**Confidence** = winning support / total support across all clusters.

---

## 6. How reputation works

### Bounds and initial value

```
REPUTATION_INITIAL = 0.5   (neutral)
REPUTATION_MIN     = 0.1
REPUTATION_MAX     = 0.9
```

A client is **trusted** when `reputation > 0.5`.

### Update rule

```
correct   → reputation += REPUTATION_REWARD   (default +0.05)
incorrect → reputation -= REPUTATION_PENALTY  (default −0.05)
```

Result is clamped to `[REPUTATION_MIN, REPUTATION_MAX]`.

Reward and penalty are independently configurable — you can make
penalty larger than reward if you want trust to be hard to build and
easy to lose.

### Chronological correctness (brief §9, §11) — CRITICAL

A client's reputation at hour H must **not** include information
learned at hour H or any later hour.  This is enforced via the
`clientReputationHistory` collection:

1. When computing hour H, for each participating client, query
   `clientReputationHistory` for the latest record with
   `asOfHour < H`.  This **excludes** records from hour H and later.
2. If no such record exists, the client's first participation is at
   hour H or later → use the **initial** reputation (0.5).

   We deliberately do **NOT** fall back to `clients.reputation`
   because that field may reflect computations from *later* hours
   (future-information leakage).

3. After computing hour H, insert a `clientReputationHistory` record
   with `asOfHour = H`.
4. Update `clients.reputation` **only if** no later computation exists
   for that client (i.e., this hour is the client's new latest).

This design is tested explicitly in
`test_getData.py::test_chronological_reputation_no_future_leak`.

### Persistence across hours and products

Reputation is **global per client** — it persists across hours and
across products.  A client that builds trust on product A carries
that trust to product B.  The `clientReputationHistory` log records
every change with its `asOfHour`, enabling correct reconstruction at
any historical point.

### Multiple observations from the same client (brief §16)

**Policy: one effective observation per client per hour** — if a
client submits multiple times in the same hour, only the **latest**
(by `observedAt`) is used for consensus.  This prevents a single
client from dominating by spamming.  All raw observations are still
stored for audit/replay.

---

## 7. How external validation works

### When validation is triggered

The system checks the **trusted-population ratio** among participating
clients in the current hour:

```
trusted_ratio = (clients with reputation > 0.5) / total participating clients

if trusted_ratio >= TRUSTED_CLIENT_THRESHOLD (default 0.6):
    use internal weighted consensus
else:
    perform external validation
```

### What the validator does

`validators/ebay_validator.py:EbayValidator`:

1. Takes a product URL (or bare eBay item ID).
2. Fetches the product page via `requests.get` (server-side rendered
   HTML — no JavaScript execution).
3. Extracts the price from the first matching selector:
   * `div.x-price-primary` (modern layout)
   * `div#prcIsum` / `span#prcIsum` (legacy layout)
   * `meta[itemprop=price]` (microdata fallback)
4. Parses the price text (strips currency symbols, handles commas).
5. Returns a `ValidationResult` with `{ok, price, currency, url, error}`.

### How the result is used

When validation succeeds:
* `canonicalPrice` is set to the validator's price (overrides consensus).
* `validationPerformed = true`, `validatorPrice` is recorded.
* Correctness is determined relative to the validator's price.

When validation fails (network error, price not found):
* The system falls back to internal consensus and logs a warning.
* `validationPerformed = false`.

### Decoupling

The core computation engine (`core/history.py`) accepts the validator
as a **callable** (`Callable[[str], dict]`), not as a concrete class.
This means:
* Tests inject a mock validator without importing the real one.
* A different platform's validator can be swapped in without touching
  the core logic.

---

## 8. Environment variables

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB` | `truePriceDb` | Database name |
| `JWT_SECRET` | `dev-secret-change-in-production` | **Change this!** JWT signing key |
| `JWT_ACCESS_EXPIRES` | `3600` | Access token lifetime (seconds) |
| `JWT_REFRESH_EXPIRES` | `2592000` | Refresh token lifetime (seconds) |
| `REPUTATION_INITIAL` | `0.5` | Initial client reputation |
| `REPUTATION_MIN` | `0.1` | Minimum reputation |
| `REPUTATION_MAX` | `0.9` | Maximum reputation |
| `REPUTATION_REWARD` | `0.05` | Reputation increase on correct |
| `REPUTATION_PENALTY` | `0.05` | Reputation decrease on incorrect |
| `PRICE_TOLERANCE` | `0.02` | Relative price tolerance (2 %) |
| `TRUSTED_CLIENT_THRESHOLD` | `0.6` | Min trusted-client ratio (60 %) |
| `HISTORY_RETENTION_DAYS` | `30` | History retention window |
| `MAX_HOURS_PER_REQUEST` | `720` | Cap on hours computed per request |
| `FLASK_HOST` | `0.0.0.0` | Flask bind host |
| `FLASK_PORT` | `5000` | Flask port |
| `FLASK_DEBUG` | `false` | Flask debug mode |
| `PLATFORM` | `ebay` | Active platform (only `ebay` supported) |
| `EBAY_BASE_URL` | `https://www.ebay.com` | eBay base URL |
| `VALIDATOR_USER_AGENT` | `TruePrice-Validator/1.0 ...` | Validator User-Agent |
| `VALIDATOR_TIMEOUT` | `10` | Validator HTTP timeout (seconds) |

---

## 9. Backend setup

### Prerequisites

* Python 3.10+
* MongoDB 4.4+ (local or remote)

### Install MongoDB (Docker)

```bash
sudo docker run -d \
  --name mongodb \
  -p 27017:27017 \
  -v mongodb_data:/data/db \
  mongo:8
```

### Install Python dependencies

```bash
cd server
python -m pip install -r requirements.txt
```

### Configure

```bash
cp ../.env.example .env
# Edit .env — at minimum, change JWT_SECRET
```

### Run

```bash
cd server
python app.py
# → Backend running on http://localhost:5000
```

Health check:
```bash
curl http://localhost:5000/
# → {"name":"TruePrice API","status":"ok"}
```

---

## 10. Extension installation

1. Open Chrome / Brave / Edge.
2. Navigate to `chrome://extensions`.
3. Enable **Developer mode** (top-right toggle).
4. Click **Load unpacked**.
5. Select the `extension/` directory.
6. The TruePrice icon should appear in your toolbar.

### First use

1. Click the TruePrice icon.
2. Click **Register** — this creates an anonymous client and stores
   the JWT in `chrome.storage.local`.
3. Navigate to an eBay product page (e.g.
   `https://www.ebay.com/itm/123456789`).
4. The extension automatically extracts the item ID and price, then
   submits an observation (once per item per hour).
5. Click the TruePrice icon again to see the price-history chart.

### Dashboard

Click **Dashboard** in the popup to see all tracked products with
mini charts.

---

## 11. How to test

Tests use **mongomock** (in-memory MongoDB substitute) — no live
MongoDB or network access required.  Mongomock is in
`requirements-dev.txt`, **not** `requirements.txt`, so it is never
installed in production.

```bash
cd server

# Install test dependencies (also installs production deps)
pip install -r requirements-dev.txt

# Run tests
python -m pytest tests/ -v
```

Expected output:
```
79 passed in <1s
```

### Test coverage

| File | What it tests |
|---|---|
| `test_registerClient.py` | Registration, valid/invalid auth, refresh flow, access-vs-refresh token separation |
| `test_postData.py` | Observation ingestion: valid, missing fields, non-numeric price, string coercion, duplicates |
| `test_reputation.py` | Initial value, reward, penalty, lower/upper bounds, clamping, chaining, asymmetric config |
| `test_consensus.py` | Clustering (close prices, separated, chaining, empty), weighted median, weighted consensus, tie-breaking |
| `test_history_computation.py` | Per-hour pipeline: dedup, consensus, validation threshold, validation failure fallback, correctness, reputation-after-consensus, bounds |
| `test_getData.py` | End-to-end: unknown product, single hour, reuse of computed hours, missing hours, **chronological no-future-leak**, independent client reputations |
| `test_validator.py` | `parse_price_text` (USD/GBP/EUR/INR), `extract_item_id`, mocked HTTP for modern/legacy/meta/no-price/error, bare-ID expansion, `as_dict()` shape |

---

## 12. Simulation script (tester.py)

Since this is a college project, you won't have thousands of real users
submitting prices.  `tester.py` simulates the complete reputation system
with 100 synthetic clients to verify the core logic works.

### What it does

1. Lists all products in the database — you select one (or specify with `--product`).
2. Creates **100 simulated clients**:
   - **70 good clients** — post correct prices (within ±2 % of the true price)
   - **15 true imposters** — post wildly wrong prices (30 %–300 % of true price) from the start
   - **15 sleeper cells** — post correct prices for the first 70 % of days, then start inflating by 30 % (simulating a "fake discount" attack)
3. Generates **predated observations** (1–7 days ago) for each client.
4. Computes all hourly results **chronologically** using the real `compute_hour` pipeline, with a mock validator that returns the true historical price for each hour.
5. Prints:
   - All **30 imposters + sleepers** with their final reputations and whether they were **PUNISHED** ✓ or **NOT PUNISHED** ✗
   - The **price history** (true price vs computed canonical price) showing whether imposters corrupted any hours
   - A **verdict**: did the system catch the bad actors?

### Usage

```bash
cd server

# Interactive — lists products, you pick one
python tester.py

# Specify product ID directly
python tester.py --product 123456789

# Custom parameters (default: 7 days, 100 clients)
python tester.py --days 14 --clients 200

# Clean all simulation data
python tester.py --clean
```

### What to look for

- **Imposters** should be punished quickly (reputation drops toward 0.1) — their wildly wrong prices are rejected by the validator and consensus.
- **Sleepers** are harder to catch — they build trust first, then betray it. With enough days, their reputation should start dropping after activation.
- **Corrupted hours** — hours where the canonical price deviates more than `PRICE_TOLERANCE` from the true price. These typically happen when only 1–2 clients observe in an hour and one of them is a sleeper.
- After running, **open the extension** to see the price history chart — it should show the true price trajectory, not the imposter-inflated prices.

### How it connects to the real system

`tester.py` writes directly to MongoDB (same collections as the real
backend), then calls `core/history.py:compute_hour()` — the **same
function** the backend uses.  Results are persisted to `hourlyResults`
and `clientReputationHistory` just like real computation.  When you
later open the extension, it calls `/api/history`, which finds all hours
already computed and returns them immediately — no recomputation needed.

The script tags all its data with `simTag: "tester_simulation"` so it
can be cleaned up with `--clean` without affecting real data.

---

## 13. API reference

All authenticated routes require `Authorization: Bearer <accessToken>`.
All authenticated responses include a fresh `refreshToken` for rotation.

### `POST /api/registerClient`
Anonymous registration. No auth required.

**Response 200:**
```json
{
  "status": "success",
  "message": "Client registered successfully",
  "clientId": "<uuid>",
  "accessToken": "<jwt>",
  "refreshToken": "<jwt>"
}
```
Also sets an `access_token` HTTP-only cookie.

### `POST /api/refresh`
Exchange a refresh token for a new access+refresh pair.

**Header:** `Authorization: Bearer <refreshToken>`

**Response 200:**
```json
{
  "status": "success",
  "accessToken": "<jwt>",
  "refreshToken": "<jwt>"
}
```

### `POST /api/observations`
Store a raw price observation.

**Body:**
```json
{
  "productId": "123456789",
  "price": 201.50,
  "currency": "USD",
  "url": "https://www.ebay.com/itm/123456789",
  "title": "Product Name"
}
```

**Response 200:**
```json
{
  "status": "success",
  "message": "Observation stored",
  "refreshToken": "<jwt>"
}
```

### `POST /api/history`
Get computed price history (lazily computes missing hours).

**Body:**
```json
{
  "productId": "123456789"
}
```

**Response 200 (success):**
```json
{
  "status": "success",
  "productId": "123456789",
  "currency": "USD",
  "history": [
    {
      "hour": "2026-09-23T10:00:00+00:00",
      "canonicalPrice": 201.0,
      "currency": "USD",
      "confidence": 0.93,
      "observationCount": 150,
      "clientCount": 120,
      "validationPerformed": false,
      "validatorPrice": null,
      "computedAt": "2026-09-23T11:00:05+00:00"
    }
  ],
  "refreshToken": "<jwt>"
}
```

**Response 200 (missing — no observations yet):**
```json
{
  "status": "missing",
  "message": "Unknown product — no observations yet",
  "refreshToken": "<jwt>"
}
```

---

## 14. Known limitations

* **No Redis / Prometheus / Grafana** — intentionally omitted per the
  current brief.  The architecture is clean enough to add them later.
* **No rate limiting** — a client could spam observations.  Redis-based
  rate limiting would be the natural addition.
* **No distributed locking** — if two requests trigger computation for
  the same product-hour simultaneously, both will compute (the unique
  index on `(productId, hour)` makes the upsert idempotent, but
  `clientReputationHistory` could get duplicate entries).  For a
  college project with single-user testing this is acceptable.
* **eBay DOM changes** — the validator's CSS selectors are based on
  2024-2025 eBay structure.  If eBay changes their layout, the
  selectors in `validators/ebay_validator.py` need updating.
* **No JavaScript execution in the validator** — the validator uses
  plain `requests.get` + BeautifulSoup.  If eBay moves the price
  behind JS rendering, the validator would need a headless browser.
  For item pages this is currently not an issue.
* **Extension per-hour throttle** — the extension submits at most one
  observation per item per hour.  This is intentional (prevents a
  single user from flooding an hour) but means very-recent prices may
  take up to an hour to appear in history.
* **Reputation is global per client** — a client trusted on product A
  is trusted on product B.  This is the intended design (brief §10)
  but may not suit all scenarios.
