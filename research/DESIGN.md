# Crowd-Consensus Simulation Platform — Design Specification

## 1. Context & Objectives

TruePrice (`server/`) is a crowdsourced price-tracking platform designed to defeat deceptive e-commerce pricing (e.g. fake discounts) by aggregating user-reported prices. Observations are weighted by each user's reputation/trust score. When trusted consensus is weak or split, the platform triggers external validation against an authoritative price source. Successful validations reward honest contributors and penalize bad actors, progressively shifting the voting power toward honest users and reducing the need for future external validations.

Because the live validation channel (eBay scraping) is blocked (HTTP 403), this standalone simulation platform in `research/` replicates the core mathematical, consensus, and reputation dynamics with **zero external dependencies**, allowing reproducible demonstrations, stress-testing, and defense evaluation.

---

## 2. Core Mechanics in the Production System (`server/`)

### 2.1 User Trust & Reputation Lifecycle
The reputation model in `server/core/reputation.py` is **strength-based** and **bounded-proportional**:

1. **Initialization & Range**:
   - `reputation_initial = 0.5` (neutral baseline).
   - Bounds: `reputation_min = 0.1`, `reputation_max = 0.9`.
   - A user is deemed **trusted** if `reputation > 0.5`. Fresh users are neutral and not initially trusted.

2. **Consensus-Strength-Based Update Magnitude**:
   - Updates are scaled by how strong the consensus was ($consensus\_strength \in [0.5, 1.0]$, derived from $\max(0.5, confidence)$):
     $$\text{normalized} = \max(0.0, 2.0 \times (consensus\_strength - 0.5))$$
     $$\text{magnitude} = \text{base\_reward} + \text{strength\_factor} \times \text{normalized}$$
     *(Defaults: $\text{base\_reward} = 0.05$, $\text{strength\_factor} = 0.10 \implies \text{magnitude} \in [0.05, 0.15]$)*
   - A wrong submission against a unanimous consensus ($1.0$) is punished harder than a wrong submission against a split consensus ($0.5$).

3. **Bounded-Proportional Adjustments**:
   - **Correct submission**:
     $$\text{scale} = \frac{\text{maximum} - \text{current}}{\text{maximum} - \text{minimum}} = \frac{0.9 - \text{current}}{0.8}$$
     $$\Delta = \text{magnitude} \times \max(0.0, \text{scale})$$
     $$\text{new\_reputation} = \text{current} + \Delta$$
     *Effect*: High-reputation users have little room to grow, so they gain slowly.
   - **Incorrect submission**:
     $$\text{scale} = \frac{\text{current} - \text{minimum}}{\text{maximum} - \text{minimum}} = \frac{\text{current} - 0.1}{0.8}$$
     $$\Delta = \text{magnitude} \times \max(0.0, \text{scale})$$
     $$\text{new\_reputation} = \text{current} - \Delta$$
     *Effect*: High-reputation users have a large drop distance, so trust is easy to lose and hard to rebuild.
   - Final value is clamped to $[0.1, 0.9]$.

4. **Execution Timing & Chronological Integrity**:
   - Reputations are updated **strictly after** the consensus and validation for the current hour are finalized (`server/core/history.py`).
   - Deduplication ensures each client has at most one effective submission per hour (latest timestamp wins), preventing spamming or replay attacks.

---

### 2.2 Consensus Strength & Validation Triggers

1. **Price Clustering**:
   - Sorted submissions are grouped into clusters using relative single-linkage tolerance:
     $$\frac{p_2 - p_1}{p_1} \le \text{price\_tolerance} \quad (\text{default: } 0.02 = 2\%)$$

2. **Weighted Cluster Support**:
   - Each cluster $C$ accumulates support from its members' reputations:
     $$\text{support}(C) = \sum_{\text{obs} \in C} \text{reputation}(\text{clientId})$$
     *(Unseen users default to $0.5$)*

