import os
import json
import tempfile
import pytest
from executor.src.config import ExecutorSettings
from executor.src.exceptions import ContextError, PromptTemplateNotFoundError, InvalidMCPConfigError
from executor.src.context_loader import ContextLoader


def test_executor_settings_context_defaults():
    settings = ExecutorSettings()
    assert settings.MCP_CONFIG_PATH == "mcp_config.json"
    assert settings.SKILLS_DIR == ".agents/skills"
    assert settings.PROMPTS_DIR == "executor/prompts"
    assert settings.MANDATORY_PROMPTS == ["planning.md", "coding.md", "review.md"]


def test_exceptions_hierarchy():
    err = PromptTemplateNotFoundError("Prompt missing")
    assert isinstance(err, ContextError)
    
    mcp_err = InvalidMCPConfigError("Invalid JSON")
    assert isinstance(mcp_err, ContextError)


def test_load_mcp_config_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        mcp_file = os.path.join(tmpdir, "mcp_config.json")
        data = {"mcpServers": {"test": {"command": "node"}}}
        with open(mcp_file, "w") as f:
            json.dump(data, f)

        loader = ContextLoader()
        cfg = loader.load_mcp_config(mcp_file)
        assert cfg == data


def test_load_mcp_config_missing_returns_empty():
    loader = ContextLoader()
    cfg = loader.load_mcp_config("/path/to/nonexistent/mcp_config.json")
    assert cfg == {}


def test_load_mcp_config_invalid_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        mcp_file = os.path.join(tmpdir, "mcp_config.json")
        with open(mcp_file, "w") as f:
            f.write("{invalid json...")

        loader = ContextLoader()
        with pytest.raises(InvalidMCPConfigError, match="JSON inválido"):
            loader.load_mcp_config(mcp_file)


def test_discover_skills_empty_or_nonexistent():
    loader = ContextLoader()
    skills = loader.discover_skills("/path/to/nonexistent/skills")
    assert skills == {}


def test_discover_skills_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = os.path.join(tmpdir, "my-skill")
        os.makedirs(skill_dir)
        skill_file = os.path.join(skill_dir, "SKILL.md")
        with open(skill_file, "w") as f:
            f.write("# My Skill\nDescription of skill")

        loader = ContextLoader()
        skills = loader.discover_skills(tmpdir)
        assert "my-skill" in skills
        assert skills["my-skill"]["content"] == "# My Skill\nDescription of skill"


def test_load_prompt_template_missing_throws():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = ContextLoader()
        with pytest.raises(PromptTemplateNotFoundError, match="Prompt obrigatório ausente"):
            loader.load_prompt_template("planning", prompts_dir=tmpdir)


def test_load_prompt_template_empty_throws():
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_file = os.path.join(tmpdir, "coding.md")
        with open(prompt_file, "w") as f:
            f.write("   ")

        loader = ContextLoader()
        with pytest.raises(PromptTemplateNotFoundError, match="vazio"):
            loader.load_prompt_template("coding", prompts_dir=tmpdir)


def test_build_context_bundle_success():
    loader = ContextLoader()
    # Uses actual project prompts directory by default settings
    bundle = loader.build_context_bundle("coding")
    assert bundle["phase"] == "coding"
    assert "Coding Prompt Template" in bundle["prompt_template"]
    assert "mcp_config" in bundle
    assert "skills" in bundle
