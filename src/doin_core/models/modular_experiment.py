"""Serializable, plugin-agnostic contract for temporal modular experiments.

This describes a candidate and its objective; it does not train or score it.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Branch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    features: list[str] = Field(min_length=1)
    encoder: Literal["temporal_conv", "recurrent", "attention"]

    @model_validator(mode="after")
    def unique_features(self) -> Branch:
        if any(not feature for feature in self.features) or len(set(self.features)) != len(self.features):
            raise ValueError("branch features must be nonempty and unique")
        return self


class Architecture(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    branches: list[Branch] = Field(min_length=2)
    fusion: Literal["sequence_concat"]
    temporal_core: Literal["temporal_conv", "recurrent", "attention"]

    @model_validator(mode="after")
    def unique_branches(self) -> Architecture:
        names = [branch.name for branch in self.branches]
        if len(set(names)) != len(names):
            raise ValueError("branch names must be unique")
        return self


class Objective(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    metric: str = Field(min_length=1)
    split: Literal["validation"]
    higher_is_better: bool
    unit: str = Field(min_length=1)


class DataIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    dataset_id: str = Field(min_length=1)
    train_end: date = Field(strict=False)
    validation_start: date = Field(strict=False)

    @model_validator(mode="after")
    def chronological(self) -> DataIdentity:
        if self.train_end >= self.validation_start:
            raise ValueError("validation must start after training ends")
        return self


class ModularExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["modular.experiment.v1"]
    architecture: Architecture
    regime: Literal["R0", "R1", "R2"]
    detector_checkpoint: str | None = None
    objective: Objective
    data: DataIdentity

    @model_validator(mode="after")
    def checkpoint_matches_regime(self) -> ModularExperiment:
        if self.regime == "R0" and self.detector_checkpoint is not None:
            raise ValueError("R0 must not import a detector checkpoint")
        if self.regime in ("R1", "R2") and not self.detector_checkpoint:
            raise ValueError("R1/R2 require a detector checkpoint reference")
        return self