3. **Winning Cluster & Representative Price**:
   - The winning cluster is the one with the highest weighted support. Ties are broken by higher unique client count, then lower representative price.
   - The representative price of the winning cluster is the **reputation-weighted median** of its observations (resilient to internal outliers).

4. **Consensus Confidence**:
   - Confidence is defined as:
     $$\text{confidence} = \frac{\text{winning\_cluster\_support}}{\sum \text{all\_cluster\_supports}} \in [0.0, 1.0]$$

5. **Validation Triggers**:
   In `server/core/history.py`, validation against the external price source is triggered if **any** of the following conditions are met:
   - **Untrusted Crowd**: $\text{trusted\_ratio} < \text{trusted\_threshold}$ (default: $0.6$), where:
     $$\text{trusted\_ratio} = \frac{\#\{\text{clients with reputation} > 0.5\}}{\text{total participating clients}}$$
   - **Tied Support**: Top two clusters have equal support ($|S_0 - S_1| < 10^{-9}$), indicating a split crowd that internal consensus cannot resolve.
   - **Low Participation**: Participating clients $< \text{validation\_min\_observations}$ (default: $3$).
   - **Random Auditing**: Probabilistic spot-check (`random_rate`, default $0.3$) to catch sleeper cells that have built trust.

---

### 2.3 Validated Price Correction

1. **Overriding Internal Consensus**:
   - When validation is triggered and succeeds:
     $$\text{canonical\_price} = \text{validator\_price}$$
     $$\text{validation\_performed} = \text{True}$$
   - When validation is not triggered (or fails):
     $$\text{canonical\_price} = \text{crowd\_consensus\_price}$$
     $$\text{validation\_performed} = \text{False}$$

2. **Grading Observations**:
   - Submissions are evaluated against $\text{canonical\_price}$ with relative tolerance:
     $$\text{correct} \iff \frac{|\text{obs.price} - \text{canonical\_price}|}{\text{canonical\_price}} \le \text{tolerance}$$
   - When validation overrides a falsified or split crowd, the ground truth authoritative price marks all malicious or erroneous prices as incorrect, triggering reputation penalties.
   - Honest contributors are marked correct and gain reputation, moving above $0.5$ and becoming trusted.

3. **Self-Reinforcing Defense**:
   - As honest users accumulate trust, the proportion of trusted users and the weighted support for accurate prices increase.
   - Once trusted ratio / agreement consistently exceeds the threshold, external validations are no longer triggered, and the crowd functions autonomously.

---

## 3. Simulation Simplifications & Rationale

| Real System (`server/`) | Simulation Platform (`research/`) | Rationale / Simplification |
| :--- | :--- | :--- |
| **External eBay Scraping** (`requests.get` + BeautifulSoup on eBay URLs) | **Synthetic Ground Truth Generator** (base price with configurable daily drift) | Eliminates network dependencies and HTTP 403 blocks; guarantees reproducible and deterministic testing. |
| **MongoDB Persistence & JWT** (5 collections, JWT auth, IP rate limits) | **In-Memory State Engine** (pure Python data structures per run) | Simplifies execution, removes database setup, provides instantaneous simulation ticks and fast pytest runs. |
| **Lazy Materialization** (on-demand retroactive computation over timestamps) | **Direct Tick-Based Loop** ($1 \text{ tick} = 1 \text{ simulated hour}$) | Clean progression suitable for live dashboard streaming and sequential state analysis. |
| **Arbitrary User Behavior** | **Discrete Behavioral Archetypes**: Honest, Imposter, Sleeper | Allows formal experimental control over attack ratios, activation schedules, and error distributions. |
| **Complex Multi-Condition Validation Trigger** | **Configurable Consensus / Trust Threshold** | Maps the core conditions (`trusted_ratio < threshold` or low agreement, plus ties) to an intuitive user parameter. |

---

## 4. Simulation Architecture & SOLID Design

The simulation is implemented purely within `research/` with no imports or dependencies on `server/`:

```
research/
├── DESIGN.md                 # This design specification
├── README.md                 # Running instructions, parameter guide, metrics
├── requirements.txt          # Minimal dependencies (Flask, pytest)
├── engine/                   # Simulation domain logic (clean architecture)
│   ├── __init__.py
│   ├── config.py             # SimulationConfig dataclass & parameter validation
│   ├── archetypes.py         # User model (Honest, Imposter, Sleeper)
│   ├── consensus.py          # Clustering, weighted median, consensus engine
│   ├── reputation.py         # Strength-based, bounded-proportional trust engine
│   └── simulator.py          # Master loop, ground truth generation, tick processor
├── web/                      # Flask presentation layer
│   ├── __init__.py
│   ├── app.py                # Flask routes, API endpoints, SSE / polling runner
│   ├── static/
│   │   ├── css/style.css     # Clean responsive styling
│   │   └── js/app.js         # Vanilla JS UI controller + Chart.js integrations
│   └── templates/
│       ├── index.html        # Page 1: Configuration form
│       ├── live.html         # Page 2: Live dashboard during run
│       └── report.html       # Page 3: Final report at end of run
└── tests/                    # Verification suite
    ├── __init__.py
    ├── test_engine.py        # Unit tests for clustering, consensus, reputation
    └── test_smoke.py         # Required pytest smoke test #1 and #2
```

### Applying SOLID Principles:
- **Single Responsibility Principle (SRP)**:
  - `reputation.py` only handles reputation transitions and bounds.
  - `consensus.py` only clusters observations and computes weighted medians and support.
  - `archetypes.py` generates individual user decisions for a given tick.
  - `simulator.py` manages simulation time, ground truth trajectory, and step execution.
  - `app.py` serves web routes and returns JSON / event streams.
- **Open/Closed Principle (OCP)**:
  - User archetypes implement a common protocol/interface (`UserBehavior`), making it trivial to add new adversarial strategies (e.g. sybil bursts, oscillating attackers) without touching the consensus engine.
- **Liskov Substitution Principle (LSP)**:
  - All user models adhere to standard observation generation semantics.
- **Interface Segregation Principle (ISP)**:
  - Components take minimal typed configurations rather than monolithic global configs.
- **Dependency Inversion Principle (DIP)**:
  - The simulator depends on abstract interfaces for price validation and observation generation, enabling deterministic seeding and mock injection in unit tests.

---

## 5. Parameter Mapping & Verification Strategy

### 5.1 Configuration Parameters
- `seed`: Integer seed ensuring `random.Random(seed)` yields byte-for-byte reproducible runs.
- `total_users`, `imposter_count`, `sleeper_cell_count`: Crowd sizing ($honest = total - imposter - sleeper$).
- `sleeper_activation_day`: Day at which sleeper cells switch from honest to malicious submissions.
- `participation_factor`: Probability ($0.0 - 1.0$) that a user participates during a given hourly tick.
- `honest_error_rate` & `honest_error_margin_percent`: Human noise modeling.
- `fake_product_name`, `fake_product_price`: Attacker payload.
- `seed_history_days`: Warm-up period with honest submissions to establish initial reputation.
- `consensus_threshold`: Threshold of trusted participation / confidence required to avoid external validation.
- `simulation_days`: Duration of the attack phase.

### 5.2 Verification Criteria
1. **Smoke Test #1 (Benign Crowd)**: With 0 imposters and 0 sleepers, validations occur during early hours while users build initial trust, then drop to $\sim 0$; prediction error stays within the honest noise margin.
2. **Smoke Test #2 (Heavy Imposter Attack)**: Imposters are systematically penalized upon validation; their reputation drops toward $0.1$ and they are prevented from dominating the Top 20 trusted ranks.
3. **Web Application Verification**: Full browser workflow executes flawlessly: configuration form $\to$ live tick dashboard $\to$ comprehensive final report.
