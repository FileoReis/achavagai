"""
historico.py
Memória local entre uma execução e outra. Faz duas coisas:

1. Marca as vagas NOVAS: as que não apareceram nos resultados de execuções
   anteriores. Quem roda o script todo dia vê logo o que é novidade.
2. Guarda em cache a nota e o motivo que a IA deu a cada vaga. Na próxima execução,
   as vagas que continuam abertas reaproveitam a nota e NÃO gastam chamadas de IA
   (importante no plano gratuito, que tem limite de uso). A nota só vale se o
   currículo, a cidade de busca e as regras do prompt forem os mesmos, e por
   CACHE_VALIDADE_DIAS dias.

O arquivo (HISTORICO_ARQUIVO no config.py) é um JSON simples na pasta do projeto,
só com links e notas. NÃO guarda o texto do currículo (só uma impressão digital
dele para saber se mudou). Para recomeçar do zero, apague o arquivo. Se ele estiver
corrompido ou o disco recusar a gravação, o script segue normalmente, sem histórico.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

from filtros import chave_duplicata, normalizar_link

VERSAO_ARQUIVO = 1
DIAS_PARA_ESQUECER = 60  # vagas não vistas há mais tempo que isso saem do arquivo


def chave_da_vaga(vaga) -> str:
    """Identificador estável da vaga: o link sem parâmetros de rastreamento ou, se
    não houver link, título + empresa + cidade."""
    link = normalizar_link(getattr(vaga, "link", "") or "")
    if link:
        return link
    chave = chave_duplicata(vaga)
    return "|".join(chave) if chave else ""


def chave_do_contexto(texto_curriculo: str, contexto: dict | None, versao_prompt: str) -> str:
    """Impressão digital de tudo que, se mudar, torna as notas antigas inválidas."""
    contexto = contexto or {}
    base = "\x1f".join([
        versao_prompt,
        texto_curriculo or "",
        str(contexto.get("cidade", "")),
        str(contexto.get("bairro", "")),
        str(contexto.get("uf", "")),
        str(contexto.get("cnh", "")),
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


class Historico:
    def __init__(
        self,
        caminho: str | Path | None = None,
        validade_dias: int = 14,
        hoje: date | None = None,
        usar_cache: bool = True,
    ):
        self.caminho = Path(caminho) if caminho else None
        self.validade_dias = int(validade_dias)
        self.hoje = hoje or date.today()
        self.usar_cache = usar_cache
        self.vagas: dict[str, dict] = {}
        self.primeira_execucao = True  # sem arquivo anterior, nada é "novo"
        self.aviso: str | None = None
        self._carregar()

    # -- leitura e gravação -------------------------------------------------

    def _carregar(self) -> None:
        if not self.caminho or not self.caminho.is_file():
            return
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            vagas = dados.get("vagas")
            if dados.get("versao") != VERSAO_ARQUIVO or not isinstance(vagas, dict):
                raise ValueError("formato desconhecido")
        except (OSError, ValueError, AttributeError):
            self.aviso = "O arquivo de histórico estava ilegível e foi ignorado (um novo será criado)."
            return
        self.vagas = {k: v for k, v in vagas.items() if isinstance(v, dict)}
        self.primeira_execucao = False

    def salvar(self) -> bool:
        """Grava o arquivo (de forma atômica). Devolve False se não conseguiu."""
        if not self.caminho:
            return False
        limite = self.hoje - timedelta(days=DIAS_PARA_ESQUECER)
        mantidas = {}
        for chave, entrada in self.vagas.items():
            ultima = self._data(entrada.get("ultima_vez")) or self._data((entrada.get("avaliacao") or {}).get("data"))
            if ultima and ultima >= limite:
                mantidas[chave] = entrada
        self.vagas = mantidas
        conteudo = json.dumps(
            {"versao": VERSAO_ARQUIVO, "atualizado_em": self.hoje.isoformat(), "vagas": self.vagas},
            ensure_ascii=False, indent=1,
        )
        temporario = self.caminho.with_name(self.caminho.name + ".tmp")
        try:
            temporario.write_text(conteudo, encoding="utf-8")
            os.replace(temporario, self.caminho)
        except OSError:
            return False
        return True

    @staticmethod
    def _data(texto) -> date | None:
        try:
            return date.fromisoformat(str(texto))
        except ValueError:
            return None

    def _entrada(self, vaga) -> dict:
        chave = chave_da_vaga(vaga)
        if not chave:
            return {}  # vaga sem como ser identificada: nada é guardado
        return self.vagas.setdefault(chave, {})

    # -- vagas novas ----------------------------------------------------------

    def eh_nova(self, vaga) -> bool:
        """True se a vaga não apareceu em nenhuma execução anterior. Na primeira
        execução devolve sempre False (marcar tudo como novo não ajudaria)."""
        if self.primeira_execucao:
            return False
        chave = chave_da_vaga(vaga)
        return bool(chave) and not (self.vagas.get(chave) or {}).get("primeira_vez")

    def registrar_vistas(self, vagas: list) -> None:
        """Anota que estas vagas foram mostradas hoje. Chame DEPOIS de usar eh_nova."""
        hoje = self.hoje.isoformat()
        for vaga in vagas:
            entrada = self._entrada(vaga)
            if entrada is not None and chave_da_vaga(vaga):
                entrada.setdefault("primeira_vez", hoje)
                entrada["ultima_vez"] = hoje

    # -- cache de notas da IA ---------------------------------------------------

    def nota_em_cache(self, vaga, chave_contexto: str) -> tuple[float, str] | None:
        if not self.usar_cache:
            return None
        avaliacao = (self.vagas.get(chave_da_vaga(vaga)) or {}).get("avaliacao")
        if not isinstance(avaliacao, dict) or avaliacao.get("ctx") != chave_contexto:
            return None
        data = self._data(avaliacao.get("data"))
        if not data or (self.hoje - data).days > self.validade_dias:
            return None
        try:
            return float(avaliacao["nota"]), str(avaliacao.get("motivo", ""))
        except (KeyError, TypeError, ValueError):
            return None

    def guardar_avaliacao(self, vaga, chave_contexto: str, nota: float, motivo: str) -> None:
        entrada = self._entrada(vaga)
        if chave_da_vaga(vaga):
            entrada["avaliacao"] = {
                "ctx": chave_contexto,
                "nota": round(float(nota), 1),
                "motivo": motivo,
                "data": self.hoje.isoformat(),
            }
