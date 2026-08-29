from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scale_runner_attests_stable_executable(tmp_path, monkeypatch) -> None:
    scale = load_script(
        "cuda_local_transition_scale_test_subject",
        "cpp/tests/cuda_local_transition_scale.py",
    )
    runner = tmp_path / "scale-runner"
    runner.write_bytes(b"stable runner bytes")
    expected = hashlib.sha256(runner.read_bytes()).hexdigest()

    def fake_run(command, **_kwargs):
        assert Path(command[0]) == runner
        return subprocess.CompletedProcess(command, 0, json.dumps({}), "")

    monkeypatch.setattr(scale.subprocess, "run", fake_run)
    monkeypatch.setattr(scale, "validate_result", lambda result, **_kwargs: result)
    result = scale.run_runner(
        runner,
        target_unique_corpus_slots=1,
        batch_states=1,
        seed=0,
    )
    assert result["scale_runner_executable_sha256"] == expected


def test_scale_runner_fails_if_executable_changes(tmp_path, monkeypatch) -> None:
    scale = load_script(
        "cuda_local_transition_scale_mutation_test_subject",
        "cpp/tests/cuda_local_transition_scale.py",
    )
    runner = tmp_path / "scale-runner"
    runner.write_bytes(b"before")

    def fake_run(command, **_kwargs):
        runner.write_bytes(b"after")
        return subprocess.CompletedProcess(command, 0, json.dumps({}), "")

    monkeypatch.setattr(scale.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="changed during execution"):
        scale.run_runner(
            runner,
            target_unique_corpus_slots=1,
            batch_states=1,
            seed=0,
        )


def test_memcheck_attests_stable_scale_runner(tmp_path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "cpp" / "tests"))
    sanitizer = load_script(
        "cuda_local_transition_scale_sanitizer_test_subject",
        "cpp/tests/cuda_local_transition_scale_sanitizer.py",
    )
    runner = tmp_path / "scale-runner"
    runner.write_bytes(b"stable memcheck runner bytes")
    expected = hashlib.sha256(runner.read_bytes()).hexdigest()

    def fake_run(command, **_kwargs):
        assert Path(command[5]) == runner
        return subprocess.CompletedProcess(
            command, 0, "{}\n", "ERROR SUMMARY: 0 errors\n"
        )

    monkeypatch.setattr(sanitizer.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sanitizer.scale, "validate_result", lambda result, **_kwargs: result
    )
    _result, _transcript, digest = sanitizer.run_memcheck(
        tmp_path / "compute-sanitizer",
        runner,
        target_unique_corpus_slots=1,
        batch_states=1,
        seed=0,
    )
    assert digest == expected


def test_memcheck_fails_if_scale_runner_changes(tmp_path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "cpp" / "tests"))
    sanitizer = load_script(
        "cuda_local_transition_scale_sanitizer_mutation_test_subject",
        "cpp/tests/cuda_local_transition_scale_sanitizer.py",
    )
    runner = tmp_path / "scale-runner"
    runner.write_bytes(b"before")

    def fake_run(command, **_kwargs):
        runner.write_bytes(b"after")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(sanitizer.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="changed during execution"):
        sanitizer.run_memcheck(
            tmp_path / "compute-sanitizer",
            runner,
            target_unique_corpus_slots=1,
            batch_states=1,
            seed=0,
        )


@pytest.mark.parametrize(
    "value",
    [None, "", "0" * 63, "0" * 65, "A" * 64, "g" * 64, 0],
)
def test_release_verifier_rejects_missing_or_malformed_attestation(value) -> None:
    verifier = load_script(
        "verify_release_cuda_scale_test_subject", "scripts/verify_release.py"
    )
    with pytest.raises(SystemExit, match="missing or malformed"):
        verifier.require_sha256_attestation("runner digest", value)


def test_release_verifier_accepts_lowercase_sha256() -> None:
    verifier = load_script(
        "verify_release_cuda_scale_valid_test_subject", "scripts/verify_release.py"
    )
    digest = "0123456789abcdef" * 4
    assert verifier.require_sha256_attestation("runner digest", digest) == digest
