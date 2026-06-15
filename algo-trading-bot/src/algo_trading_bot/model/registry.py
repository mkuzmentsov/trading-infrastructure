"""Model registry + champion-challenger (FR10).

Every trained model is versioned and pinned to the exact (data snapshot, code
commit, config, validation evidence) that produced it (§3.4, NFR2). A model can only
enter the registry as *approved* if it cleared the approve-for-live gate (§4).

Champion-challenger: the live model is the champion; retrained candidates run as
challengers (in paper/shadow) and only promote if they beat the champion OOS under
the same gate. This is how the system adapts to edge decay without flip-flopping on
noise (principle #10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ModelVersion:
    model_id: str
    version: str
    data_snapshot_id: str
    git_commit: str
    config_hash: str
    approved: bool
    created_at: datetime
    metrics: dict


class ModelRegistry:
    def __init__(self, root: str) -> None:
        self.root = root

    def register(self, version: ModelVersion, artifact) -> None:
        raise NotImplementedError("persist artifact + ModelVersion metadata")

    def champion(self, model_id: str) -> ModelVersion | None:
        """The currently-live approved version for this model id."""
        raise NotImplementedError

    def promote(self, model_id: str, version: str) -> None:
        """Promote a challenger to champion (only if approved + beat current champion)."""
        raise NotImplementedError


class RetrainScheduler:
    """Triggers scheduled retraining (FR10), mirroring walk-forward cadence (§4.5)."""

    def __init__(self, every) -> None:
        self.every = every

    def due(self, now: datetime, last_trained: datetime) -> bool:
        raise NotImplementedError("now - last_trained >= self.every")
