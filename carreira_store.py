"""Persistência local do acompanhamento de candidaturas (SQLite).

O banco fica na pasta de resultados do usuário. Não contém currículo completo,
chaves de API nem dados de contato; apenas estado das vagas acompanhadas.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

STATUS_VALIDOS = (
    "Encontrada",
    "Favorita",
    "Quero me candidatar",
    "Candidatura enviada",
    "Aguardando resposta",
    "Entrevista agendada",
    "Aprovado",
    "Recusado",
    "Arquivada",
)


def agora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def id_da_vaga(url: str, titulo: str = "", empresa: str = "", cidade: str = "") -> str:
    base = str(url or "").strip() or "|".join((titulo, empresa, cidade))
    return hashlib.sha256(base.casefold().encode("utf-8")).hexdigest()[:32]


def url_valida(url: str) -> bool:
    try:
        p = urlsplit(str(url or "").strip())
        return p.scheme.lower() in {"http", "https"} and bool(p.netloc) and not p.username and not p.password
    except ValueError:
        return False


class CareerStore:
    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho).expanduser().resolve()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    def _conectar(self):
        con = sqlite3.connect(self.caminho, timeout=8)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _inicializar(self):
        with self._conectar() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS applications (
                    job_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    company TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    score REAL NOT NULL DEFAULT 0,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'Encontrada',
                    notes TEXT NOT NULL DEFAULT '',
                    applied_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS application_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES applications(job_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
                CREATE INDEX IF NOT EXISTS idx_applications_favorite ON applications(favorite);
                CREATE TABLE IF NOT EXISTS advice_cache (
                    job_id TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, profile_hash)
                );
                CREATE TABLE IF NOT EXISTS research_sessions (
                    session_id TEXT PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    terms TEXT NOT NULL DEFAULT '[]',
                    city TEXT NOT NULL DEFAULT '',
                    job_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
            """)

    def listar(self) -> dict[str, dict]:
        with self._conectar() as con:
            rows = con.execute("SELECT * FROM applications").fetchall()
        return {r["job_id"]: dict(r) for r in rows}


    def registrar_vagas(self, jobs: list[dict]) -> None:
        """Registra cada vaga vista sem sobrescrever favorito, notas ou etapa existentes."""
        now = agora_iso()
        with self._conectar() as con:
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                job_id = str(job.get("id") or "")
                url = str(job.get("url") or "").strip()
                if not re.fullmatch(r"[a-f0-9]{32}", job_id) or (url and not url_valida(url)):
                    continue
                con.execute("""INSERT INTO applications(job_id,url,title,company,city,source,score,favorite,status,notes,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,0,'Encontrada','',?,?)
                    ON CONFLICT(job_id) DO UPDATE SET url=excluded.url,title=excluded.title,company=excluded.company,
                    city=excluded.city,source=excluded.source,score=excluded.score,updated_at=excluded.updated_at""",
                    (job_id,url,str(job.get("title") or "")[:240],str(job.get("company") or "")[:200],
                     str(job.get("city") or "")[:160],str(job.get("source") or "")[:100],
                     max(0.0,min(100.0,float(job.get("score") or 0))),now,now))

    def atualizar(self, dados: dict) -> dict:
        job_id = str(dados.get("job_id") or "")
        url = str(dados.get("url") or "").strip()
        if not re.fullmatch(r"[a-f0-9]{32}", job_id) or (url and not url_valida(url)):
            raise ValueError("Identificador ou endereço da vaga inválido.")
        status = str(dados.get("status") or "Encontrada")
        if status not in STATUS_VALIDOS:
            raise ValueError("Status de candidatura inválido.")
        notes = str(dados.get("notes") or "")[:4000]
        favorite = 1 if bool(dados.get("favorite")) else 0
        title = str(dados.get("title") or "")[:240]
        company = str(dados.get("company") or "")[:200]
        city = str(dados.get("city") or "")[:160]
        source = str(dados.get("source") or "")[:100]
        try:
            score = max(0.0, min(100.0, float(dados.get("score", 0))))
        except (TypeError, ValueError):
            score = 0.0
        now = agora_iso()
        with self._conectar() as con:
            anterior = con.execute("SELECT status, favorite, notes, created_at, applied_at FROM applications WHERE job_id=?", (job_id,)).fetchone()
            created = anterior["created_at"] if anterior else now
            applied = (anterior["applied_at"] if anterior else None)
            if status == "Candidatura enviada" and not applied:
                applied = now
            con.execute("""
                INSERT INTO applications(job_id,url,title,company,city,source,score,favorite,status,notes,applied_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET
                    url=excluded.url,title=excluded.title,company=excluded.company,city=excluded.city,
                    source=excluded.source,score=excluded.score,favorite=excluded.favorite,
                    status=excluded.status,notes=excluded.notes,applied_at=excluded.applied_at,updated_at=excluded.updated_at
            """, (job_id,url,title,company,city,source,score,favorite,status,notes,applied,created,now))
            old_status = anterior["status"] if anterior else None
            old_favorite = bool(anterior["favorite"]) if anterior else False
            old_notes = anterior["notes"] if anterior else ""
            if old_status != status:
                con.execute(
                    "INSERT INTO application_events(job_id,old_status,new_status,detail,created_at) VALUES(?,?,?,?,?)",
                    (job_id, old_status, status, "Etapa da candidatura atualizada", now),
                )
            if old_favorite != bool(favorite):
                detalhe = "Adicionada aos favoritos" if favorite else "Removida dos favoritos"
                con.execute(
                    "INSERT INTO application_events(job_id,old_status,new_status,detail,created_at) VALUES(?,?,?,?,?)",
                    (job_id, status, status, detalhe, now),
                )
            if old_notes != notes:
                con.execute(
                    "INSERT INTO application_events(job_id,old_status,new_status,detail,created_at) VALUES(?,?,?,?,?)",
                    (job_id, status, status, "Notas de acompanhamento atualizadas", now),
                )
            row = con.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
        return dict(row)

    def eventos(self, job_id: str) -> list[dict]:
        if not re.fullmatch(r"[a-f0-9]{32}", str(job_id or "")):
            return []
        with self._conectar() as con:
            rows = con.execute("SELECT old_status,new_status,detail,created_at FROM application_events WHERE job_id=? ORDER BY id DESC LIMIT 50", (job_id,)).fetchall()
        return [dict(r) for r in rows]

    def obter_conselho(self, job_id: str, profile_hash: str):
        with self._conectar() as con:
            row = con.execute("SELECT payload FROM advice_cache WHERE job_id=? AND profile_hash=?", (job_id, profile_hash)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return None

    def guardar_conselho(self, job_id: str, profile_hash: str, payload: dict):
        now = agora_iso()
        raw = json.dumps(payload, ensure_ascii=False)[:30000]
        with self._conectar() as con:
            con.execute("""INSERT INTO advice_cache(job_id,profile_hash,payload,created_at) VALUES(?,?,?,?)
                ON CONFLICT(job_id,profile_hash) DO UPDATE SET payload=excluded.payload,created_at=excluded.created_at""",
                (job_id, profile_hash, raw, now))

    def registrar_pesquisa(self, payload: dict) -> None:
        """Registra uma execução do painel uma única vez, mesmo se for reaberta."""
        if not isinstance(payload, dict):
            return
        generated = str(payload.get("generated_at") or agora_iso())[:80]
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        terms = payload.get("terms") if isinstance(payload.get("terms"), list) else []
        jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
        job_ids = sorted(str(j.get("id") or "") for j in jobs if isinstance(j, dict))
        material = "|".join((generated, str(metadata.get("cidade") or metadata.get("cidade_candidato") or ""),
                             ",".join(map(str, terms)), ",".join(job_ids)))
        sid = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        with self._conectar() as con:
            con.execute(
                "INSERT OR IGNORE INTO research_sessions(session_id,generated_at,terms,city,job_count,created_at) VALUES(?,?,?,?,?,?)",
                (sid, generated, json.dumps([str(x)[:100] for x in terms[:20]], ensure_ascii=False),
                 str(metadata.get("cidade") or metadata.get("cidade_candidato") or "")[:160], len(jobs), agora_iso()),
            )

    def pesquisas_recentes(self, limite: int = 20) -> list[dict]:
        limite = max(1, min(100, int(limite)))
        with self._conectar() as con:
            rows = con.execute(
                "SELECT session_id,generated_at,terms,city,job_count FROM research_sessions ORDER BY generated_at DESC LIMIT ?",
                (limite,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["terms"] = json.loads(item.get("terms") or "[]")
            except json.JSONDecodeError:
                item["terms"] = []
            items.append(item)
        return items

    def resumo(self) -> dict:
        """Resumo separa vagas simplesmente registradas das que o usuário acompanha."""
        with self._conectar() as con:
            total = con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            acompanhadas = con.execute(
                "SELECT COUNT(*) FROM applications WHERE favorite=1 OR status<>'Encontrada' OR notes<>''"
            ).fetchone()[0]
            favorites = con.execute("SELECT COUNT(*) FROM applications WHERE favorite=1").fetchone()[0]
            rows = con.execute("SELECT status,COUNT(*) AS qtd FROM applications GROUP BY status").fetchall()
        return {
            "registradas": total,
            "acompanhadas": acompanhadas,
            "favoritas": favorites,
            "por_status": {r["status"]: r["qtd"] for r in rows},
        }
