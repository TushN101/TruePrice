"""
tester.py — TruePrice simulation script.

Simulates 100 clients observing a product over the past N days:
  - 70 good clients:  post correct prices (within 1-2 % tolerance)
  - 15 true imposters: post wildly wrong prices from the start
  - 15 sleeper cells:  post correct prices initially, then inflate
                       to simulate a "fake discount" attack

All observations are predated (1 day ago, 2 days ago, ...) to test
historical computation and chronological reputation correctness.

After simulation, the script:
  1. Prints all 30 imposters + sleepers with their final reputations
  2. Shows whether each was punished (reputation < 0.5)
  3. Prints the price history (true price vs computed canonical price)
     so you can verify imposters did NOT corrupt the canonical price

The simulation uses a mock validator that returns the true price for
each hour.  This stands in for the eBay validator — which can only
return the *current* price, not historical prices.

Usage:
    python tester.py                          # interactive product selection
    python tester.py --product 123456789      # specify product ID
    python tester.py --days 7 --clients 100   # custom parameters
    python tester.py --clean                  # remove all simulation data

After running, open the TruePrice extension popup on the product page
(or the dashboard) to see the computed price history chart.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Ensure the server directory is on the Python path so we can import
# config, core.*, util.*, validators.*.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from core.consensus import PricedObservation
from core.history import HourComputationConfig, compute_hour
from core.reputation import ReputationConfig
from util.databaseManager import (
    clientReputationHistory,
    clients,
    hourlyResults,
    init_db,
    observations,
    products,
)


# ─── Simulation parameters ──────────────────────────────────────────────

SIM_TAG = "tester_simulation"       # marks clients/observations created by this script

DEFAULT_DAYS = 7
DEFAULT_CLIENTS = 100
BASE_PRICE = 200.0
DAILY_DRIFT = 0.01                   # ±1 % per day

# --- Behaviour model (matches reference TrueTest script) ---------------
# Good clients (80 % of population):
#   - 80 % of the time: submit price within GOOD_NOISE of the true price
#   - 20 % of the time: submit a wrong price (GOOD_WRONG_RATE) — humans
#     make mistakes, the system must tolerate this.
GOOD_NOISE = 0.02                    # ±2 % noise on correct good-client observations
GOOD_WRONG_RATE = 0.20              # 20 % of good-client observations are wrong
GOOD_WRONG_RANGE = (0.10, 0.50)    # wrong by 10-50 % (outside tolerance)

# Imposters (15 % of population):
#   - 50 % of the time: submit a wildly wrong price
#   - 50 % of the time: accidentally agree with the true price
#     (This mirrors the reference script's `rng.random() < 0.5`.)
IMPOSTER_WRONG_RATE = 0.50
IMPOSTER_RANGE = (0.30, 3.00)      # 30 %-300 % of true price when wrong

# Sleepers (15 % of population — separate from imposters):
#   - Before activation: behave like good clients (with 20 % wrong)
#   - After activation:  always inflate by SLEEPER_INFLATION (fake discount)
SLEEPER_INFLATION = 0.30            # +30 % inflation when activated
SLEEPER_ACTIVATE_RATIO = 0.70       # activate at 70 % of sim period

# Participation model (matches reference wantParticipateFactor):
# Each client has a PARTICIPATE_RATE chance of submitting an observation
# in any given hour.  Not all clients see the product every hour.
PARTICIPATE_RATE = 0.70


# ─── Helpers ────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _hour_floor(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


# ─── Product selection ─────────────────────────────────────────────────

def list_products():
    """List all product IDs in the database (real + simulated)."""
    return list(products().find({}, {"_id": 1, "title": 1}).sort("title", 1))


def select_product_interactive():
    """Let the user pick a product from the DB."""
    prods = list_products()
    if not prods:
        print("\nNo products found in the database.")
        print("Browse eBay product pages with the extension first,")
        print("or use --product <id> to create a new one.")
        return None

    print("\n" + "=" * 60)
    print("Available products:")
    print("-" * 60)
    for i, p in enumerate(prods, 1):
        title = (p.get("title") or "(no title)")[:50]
        print(f"  {i:>3}. {p['_id']:<20} {title}")
    print("=" * 60)

    while True:
        choice = input("\nSelect product (number): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(prods):
                return prods[idx]["_id"]
        except ValueError:
            pass
        print("Invalid choice. Try again.")


# ─── Cleanup ────────────────────────────────────────────────────────────

def clean_all_simulation_data():
    """Remove ALL data created by previous simulation runs."""
    print("\nCleaning all simulation data...")

    # Find simulated client IDs
    sim_clients = list(clients().find({"simTag": SIM_TAG}, {"_id": 1}))
    sim_client_ids = [c["_id"] for c in sim_clients]

    deleted = {
        "clients": clients().delete_many({"simTag": SIM_TAG}).deleted_count,
        "observations": observations().delete_many({"simTag": SIM_TAG}).deleted_count,
        "hourlyResults": hourlyResults().delete_many({"simTag": SIM_TAG}).deleted_count,
    }
    if sim_client_ids:
        deleted["reputationHistory"] = clientReputationHistory().delete_many(
            {"clientId": {"$in": sim_client_ids}},
        ).deleted_count
    else:
        deleted["reputationHistory"] = 0

    print(f"  Deleted: {deleted}")


def clean_product_data(product_id):
    """Remove simulation data for a specific product."""
    sim_clients = list(clients().find({"simTag": SIM_TAG}, {"_id": 1}))
    sim_client_ids = [c["_id"] for c in sim_clients]

    observations().delete_many({"productId": product_id, "simTag": SIM_TAG})
    hourlyResults().delete_many({"productId": product_id, "simTag": SIM_TAG})
    if sim_client_ids:
        clientReputationHistory().delete_many({
            "clientId": {"$in": sim_client_ids},
            "productId": product_id,
        })
    clients().delete_many({"simTag": SIM_TAG})
    print(f"  Cleaned simulation data for product {product_id}")


# ─── Client generation ─────────────────────────────────────────────────

def generate_clients(n_clients):
    """Create n_clients client documents in MongoDB.

    Distribution (brief §4):
      - 70 % good clients
      - 15 % true imposters (bad from the start)
      - 15 % sleeper cells (good first, turn bad later)

    Returns (all_ids, imposter_ids, sleeper_ids, good_ids).
    """
    n_imposters = int(n_clients * 0.15)
    n_sleepers = int(n_clients * 0.15)
    n_good = n_clients - n_imposters - n_sleepers

    all_ids = []
    imposter_ids = []
    sleeper_ids = []
    good_ids = []

    now = _now()

    for i in range(n_clients):
        cid = str(uuid.uuid4())
        all_ids.append(cid)

        if i < n_imposters:
            role = "imposter"
            imposter_ids.append(cid)
        elif i < n_imposters + n_sleepers:
            role = "sleeper"
            sleeper_ids.append(cid)
        else:
            role = "good"
            good_ids.append(cid)

        clients().insert_one({
            "_id": cid,
            "ipAddress": f"10.{i // 256}.{i % 256}.1",
            "createdAt": now - timedelta(days=DEFAULT_DAYS + 1),
            "reputation": config.reputation_initial,
            "simTag": SIM_TAG,
            "role": role,
        })

    print(f"  Created {n_clients} clients: "
          f"{n_good} good, {n_imposters} imposters, {n_sleepers} sleepers")
    return all_ids, imposter_ids, sleeper_ids, good_ids


# ─── Price trajectory ───────────────────────────────────────────────────

def generate_price_trajectory(days, seed=42):
    """Generate a true price for each day of the simulation.

    Returns {day_index: true_price} where day_index 0 = oldest,
    days-1 = today.
    """
    rng = random.Random(seed)
    trajectory = {}
    price = BASE_PRICE
    for day in range(days):
        drift = rng.uniform(-DAILY_DRIFT, DAILY_DRIFT)
        price = round(price * (1 + drift), 2)
        trajectory[day] = price
    return trajectory


# ─── Observation generation ────────────────────────────────────────────

def generate_observations(
    product_id,
    all_ids,
    imposter_ids,
    sleeper_ids,
    good_ids,
    trajectory,
    days,
):
    """Generate predated observations for all clients and insert into MongoDB.

    Participation model (matches reference wantParticipateFactor):
    For each hour in the simulation window, each client has a
    PARTICIPATE_RATE (70 %) chance of submitting one observation.
    This models real-world behaviour — not every user sees the product
    every hour.

    Returns {hour: [PricedObservation, ...]} grouped by top-of-hour.
    """
    rng = random.Random(42)
    now = _now()
    sleeper_activate_day = int(days * SLEEPER_ACTIVATE_RATIO)

    obs_by_hour = defaultdict(list)

    # Build a list of all hours in the simulation window (oldest first).
    total_hours = days * 24
    sim_start = now - timedelta(hours=total_hours - 1)

    # Pre-compute the true price for each hour based on the day it falls in.
    hour_to_true_price = {}
    for h_offset in range(total_hours):
        hour_dt = sim_start.replace(
            minute=0, second=0, microsecond=0,
        ) + timedelta(hours=h_offset)
        days_ago = (now - hour_dt).days
        day_key = max(0, min(days - 1, days - 1 - days_ago))
        if day_key in trajectory:
            hour_to_true_price[hour_dt] = trajectory[day_key]

    for client_id in all_ids:
        is_imposter = client_id in imposter_ids
        is_sleeper = client_id in sleeper_ids

        for hour_dt, true_price in hour_to_true_price.items():
            # Participation check — 70 % chance this client observes this hour.
            if rng.random() >= PARTICIPATE_RATE:
                continue

            # Determine the simulation "day" for sleeper activation logic.
            days_ago = (now - hour_dt).days
            day = max(0, min(days - 1, days - 1 - days_ago))

            # Random minute within the hour.
            obs_time = hour_dt.replace(
                minute=rng.randint(0, 59),
                second=rng.randint(0, 59),
            )

            if is_imposter:
                # True imposter: 50 % wildly wrong, 50 % accidentally right
                if rng.random() < IMPOSTER_WRONG_RATE:
                    factor = rng.uniform(*IMPOSTER_RANGE)
                    price = round(true_price * factor, 2)
                else:
                    noise = rng.uniform(-GOOD_NOISE, GOOD_NOISE)
                    price = round(true_price * (1 + noise), 2)
            elif is_sleeper and day >= sleeper_activate_day:
                # Sleeper activated: always inflate (fake-discount attack)
                price = round(true_price * (1 + SLEEPER_INFLATION), 2)
            else:
                # Good client (or sleeper before activation):
                # 80 % correct (within noise), 20 % wrong (human error)
                if rng.random() < GOOD_WRONG_RATE:
                    wrong_factor = rng.uniform(*GOOD_WRONG_RANGE)
                    sign = rng.choice([-1, 1])
                    price = round(true_price * (1 + sign * wrong_factor), 2)
                else:
                    noise = rng.uniform(-GOOD_NOISE, GOOD_NOISE)
                    price = round(true_price * (1 + noise), 2)

            observations().insert_one({
                "productId": product_id,
                "clientId": client_id,
                "price": price,
                "currency": "USD",
                "observedAt": obs_time,
                "clientIp": "10.0.0.1",
                "simTag": SIM_TAG,
            })

            obs_by_hour[hour_dt].append(PricedObservation(
                clientId=client_id, price=price, observedAt=obs_time,
            ))

    total = sum(len(v) for v in obs_by_hour.values())
    print(f"  Generated {total} observations across {len(obs_by_hour)} hours")
    return obs_by_hour


# ─── Reputation loading (chronological correctness) ────────────────────

def get_reps_before(client_ids, hour):
    """Get each client's reputation as of just before ``hour``.

    Queries ``clientReputationHistory`` for the latest record with
    ``asOfHour < hour``.  Falls back to the initial reputation if no
    record exists.  We deliberately do NOT use ``clients.reputation``
    because that field may include changes from later hours.
    """
    reps = {}
    for cid in client_ids:
        rec = clientReputationHistory().find_one(
            {"clientId": cid, "asOfHour": {"$lt": hour}},
            sort=[("asOfHour", -1)],
        )
        reps[cid] = rec["newReputation"] if rec else config.reputation_initial
    return reps


# ─── Result persistence ────────────────────────────────────────────────

def persist_result(product_id, result, currency):
    """Persist a ``HourResult`` to MongoDB (hourlyResults + reputation history)."""
    now = _now()

    hourlyResults().update_one(
        {"productId": product_id, "hour": result.hour},
        {"$set": {
            "productId": product_id,
            "hour": result.hour,
            "canonicalPrice": result.canonical_price,
            "currency": currency,
            "confidence": result.confidence,
            "observationCount": result.observation_count,
            "clientCount": result.client_count,
            "validationPerformed": result.validation_performed,
            "validatorPrice": result.validator_price,
            "clientReputationsBefore": result.client_reputations_before,
            "clientReputationsAfter": result.client_reputations_after,
            "correctClients": result.correct_clients,
            "incorrectClients": result.incorrect_clients,
            "clusterCount": result.cluster_count,
            "winningClusterSize": result.winning_cluster_size,
            "computedAt": now,
            "simTag": SIM_TAG,
        }},
        upsert=True,
    )

    for cid, rep_after in result.client_reputations_after.items():
        rep_before = result.client_reputations_before.get(
            cid, config.reputation_initial,
        )
        reason = "correct" if cid in result.correct_clients else "incorrect"

        later = clientReputationHistory().find_one(
            {"clientId": cid, "asOfHour": {"$gt": result.hour}},
            projection={"_id": 1},
        )
        is_latest = later is None

        clientReputationHistory().insert_one({
            "clientId": cid,
            "productId": product_id,
            "hour": result.hour,
            "asOfHour": result.hour,
            "previousReputation": rep_before,
            "newReputation": rep_after,
            "reason": reason,
            "delta": rep_after - rep_before,
            "recordedAt": now,
        })

        if is_latest:
            clients().update_one(
                {"_id": cid},
                {"$set": {"reputation": rep_after}},
            )


# ─── Main simulation ───────────────────────────────────────────────────

def run_simulation(product_id, days, n_clients):
    """Run the full simulation for a product."""
    print("\n" + "=" * 60)
    print(f"SIMULATION: product={product_id}, days={days}, clients={n_clients}")
    print("=" * 60)

    # 1 — Clean previous simulation data for this product
    print("\n1. Cleaning previous simulation data...")
    clean_product_data(product_id)

    # 2 — Ensure product exists
    product = products().find_one({"_id": product_id})
    if not product:
        products().insert_one({
            "_id": product_id,
            "platform": "ebay",
            "externalId": product_id,
            "url": f"https://www.ebay.com/itm/{product_id}",
            "title": "Simulated Product",
            "currency": "USD",
            "firstSeenAt": _now(),
            "lastSeenAt": _now(),
        })
        product = products().find_one({"_id": product_id})
        print(f"  Created product record for {product_id}")
    currency = product.get("currency", "USD")
    product_url = product.get("url")

    # 3 — Generate clients
    print("\n2. Generating clients...")
    all_ids, imposter_ids, sleeper_ids, good_ids = generate_clients(n_clients)

    # 4 — Generate price trajectory
    print("\n3. Generating price trajectory...")
    trajectory = generate_price_trajectory(days)
    print(f"  True price range: ${min(trajectory.values()):.2f} – ${max(trajectory.values()):.2f}")
    for day, price in sorted(trajectory.items()):
        days_ago = days - 1 - day
        print(f"    Day {day} ({days_ago}d ago): ${price:.2f}")

    # 5 — Generate observations
    print("\n4. Generating predated observations...")
    obs_by_hour = generate_observations(
        product_id, all_ids, imposter_ids, sleeper_ids, good_ids,
        trajectory, days,
    )

    # 6 — Compute hours chronologically
    print("\n5. Computing hourly results chronologically...")
    rep_cfg = ReputationConfig(
        initial=config.reputation_initial,
        minimum=config.reputation_min,
        maximum=config.reputation_max,
        reward=config.reputation_reward,
        penalty=config.reputation_penalty,
        strength_factor=config.reputation_strength_factor,
    )
    hour_cfg = HourComputationConfig(
        tolerance=config.price_tolerance,
        trusted_threshold=config.trusted_client_threshold,
        reputation=rep_cfg,
        validation_random_rate=config.validation_random_rate,
        validation_min_observations=config.validation_min_observations,
    )

    # Build a mock validator that returns the true price for each hour.
    # The real eBay validator can only return the *current* price; for
    # predated hours we need the historical true price.
    hour_to_true_price = {}
    now = _now()
    for hour in obs_by_hour:
        days_ago = (now - hour).days
        day_key = max(0, min(days - 1, days - 1 - days_ago))
        if day_key in trajectory:
            hour_to_true_price[hour] = trajectory[day_key]

    class _MockValidator:
        def __init__(self):
            self.current_hour = None

        def __call__(self, url):
            price = hour_to_true_price.get(self.current_hour)
            if price is not None:
                return {"ok": True, "price": price, "currency": "USD"}
            return {"ok": False, "price": None, "error": "no true price for hour"}

    mock_validator = _MockValidator()

    sorted_hours = sorted(obs_by_hour.keys())
    total = len(sorted_hours)

    for i, hour in enumerate(sorted_hours):
        hour_obs = obs_by_hour[hour]
        client_ids = list({o.clientId for o in hour_obs})
        reps_before = get_reps_before(client_ids, hour)

        mock_validator.current_hour = hour
        result = compute_hour(
            hour=hour,
            observations=hour_obs,
            client_reputations_before=reps_before,
            cfg=hour_cfg,
            validator=mock_validator,
            product_url=product_url,
        )
        persist_result(product_id, result, currency)

        if (i + 1) % 10 == 0 or i == 0 or i == total - 1:
            print(f"  [{i+1:>3}/{total}] {hour.strftime('%Y-%m-%d %H:00')} "
                  f"canonical=${result.canonical_price:>8.2f}  "
                  f"conf={result.confidence:.2f}  "
                  f"validated={'Y' if result.validation_performed else 'N'}  "
                  f"clients={result.client_count}")

    # 7 — Print results
    print_results(
        product_id, all_ids, imposter_ids, sleeper_ids, good_ids,
        trajectory, days, hour_to_true_price,
    )


# ─── Results printing ──────────────────────────────────────────────────

def print_results(
    product_id, all_ids, imposter_ids, sleeper_ids, good_ids,
    trajectory, days, hour_to_true_price,
):
    """Print final reputations and price-history comparison."""
    print("\n" + "=" * 60)
    print("SIMULATION RESULTS")
    print("=" * 60)

    # Get final reputations from the live client records.
    reps = {}
    for cid in all_ids:
        c = clients().find_one({"_id": cid})
        reps[cid] = c["reputation"] if c else config.reputation_initial

    # ── Summary ──
    good_reps = [reps[c] for c in good_ids]
    imp_reps = [reps[c] for c in imposter_ids]
    slp_reps = [reps[c] for c in sleeper_ids]

    print("\nSUMMARY")
    print("-" * 60)
    print(f"  Total clients:       {len(all_ids)}")
    print(f"  Good clients:        {len(good_ids)}")
    print(f"  True imposters:      {len(imposter_ids)}")
    print(f"  Sleeper cells:       {len(sleeper_ids)}")

    print("\nAVERAGE REPUTATIONS")
    print("-" * 60)
    print(f"  Good clients:        {sum(good_reps)/len(good_reps):.4f}")
    if imp_reps:
        print(f"  True imposters:      {sum(imp_reps)/len(imp_reps):.4f}")
    if slp_reps:
        print(f"  Sleeper cells:       {sum(slp_reps)/len(slp_reps):.4f}")

    punished_imposters = sum(1 for r in imp_reps if r < 0.5)
    punished_sleepers = sum(1 for r in slp_reps if r < 0.5)
    print("\nPUNISHMENT RATE")
    print("-" * 60)
    print(f"  Imposters punished:  {punished_imposters}/{len(imposter_ids)}")
    print(f"  Sleepers punished:   {punished_sleepers}/{len(sleeper_ids)}")

    # ── All 30 imposters + sleepers ──
    print("\n" + "=" * 60)
    print("ALL IMPOSTERS AND SLEEPERS — FINAL REPUTATIONS")
    print("=" * 60)
    print(f"  {'#':<4} {'Client ID':<38} {'Role':<10} {'Reputation':<12} {'Status'}")
    print("-" * 60)

    idx = 0
    for cid in imposter_ids:
        idx += 1
        rep = reps[cid]
        status = "PUNISHED" if rep < 0.5 else "NOT PUNISHED"
        marker = "✓" if rep < 0.5 else "✗"
        print(f"  {idx:<4} {cid:<38} {'IMPOSTER':<10} {rep:<12.4f} {marker} {status}")

    for cid in sleeper_ids:
        idx += 1
        rep = reps[cid]
        status = "PUNISHED" if rep < 0.5 else "NOT PUNISHED"
        marker = "✓" if rep < 0.5 else "✗"
        print(f"  {idx:<4} {cid:<38} {'SLEEPER':<10} {rep:<12.4f} {marker} {status}")

    # ── Price history: true vs computed ──
    print("\n" + "=" * 60)
    print("PRICE HISTORY — TRUE PRICE vs COMPUTED CANONICAL PRICE")
    print("=" * 60)
    print(f"  {'Hour':<22} {'True Price':>12} {'Canonical':>12} {'Diff %':>8} {'Corrupt?'}")
    print("-" * 60)

    results = list(
        hourlyResults()
        .find({"productId": product_id, "simTag": SIM_TAG})
        .sort("hour", 1)
    )

    corrupted_count = 0
    now = _now()
    for r in results:
        hour = r["hour"]
        canonical = r["canonicalPrice"]
        # Normalise timezone (MongoDB may strip tzinfo on roundtrip).
        if hasattr(hour, "tzinfo") and hour.tzinfo is None:
            hour = hour.replace(tzinfo=timezone.utc)
        # Compute the true price directly from the date.
        days_ago = (now - hour).days
        day_key = max(0, min(days - 1, days - 1 - days_ago))
        true_price = trajectory.get(day_key)
        if true_price:
            diff_pct = abs(canonical - true_price) / true_price * 100
            corrupted = diff_pct > (config.price_tolerance * 100)
            if corrupted:
                corrupted_count += 1
            print(f"  {hour.strftime('%Y-%m-%d %H:00'):<22} "
                  f"${true_price:>10.2f} ${canonical:>10.2f} "
                  f"{diff_pct:>7.2f}%  {'⚠ YES' if corrupted else 'ok'}")
        else:
            print(f"  {hour.strftime('%Y-%m-%d %H:00'):<22} "
                  f"{'?':>12} ${canonical:>10.2f}")

    print("-" * 60)
    print(f"  Corrupted hours: {corrupted_count} / {len(results)}")

    # ── Verdict ──
    print("\n" + "=" * 60)
    print("VERDICT")
    print("-" * 60)
    if corrupted_count == 0 and punished_imposters == len(imposter_ids):
        print("  ✓ System working correctly:")
        print("    - All canonical prices match the true price")
        print("    - All imposters were punished")
    else:
        if corrupted_count > 0:
            print(f"  ⚠ {corrupted_count} hours had corrupted canonical prices")
        if punished_imposters < len(imposter_ids):
            print(f"  ⚠ {len(imposter_ids) - punished_imposters} imposters were NOT punished")
    print()
    print("  → Open the TruePrice extension popup or dashboard to")
    print(f"    view the price history chart for product {product_id}")
    print("=" * 60)


# ─── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TruePrice simulation — tests reputation system with imposters and sleepers",
    )
    parser.add_argument("--product", type=str, default=None,
                        help="Product ID to simulate (creates if it doesn't exist)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"Days of history to simulate (default {DEFAULT_DAYS})")
    parser.add_argument("--clients", type=int, default=DEFAULT_CLIENTS,
                        help=f"Number of clients (default {DEFAULT_CLIENTS})")
    parser.add_argument("--clean", action="store_true",
                        help="Remove ALL simulation data and exit")
    args = parser.parse_args()

    # Initialise DB connection
    init_db(config.mongo_uri, config.mongo_db)

    if args.clean:
        clean_all_simulation_data()
        return

    # Select product
    product_id = args.product
    if not product_id:
        product_id = select_product_interactive()
        if not product_id:
            return

    run_simulation(product_id, args.days, args.clients)


if __name__ == "__main__":
    main()
