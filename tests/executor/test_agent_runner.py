import pytest
from executor.src.config import ExecutorSettings
from executor.src.agent_runner import AgentRunner


def test_agent_runner_command_generation():
    settings = ExecutorSettings(
        OPENCODE_RUN_COMMAND="opencode run {prompt_path}",
        OPENCODE_MODEL="claude-3-5-sonnet"
    )
    runner = AgentRunner(settings=settings)

    cmd = runner.build_agent_command(phase="coding", story_id="STORY-1", prompt_path="/workspace/prompts/coding.md")
    assert "opencode run /workspace/prompts/coding.md -m claude-3-5-sonnet" in cmd
    assert "cd /workspace" in cmd
    assert "command -v opencode" in cmd


def test_agent_runner_env_vars():
    settings = ExecutorSettings(OPENCODE_API_KEY="sk-test-key-123", _env_file=None)
    runner = AgentRunner(settings=settings)

    env = runner.get_phase_env_vars(phase="review", story_id="STORY-2", base_env={"CUSTOM": "VAL"})
    assert env["WORKFLOW_PHASE"] == "review"
    assert env["STORY_ID"] == "STORY-2"
    assert env["NON_INTERACTIVE"] == "1"
    assert env["OPENCODE_API_KEY"] == "sk-test-key-123"
    assert env["OPENROUTER_API_KEY"] == "sk-test-key-123"
    assert env["ANTHROPIC_API_KEY"] == "sk-test-key-123"
    assert env["CUSTOM"] == "VAL"


def test_agent_runner_openrouter_api_key_env():
    settings = ExecutorSettings(OPENROUTER_API_KEY="sk-or-v1-abc", _env_file=None)
    runner = AgentRunner(settings=settings)

    env = runner.get_phase_env_vars(phase="coding", story_id="STORY-3")
    assert env["OPENROUTER_API_KEY"] == "sk-or-v1-abc"
    assert env["OPENCODE_API_KEY"] == "sk-or-v1-abc"
