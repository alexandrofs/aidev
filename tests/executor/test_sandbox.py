import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from executor.src.config import ExecutorSettings
from executor.src.sandbox import DockerSandboxManager


def test_executor_settings_defaults():
    settings = ExecutorSettings()
    assert settings.SANDBOX_IMAGE == "python:3.12-slim"
    assert settings.POLL_INTERVAL == 2.0
    assert settings.CONTAINER_TIMEOUT == 300
    assert settings.WORKER_ID.startswith("executor-worker-")


def test_sandbox_manager_run_and_cleanup():
    mock_docker_client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "test_container_123"
    mock_docker_client.containers.run.return_value = mock_container

    manager = DockerSandboxManager(docker_client=mock_docker_client)

    created_temp_dir = None
    with manager.run_sandbox(image="python:3.12-slim", command="echo hello", env_vars={"FOO": "BAR"}) as container:
        assert container == mock_container
        mock_docker_client.containers.run.assert_called_once()
        call_kwargs = mock_docker_client.containers.run.call_args.kwargs
        assert call_kwargs["image"] == "python:3.12-slim"
        assert call_kwargs["command"] == "echo hello"
        assert call_kwargs["environment"] == {"FOO": "BAR"}
        assert call_kwargs["detach"] is True
        assert call_kwargs["auto_remove"] is False
        
        # Capture temporary volume path
        volumes = call_kwargs["volumes"]
        created_temp_dir = list(volumes.keys())[0]
        assert os.path.exists(created_temp_dir)

    # After context exit, container.stop and container.remove must be called
    mock_container.stop.assert_called_once_with(timeout=5)
    mock_container.remove.assert_called_once_with(v=True, force=True)
    # Temporary directory must be cleaned up
    assert not os.path.exists(created_temp_dir)


def test_sandbox_manager_cleanup_on_exception():
    mock_docker_client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "test_container_456"
    mock_docker_client.containers.run.return_value = mock_container

    manager = DockerSandboxManager(docker_client=mock_docker_client)
    created_temp_dir = None

    with pytest.raises(ValueError, match="Something went wrong"):
        with manager.run_sandbox(image="python:3.12-slim", command="exit 1") as container:
            volumes = mock_docker_client.containers.run.call_args.kwargs["volumes"]
            created_temp_dir = list(volumes.keys())[0]
            raise ValueError("Something went wrong")

    # Cleanup must still run
    mock_container.stop.assert_called_once_with(timeout=5)
    mock_container.remove.assert_called_once_with(v=True, force=True)
    assert not os.path.exists(created_temp_dir)


def test_sandbox_execute_job():
    mock_docker_client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "test_container_789"
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b"job executed successfully\n"
    mock_docker_client.containers.run.return_value = mock_container

    manager = DockerSandboxManager(docker_client=mock_docker_client)
    result = manager.execute_job(command="python -c 'print(1)'")

    assert result["exit_code"] == 0
    assert "job executed successfully" in result["logs"]
    assert result["container_id"] == "test_container_789"
    mock_container.stop.assert_called_once()
    mock_container.remove.assert_called_once_with(v=True, force=True)


def test_sandbox_execute_job_log_truncation_and_timeout():
    mock_docker_client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "test_container_timeout"
    mock_container.wait.side_effect = RuntimeError("ReadTimeout error")
    mock_container.logs.return_value = b"A" * 200
    mock_docker_client.containers.run.return_value = mock_container

    manager = DockerSandboxManager(docker_client=mock_docker_client)
    result = manager.execute_job(command="sleep 10", max_log_bytes=100)

    assert result["exit_code"] == -1
    assert len(result["logs"]) > 100
    assert "logs truncados pelo executor" in result["logs"]

