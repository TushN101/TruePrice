# Quick start

## 1. Start MongoDB

```bash
sudo docker run -d \
  --name mongodb \
  -p 27017:27017 \
  -v mongodb_data:/data/db \
  mongo:8
```

(Or install MongoDB locally — see https://www.mongodb.com/try/download/community)

## 2. Install Python dependencies

```bash
cd server

# Production only:
pip install -r requirements.txt

# Production + test/dev (includes mongomock, pytest):
pip install -r requirements-dev.txt
```

> **Note:** `mongomock` is in `requirements-dev.txt`, NOT
> `requirements.txt`.  It is used only by the test suite
> (`tests/conftest.py`) and is never installed in production.
> The production code uses `pymongo.MongoClient` directly.

## 3. Configure environment

```bash
cp ../.env.example .env
# Edit .env — at minimum change JWT_SECRET (must be ≥32 bytes)
```

## 4. Run the backend

```bash
cd server
python app.py
# → http://vm:5000  (or http://localhost:5000 for local testing)
```

> The extension is configured to call `http://vm:5000` by default.
> If your backend is at a different URL, update `API_BASE` in
> `extension/background.js` and `extension/popup.js`, and the
> `host_permissions` in `extension/manifest.json`.

## 5. Load the extension

1. Open `chrome://extensions` in Chrome/Brave/Edge.
2. Enable **Developer mode**.
3. Click **Load unpacked** → select the `extension/` directory.
4. Click the TruePrice icon → **Register**.
5. Visit an eBay product page (e.g. `https://www.ebay.com/itm/123456789`).
6. Click the TruePrice icon again to see the price history chart.

> **Debugging:** If observations aren't being sent, open the browser
> console (F12) on the eBay page and look for `[TruePrice]` log lines.
> Also check the service worker console (click "Service Worker" on the
> extension card in `chrome://extensions`).

## 6. Run tests

```bash
cd server
python -m pytest tests/ -v
# → 79 passed
```

Tests use mongomock — no live MongoDB required.

## 7. Run the simulation (tester.py)

```bash
cd server

# Interactive — lists products, you pick one
python tester.py

# Specify product and parameters
python tester.py --product 123456789 --days 7 --clients 100

# Clean all simulation data
python tester.py --clean
```

The simulation creates 100 clients (70 good, 15 imposters, 15 sleepers),
generates predated observations, computes hourly results, and prints
final reputations — showing whether imposters/sleepers were punished.
