#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PipelineRunContext:
    args: object
    status: dict
    budget_state: dict
    status_lock: object | None = None
    budget_lock: object | None = None
    event_lock: object | None = None
    started_ids_lock: object | None = None
    round_started_ids: set | None = None

    @property
    def out_root(self) -> Path:
        return Path(self.args.out_root)

    @property
    def competition(self) -> str:
        return str(getattr(self.args, "competition", "") or "")

    @property
    def pipeline_id(self) -> str:
        return str(getattr(self.args, "pipeline_id", "") or "")

    @property
    def model(self) -> str:
        return str(getattr(self.args, "model", "") or "")

    def status_entry(self, challenge: dict) -> dict:
        return self.status.get(str(challenge["id"]), {})

    def mark_round_started(self, challenge_id: int) -> None:
        if self.round_started_ids is None:
            return
        if self.started_ids_lock is None:
            self.round_started_ids.add(int(challenge_id))
            return
        with self.started_ids_lock:
            self.round_started_ids.add(int(challenge_id))
