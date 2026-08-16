import os
import pytest

@pytest.fixture(autouse=True)
def isolate_ci_github_env(monkeypatch):
    """
    Garante que variáveis de ambiente injetadas automaticamente pelo CI do GitHub Actions
    não alterem o comportamento padrão esperado nos testes unitários e de integração locais.
    """
    # Preserva se o teste explicitamente definir, mas limpa valores automáticos de CI do runner
    if os.environ.get("GITHUB_ACTIONS") == "true":
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
