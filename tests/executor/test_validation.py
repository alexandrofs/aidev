import pytest
from unittest.mock import MagicMock
from executor.src.validation import ValidationPipeline, ValidationResult


def test_validation_result_structure():
    res = ValidationResult(
        passed=True,
        command="pytest",
        stdout="10 passed",
        stderr="",
        exit_code=0,
        duration_seconds=1.23
    )
    assert res.passed is True
    assert res.command == "pytest"
    assert res.stdout == "10 passed"
    assert res.exit_code == 0
    assert res.duration_seconds == 1.23


def test_validation_pipeline_success():
    mock_sandbox = MagicMock()
    mock_sandbox.execute_job.return_value = {
        "exit_code": 0,
        "logs": "All tests passed",
        "container_id": "test-container-123"
    }

    pipeline = ValidationPipeline(sandbox_manager=mock_sandbox)
    results = pipeline.run_validations(commands=["pytest", "flake8"])

    assert len(results) == 2
    assert results[0].passed is True
    assert results[0].command == "pytest"
    assert results[0].stdout == "All tests passed"
    assert results[1].passed is True
    assert results[1].command == "flake8"
    assert mock_sandbox.execute_job.call_count == 2


def test_validation_pipeline_failure_stops_execution():
    mock_sandbox = MagicMock()
    # First command fails, second should not run
    mock_sandbox.execute_job.return_value = {
        "exit_code": 1,
        "logs": "pytest error: 2 failed",
        "container_id": "test-container-456"
    }

    pipeline = ValidationPipeline(sandbox_manager=mock_sandbox)
    results = pipeline.run_validations(commands=["pytest", "flake8"])

    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].command == "pytest"
    assert results[0].stderr == "pytest error: 2 failed"
    assert mock_sandbox.execute_job.call_count == 1


def test_validation_pipeline_exception_handling():
    mock_sandbox = MagicMock()
    mock_sandbox.execute_job.side_effect = Exception("Docker daemon connection failed")

    pipeline = ValidationPipeline(sandbox_manager=mock_sandbox)
    results = pipeline.run_validations(commands=["pytest"])

    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].exit_code == -1
    assert "Docker daemon connection failed" in results[0].stderr
