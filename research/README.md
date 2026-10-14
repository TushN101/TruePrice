# TruePrice Crowd-Consensus Simulation Platform

A standalone simulation platform demonstrating reputation-weighted crowd consensus, adversarial attack resilience, and autonomous price-tracking dynamics with zero external dependencies.

---

## 1. Known Context

This platform is a standalone simulation of the production price-tracking system found in `server/`. In the production system, users submit real-time prices observed via a browser extension; the backend weights these submissions by user trust/reputation and periodically validates them against eBay when consensus is weak or tied. Over time, honest users accumulate trust and external validation requests decline.

Because the live external validation channel (eBay scraping) is currently blocked (HTTP 403), this simulation was developed within `research/` to recreate the exact mathematical, consensus, and reputation dynamics with **zero external dependencies**, allowing reproducible stress-testing, adversarial demonstrations, and defense verification.

**Hard Isolation Guarantee**: ALL simulation code resides strictly within `research/`. It does not import, call, or modify anything in `server/`.

---

## 2. Quick Start

### 2.1 Dependencies
The platform requires only Python 3.9+ and Flask (plus pytest for verification):
```bash
pip install -r research/requirements.txt
```
*(If using the project's existing virtual environment, dependencies are already installed in `server/.venv`)*

### 2.2 Running the Web Application
Launch the Flask application:
```bash
PYTHONPATH=research python3 research/run.py
```
Or with custom port/host:
```bash
PORT=5050 PYTHONPATH=research python3 research/run.py
```
Open your browser at **`http://localhost:5050`** to access the web interface.

### 2.3 Running the Test Suite
Run unit tests and verification smoke tests:
```bash
PYTHONPATH=research pytest research/tests/ -v
```

---

## 3. Platform Architecture & SOLID Design

The codebase is organized into modular layers adhering to SOLID design principles:

```
research/
├── DESIGN.md                 # System architecture and mathematical analysis
├── README.md                 # User guide and parameter documentation
├── requirements.txt          # Python dependencies (Flask, pytest)
├── run.py                    # Server startup script
├── engine/                   # Domain logic (pure Python, zero web dependencies)
│   ├── config.py             # SimulationConfig dataclass & parameter validation
│   ├── consensus.py          # Relative clustering, weighted median, consensus engine
│   ├── reputation.py         # Strength-based, bounded-proportional reputation model
│   ├── user_model.py         # Behavioral archetypes: Honest, Imposter, Sleeper Cell
│   └── simulation.py         # SimulationEngine, hourly tick loop, analytics compiler
├── web/                      # Presentation layer (Flask + Chart.js)
│   ├── app.py                # REST endpoints and page controllers
│   ├── templates/
│   │   ├── base.html         # Common layout with Chart.js CDN
│   │   ├── config.html       # Page 1: Configuration form
│   │   ├── live.html         # Page 2: Live dashboard during run
│   │   └── report.html       # Page 3: Final audit report
│   └── static/
│       ├── css/style.css     # Responsive theme, badges, progress bars
│       └── js/
│           ├── live.js       # Live tick playback, streaming chart, top-20 panel
│           └── report.js     # Full-history chart with shaded attack window
└── tests/                    # Verification suite
    ├── test_engine.py        # Unit tests for clustering, consensus, reputation
    ├── test_smoke.py         # Required smoke tests #1, #2, and reproducibility
    └── test_web.py           # Integration tests for Flask routes and APIs
```

---

## 4. Parameter Reference (Page 1)

| Parameter | Type / Range | Default | Description |
| :--- | :--- | :--- | :--- |
| **`seed`** | Integer | `42` | Random seed ensuring byte-for-byte reproducible simulation runs. |
| **`total_users`** | Integer ($\ge 10$) | `200` | Total user population in the simulation pool. |
| **`imposter_count`** | Integer ($\ge 0$) | `30` | Number of adversarial users submitting poisoned prices from tick 1. |
| **`sleeper_cell_count`** | Integer ($\ge 0$) | `20` | Number of users behaving honestly during seeding, then turning malicious. |
| **`honest_users`** | Derived ($\ge 0$) | `150` | Automatically calculated as `total_users - imposter_count - sleeper_cell_count`. |
| **`fake_product_name`** | String | `SuperWidget Pro Max` | Simulated item name under observation. |
| **`base_price`** | Float ($> 0$) | `$200.00` | Starting ground truth market price. |
| **`fake_product_price`** | Float ($> 0$) | `$99.00` | Poisoned price submitted by imposters and activated sleepers. |
| **`sleeper_activation_day`** | Integer ($\ge 0$) | `10` | Day in the attack phase when sleeper cells activate their exploit. |
| **`participation_factor`** | Float ($0.0 - 1.0$) | `0.70` | Probability that any user submits an observation during an hourly tick. |
| **`honest_error_rate`** | Float ($0.0 - 1.0$) | `0.15` | Probability that an honest participant makes an accidental human mistake. |
| **`honest_error_margin_percent`** | Float ($> 0$) | `0.10` ($10\%$) | How far off an honest user's mistake can be from the true price. |
| **`seed_history_days`** | Integer ($\ge 1$) | `7` | Duration of the honest warm-up phase to establish initial baseline trust. |
| **`simulation_days`** | Integer ($\ge 1$) | `14` | Duration of the adversarial attack window. |
| **`consensus_threshold`** | Float ($0.0 - 1.0$) | `0.80` ($80\%$) | Minimum weighted agreement (overall crowd confidence and trusted cluster agreement) required to accept crowd price without validation. |

---

## 5. Output Metric Reference (Page 3)

| Metric | Meaning & Defense Significance |
| :--- | :--- |
| **`Bad Clients Trusted (>0.5)`** | Percentage of imposters and sleepers with final rating $> 0.5$. In a successful defense, this is strictly **0.0%** (zero breaches). |
| **`Honest Clients Punished`** | Count and percentage of honest users temporarily penalized for occasional human error, alongside how many remained trusted ($> 0.5$) at the end. |
| **`Total Validations`** | Count of hours where the platform fell back to authoritative ground-truth validation. |
| **`Validation Rate Over Time`** | Percentage of ticks requiring external validation. In a robust defense, this drops dramatically after initial seeding as honest consensus takes over. |
| **`Seed vs Attack Validation Rate`** | Comparison of validation frequency during the warm-up phase versus the attack phase. |
| **`Adversaries in Top 20`** | Count of imposters or sleepers present in the Top 20 highest-rated users at the end. **0 adversaries = Defense Held**. |
| **`Hours Outside &plusmn;5% Band`** | Number of hours where the crowd-predicted price deviated from actual price by $> 5\%$. Indicates price integrity. |
| **`Mean Honest Trust`** | Average reputation score of honest participants (typically climbs from $0.5$ baseline to $\sim 0.78 - 0.85$). |
| **`Mean Imposter Trust`** | Average reputation score of imposters (penalized down to the floor of $0.10$). |
| **`Mean Sleeper Trust`** | Average reputation score of sleepers (punished sharply down to $0.10$ upon activation). |
| **`Auto-Generated Conclusion`** | A plain-English verdict summarizing whether rankings held, bad clients were suppressed, and how validation evolved. |
| **`Documentation & Formulas (/docs)`** | Built-in educational guide explaining the clustering formula, weighted median, validation triggers, and bounded-proportional reputation adjustments in plain English. |

---

## 6. Verification & Automated Tests

Run the full pytest suite:
```bash
PYTHONPATH=research pytest research/tests/ -v
```

The test suite validates:
1. **Smoke Test #1 (`test_smoke_1_benign_crowd_validation_rate_drops`)**:
   - Zero imposters, zero sleepers.
   - Verifies that validation rate trends to $\sim 0$ after the seed period.
   - Verifies that prediction error stays strictly within the acceptable band.
2. **Smoke Test #2 (`test_smoke_2_heavy_imposters_downgraded_defense_holds`)**:
   - Heavy imposter ratio (35% attackers + 10% sleepers).
   - Verifies that attackers are systematically downgraded to minimum trust ($0.1$).
   - Verifies that attackers NEVER dominate the Top 20 rankings.
3. **Reproducibility Test (`test_reproducibility_same_seed_identical_run`)**:
   - Verifies that identical configurations and seeds generate byte-for-byte identical histories and metrics.
4. **Unit & Integration Tests**:
   - Single-linkage relative clustering and weighted median correctness.
   - Strength-based bounded-proportional reputation scaling.
   - End-to-end web API routes, live tick advancement, fast-forwarding, and report generation.
