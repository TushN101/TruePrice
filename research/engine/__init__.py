"""Research engine package exposing core simulation components."""
from .config import SimulationConfig
from .consensus import Cluster, ConsensusResult, Observation, cluster_prices, weighted_consensus, weighted_median
from .reputation import ReputationConfig, clamp, compute_update_magnitude, is_trusted, update_reputation
from .simulation import SimulationEngine, TickRecord
from .user_model import User, UserArchetype

__all__ = [
    "SimulationConfig",
    "Cluster",
    "ConsensusResult",
    "Observation",
    "cluster_prices",
    "weighted_consensus",
    "weighted_median",
    "ReputationConfig",
    "clamp",
    "compute_update_magnitude",
    "is_trusted",
    "update_reputation",
    "SimulationEngine",
    "TickRecord",
    "User",
    "UserArchetype",
]
