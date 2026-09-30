import pytest
from pydantic import ValidationError

from doin_core.models.modular_experiment import ModularExperiment


def payload():
    return {
        "schema_version": "modular.experiment.v1",
        "architecture": {
            "branches": [
                {"name": "close", "features": ["close"], "encoder": "temporal_conv"},
                {"name": "context", "features": ["volume"], "encoder": "recurrent"},
            ],
            "fusion": "sequence_concat",
            "temporal_core": "recurrent",
        },
        "regime": "R0",
        "objective": {"metric": "MAE", "split": "validation", "higher_is_better": False, "unit": "price"},
        "data": {"dataset_id": "daily-v1", "train_end": "2024-01-01", "validation_start": "2024-01-02"},
    }


def test_json_round_trip_preserves_branch_and_objective():
    model = ModularExperiment.model_validate(payload())
    assert ModularExperiment.model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("change", [
    lambda p: p["architecture"].update(temporal_core="mlp"),
    lambda p: p["architecture"].update(branches=[]),
    lambda p: p["architecture"]["branches"][1].update(name="close"),
    lambda p: p.update(regime="R1"),
    lambda p: p["objective"].update(split="test"),
    lambda p: p["data"].update(validation_start="2023-12-31"),
])
def test_invalid_contract_refused(change):
    value = payload()
    change(value)
    with pytest.raises(ValidationError):
        ModularExperiment.model_validate(value)


def test_r1_and_r2_require_same_explicit_pretraining_reference():
    for regime in ("R1", "R2"):
        value = payload()
        value.update(regime=regime, detector_checkpoint="sha256:abc")
        assert ModularExperiment.model_validate(value).detector_checkpoint == "sha256:abc"


def test_r0_rejects_pretraining_reference():
    value = payload()
    value["detector_checkpoint"] = "sha256:abc"
    with pytest.raises(ValidationError):
        ModularExperiment.model_validate(value)
