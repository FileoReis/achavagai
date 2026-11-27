"""Garante que importar o parser não carregue o leitor pesado de PDF."""
from pathlib import Path
import subprocess
import sys


def test_importar_resume_parser_nao_carrega_pdfplumber():
    raiz = Path(__file__).resolve().parents[1]
    codigo = (
        "import sys; import resume_parser; "
        "print('pdfplumber' in sys.modules); "
        "print('pdfminer' in sys.modules); "
        "print('cryptography' in sys.modules)"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=raiz,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert resultado.stdout.strip().splitlines() == ["False", "False", "False"]


def test_ajuda_cli_nao_carrega_pdfplumber():
    raiz = Path(__file__).resolve().parents[1]
    resultado = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=raiz,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "AchaVagAI - encontra vagas" in resultado.stdout
    assert "pdfplumber" not in resultado.stderr
    assert "cryptography" not in resultado.stderr
