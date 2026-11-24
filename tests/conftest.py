"""Configuração comum dos testes. Rode com:  python -m pytest"""

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


@dataclass
class FakeVaga:
    """Imita a classe Vaga de scrapers/base.py (só os campos que o código usa),
    para os testes funcionarem mesmo sem a pasta scrapers."""
    titulo: str = ""
    empresa: str = ""
    cidade: str = ""
    descricao: str = ""
    link: str = ""
    fonte: str = "Teste"
    data_publicacao: str = ""
    termo_busca: str = ""


@pytest.fixture
def vaga():
    return FakeVaga


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Garante que nenhum teste use chaves reais nem espere de verdade."""
    for nome in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3",
                 "JOOBLE_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_MODEL", "CLAUDE_MODEL", "IA_PROVEDOR"):
        monkeypatch.delenv(nome, raising=False)
    import ia
    monkeypatch.setattr(ia, "_dormir", lambda segundos: None)
    monkeypatch.setattr(ia, "_desativada", False)
    monkeypatch.setattr(ia, "aviso_callback", None)
    monkeypatch.setattr(ia, "_bloqueados", {})
    monkeypatch.setattr(ia, "_preferido", None)
    monkeypatch.setattr(ia, "arquivo_preferencia", None)
    ia.ultimo_erro = None
    ia.modelo_usado = None
