"""Flask web application for the Crowd-Consensus Simulation Platform.

Provides routes for:
1. Page 1: Configuration Form (/configure, /)
2. Page 2: Live Dashboard (/live/<run_id>)
3. Page 3: Final Report (/report/<run_id>)
Along with REST APIs for stepped execution, streaming data, and fast-forwarding.
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Dict

# Add research root directory to sys.path so engine can be imported directly
RESEARCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if RESEARCH_DIR not in sys.path:
    sys.path.insert(0, RESEARCH_DIR)

from flask import Flask, jsonify, redirect, render_template, request, url_for
from engine.config import SimulationConfig
from engine.simulation import SimulationEngine

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)
app.config["SECRET_KEY"] = "crowd-consensus-sim-secret"

# In-memory store for active simulation engines
SIMULATIONS: Dict[str, SimulationEngine] = {}


@app.route("/")
def index():
    """Redirect to the configuration page."""
    return redirect(url_for("configure"))


@app.route("/configure", methods=["GET"])
def configure():
    """Page 1: Configuration form."""
    defaults = SimulationConfig()
    return render_template("config.html", defaults=defaults)


@app.route("/docs")
def docs():
    """Educational reference for consensus formulas and reputation mechanics."""
    return render_template("docs.html")


@app.route("/api/simulations", methods=["POST"])
def create_simulation():
    """Initialize a new simulation with submitted configuration."""
    data = request.get_json() or {}

    try:
        config = SimulationConfig(
            seed=int(data.get("seed", 42)),
            total_users=int(data.get("total_users", 200)),
            imposter_count=int(data.get("imposter_count", 30)),
            sleeper_cell_count=int(data.get("sleeper_cell_count", 20)),
            sleeper_activation_day=int(data.get("sleeper_activation_day", 10)),
            participation_factor=float(data.get("participation_factor", 0.70)),
            honest_error_rate=float(data.get("honest_error_rate", 0.15)),
            honest_error_margin_percent=float(data.get("honest_error_margin_percent", 0.10)),
            fake_product_name=str(data.get("fake_product_name", "SuperWidget Pro Max")),
            fake_product_price=float(data.get("fake_product_price", 99.0)),
            base_price=float(data.get("base_price", 200.0)),
            daily_price_drift=float(data.get("daily_price_drift", 0.01)),
            price_tolerance=float(data.get("price_tolerance", 0.02)),
            seed_history_days=int(data.get("seed_history_days", 7)),
            simulation_days=int(data.get("simulation_days", 14)),
            consensus_threshold=float(data.get("consensus_threshold", 0.80)),
        )
        config.validate()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    run_id = str(uuid.uuid4())[:8]
    SIMULATIONS[run_id] = SimulationEngine(config)

    return jsonify({
        "run_id": run_id,
        "total_ticks": config.total_ticks,
        "total_days": config.total_days,
        "seed_history_days": config.seed_history_days,
        "simulation_days": config.simulation_days,
        "redirect_url": url_for("live_dashboard", run_id=run_id),
    })


@app.route("/live/<run_id>")
def live_dashboard(run_id: str):
    """Page 2: Live simulation dashboard."""
    engine = SIMULATIONS.get(run_id)
    if not engine:
        return redirect(url_for("configure"))

    return render_template(
        "live.html",
        run_id=run_id,
        config=engine.config,
    )


@app.route("/api/simulations/<run_id>/tick", methods=["GET", "POST"])
def advance_tick(run_id: str):
    """Advance the simulation by 1 or more ticks."""
    engine = SIMULATIONS.get(run_id)
    if not engine:
        return jsonify({"error": "Simulation not found"}), 404

    batch_size = int(request.args.get("batch", 1))
    ticks_data = []

    for _ in range(batch_size):
        if engine.is_complete:
            break
        record = engine.step()
        ticks_data.append({
            "tick": record.tick,
            "day": record.day,
            "hour_of_day": record.hour_of_day,
            "actual_price": record.actual_price,
            "predicted_price": record.predicted_price,
            "canonical_price": record.canonical_price,
            "price_error_percent": record.price_error_percent,
            "confidence": record.confidence,
            "trusted_ratio": record.trusted_ratio,
            "submission_count": record.submission_count,
            "validation_performed": record.validation_performed,
            "in_attack_window": record.in_attack_window,
            "top_20_users": record.top_20_users,
        })

    latest = ticks_data[-1] if ticks_data else None

    return jsonify({
        "run_id": run_id,
        "is_complete": engine.is_complete,
        "current_tick": engine.current_tick,
        "total_ticks": engine.config.total_ticks,
        "cumulative_validations": engine.cumulative_validations,
        "ticks": ticks_data,
        "latest": latest,
    })


@app.route("/api/simulations/<run_id>/fast_forward", methods=["POST"])
def fast_forward(run_id: str):
    """Run all remaining ticks to completion."""
    engine = SIMULATIONS.get(run_id)
    if not engine:
        return jsonify({"error": "Simulation not found"}), 404

    engine.run_all()
    return jsonify({
        "run_id": run_id,
        "is_complete": True,
        "current_tick": engine.current_tick,
        "total_ticks": engine.config.total_ticks,
        "report_url": url_for("report_page", run_id=run_id),
    })


@app.route("/report/<run_id>")
def report_page(run_id: str):
    """Page 3: Final report."""
    engine = SIMULATIONS.get(run_id)
    if not engine:
        return redirect(url_for("configure"))

    # Ensure engine is complete if user visits report directly
    if not engine.is_complete:
        engine.run_all()

    report = engine.get_report()
    return render_template(
        "report.html",
        run_id=run_id,
        config=engine.config,
        report=report,
    )


@app.route("/api/simulations/<run_id>/report", methods=["GET"])
def get_report_json(run_id: str):
    """Get full report data as JSON."""
    engine = SIMULATIONS.get(run_id)
    if not engine:
        return jsonify({"error": "Simulation not found"}), 404

    if not engine.is_complete:
        engine.run_all()

    return jsonify(engine.get_report())


@app.route("/api/simulations/<run_id>/history", methods=["GET"])
def get_history_json(run_id: str):
    """Return full historical tick records for charting."""
    engine = SIMULATIONS.get(run_id)
    if not engine:
        return jsonify({"error": "Simulation not found"}), 404

    history_data = [
        {
            "tick": r.tick,
            "day": r.day,
            "hour_of_day": r.hour_of_day,
            "actual_price": r.actual_price,
            "predicted_price": r.predicted_price,
            "canonical_price": r.canonical_price,
            "price_error_percent": r.price_error_percent,
            "confidence": r.confidence,
            "trusted_ratio": r.trusted_ratio,
            "submission_count": r.submission_count,
            "validation_performed": r.validation_performed,
            "in_attack_window": r.in_attack_window,
        }
        for r in engine.history
    ]
    return jsonify({
        "run_id": run_id,
        "history": history_data,
        "attack_start_tick": engine.config.attack_start_tick,
        "sleeper_activation_tick": engine.config.sleeper_activation_tick,
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
