# core/banco.py
from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from typing import Optional, List, Tuple, Any

import mysql.connector
from mysql.connector import pooling, Error

from config import BANCO_SQL  # path para banco.sql (data/)
from normalizacao import normalizar

logger = logging.getLogger("core.banco")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# CONFIG via environment (NUNCA commit senha no código)
MYSQL_HOST = os.getenv("DB_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("DB_PORT", "3306"))
MYSQL_USER = os.getenv("DB_USER", "root")
MYSQL_PASS = os.getenv("DB_PASS", "Felps_root1012")  # configure via env var
MYSQL_DB = os.getenv("DB_NAME", "chatbot")
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "4"))
POOL_NAME = os.getenv("DB_POOL_NAME", "chatbot_pool")

MYSQL_CONFIG = {
    "host": MYSQL_HOST,
    "port": MYSQL_PORT,
    "user": MYSQL_USER,
    "password": MYSQL_PASS,
    "database": MYSQL_DB,
    "charset": "utf8mb4",
    "use_unicode": True,
}

# Tentativa de criar pool (se falhar, usaremos conexões diretas)
_pool: Optional[pooling.MySQLConnectionPool] = None
try:
    _pool = pooling.MySQLConnectionPool(pool_name=POOL_NAME, pool_size=POOL_SIZE, **MYSQL_CONFIG)
    logger.info("Pool de conexões criado: %s (size=%d)", POOL_NAME, POOL_SIZE)
except Exception as e:
    logger.warning("Não foi possível criar pool de conexões (%s). Usando conexões diretas. Erro: %s", POOL_NAME, e)
    _pool = None


@contextmanager
def get_conn():
    """
    Context manager que fornece uma conexão pronta e garante close.
    Usa pool se disponível, senão cria conexão direta.
    """
    conn = None
    try:
        if _pool:
            conn = _pool.get_connection()
        else:
            conn = mysql.connector.connect(**MYSQL_CONFIG)
        yield conn
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _execute_sql_file(path: str, conn) -> None:
    """
    Executa statements SQL contidos em arquivo (compatível com vários drivers).
    Se encontrar ALTER TABLE ... ADD COLUMN <col>, checa information_schema e pula quando coluna já existe.
    """
    import re
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"Arquivo SQL não encontrado: {path}")

    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()

    cur = conn.cursor()
    try:
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        alter_add_re = re.compile(r"ALTER\s+TABLE\s+`?(\w+)`?\s+ADD\s+COLUMN\s+`?(\w+)`?", re.IGNORECASE)
        for stmt in statements:
            try:
                m = alter_add_re.search(stmt)
                if m:
                    table = m.group(1)
                    col = m.group(2)
                    # checar existence via information_schema
                    check_sql = ("SELECT COUNT(*) FROM information_schema.COLUMNS "
                                 "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s")
                    cur.execute(check_sql, (table, col))
                    exists = cur.fetchone()
                    if exists and exists[0] > 0:
                        logger.info("Coluna %s.%s já existe — pulando ALTER.", table, col)
                        continue
                cur.execute(stmt)
                try:
                    _ = cur.fetchall()
                except Exception:
                    pass
            except Exception as e:
                logger.exception("Erro ao executar statement SQL (ignorando e continuando): %s", e)
        try:
            conn.commit()
        except Exception:
            pass
    finally:
        try:
            cur.close()
        except Exception:
            pass


def inicializar_banco(ensure_schema: bool = True):
    """
    Retorna uma conexão pronta.
    Se ensure_schema=True e existir core.config.BANCO_SQL, aplica o script SQL para criar schema/tabelas.
    """
    # tenta criar conexão direta (não via pool) para inicialização segura
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
    except Exception as e:
        logger.error("Falha ao conectar ao banco: %s", e)
        raise

    # aplica script SQL se existir
    if ensure_schema:
        try:
            if BANCO_SQL and os.path.exists(BANCO_SQL):
                logger.info("Inicializando schema a partir de: %s", BANCO_SQL)
                _execute_sql_file(BANCO_SQL, conn)
            else:
                logger.info("Arquivo banco.sql não encontrado em core.config.BANCO_SQL; assumindo schema já existente.")
        except Exception as e:
            logger.exception("Erro ao executar banco.sql: %s", e)
    return conn


# ---------------------------
# CRUD e helpers úteis
# ---------------------------
def _dict_cursor(conn):
    return conn.cursor(dictionary=True)


def inserir_resposta(conn, texto: str) -> int:
    texto_norm = normalizar(texto)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO respostas (texto, texto_normalizado) VALUES (%s, %s)", (texto, texto_norm))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        try: cur.close()
        except Exception: pass


def inserir_pergunta(conn, texto: str, resposta_id: Optional[int] = None) -> int:
    texto_norm = normalizar(texto)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO perguntas (texto, texto_normalizado, resposta_id) VALUES (%s, %s, %s)",
                    (texto, texto_norm, resposta_id))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        try: cur.close()
        except Exception: pass


def inserir_qna(conn, pergunta: str, resposta: str) -> Tuple[int, int]:
    rid = inserir_resposta(conn, resposta)
    pid = inserir_pergunta(conn, pergunta, rid)
    return pid, rid


def listar_memorias(conn, tipo: Optional[str] = None) -> List[Tuple]:
    cur = conn.cursor()
    try:
        if tipo:
            cur.execute("SELECT id, tipo, descricao, data_evento, repetir_anualmente, prioridade, tags FROM memoria_pessoal WHERE tipo=%s", (tipo,))
        else:
            cur.execute("SELECT id, tipo, descricao, data_evento, repetir_anualmente, prioridade, tags FROM memoria_pessoal")
        return cur.fetchall()
    finally:
        try: cur.close()
        except Exception: pass


def adicionar_memoria(conn, tipo, descricao, data_evento=None, repetir_anualmente=False, prioridade=None, tags=None) -> int:
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO memoria_pessoal (tipo, descricao, data_evento, repetir_anualmente, prioridade, tags)
            VALUES (%s, %s, %s, %s, %s, %s)
            """, (tipo, descricao, data_evento, bool(repetir_anualmente), prioridade, tags))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        try: cur.close()
        except Exception: pass


def remover_memoria_por_id(conn, memoria_id: int) -> None:
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM memoria_pessoal WHERE id = %s", (memoria_id,))
        conn.commit()
    finally:
        try: cur.close()
        except Exception: pass


def editar_memoria(conn, memoria_id: int, nova_descricao: Optional[str] = None, nova_data: Optional[str] = None,
                   nova_prioridade: Optional[str] = None, nova_tags: Optional[str] = None) -> None:
    cur = conn.cursor()
    try:
        sets = []
        params = []
        if nova_descricao is not None:
            sets.append("descricao = %s"); params.append(nova_descricao)
        if nova_data is not None:
            sets.append("data_evento = %s"); params.append(nova_data)
        if nova_prioridade is not None:
            sets.append("prioridade = %s"); params.append(nova_prioridade)
        if nova_tags is not None:
            sets.append("tags = %s"); params.append(nova_tags)
        if not sets:
            return
        sql = "UPDATE memoria_pessoal SET " + ", ".join(sets) + " WHERE id = %s"
        params.append(memoria_id)
        cur.execute(sql, tuple(params))
        conn.commit()
    finally:
        try: cur.close()
        except Exception: pass


def get_id_memoria_por_posicao(conn, tipo_desejado: str, posicao: int) -> Optional[int]:
    if tipo_desejado not in ["tarefa", "evento", "aniversario", "lembrete"]:
        return None
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id FROM memoria_pessoal
            WHERE tipo = %s
            ORDER BY COALESCE(data_evento, '9999-12-31') ASC
        """, (tipo_desejado,))
        resultados = cur.fetchall()
        if 0 < posicao <= len(resultados):
            return int(resultados[posicao - 1][0])
        return None
    finally:
        try: cur.close()
        except Exception: pass


def buscar_memorias_proximas(conn, dias=14) -> List[Tuple]:
    cur = conn.cursor()
    try:
        from datetime import datetime, timedelta
        agora = datetime.now()
        limite = agora + timedelta(days=dias)
        cur.execute("""
            SELECT tipo, descricao, data_evento FROM memoria_pessoal
            WHERE data_evento IS NOT NULL AND data_evento BETWEEN %s AND %s
            ORDER BY data_evento ASC
        """, (agora, limite))
        return cur.fetchall()
    finally:
        try: cur.close()
        except Exception: pass


def gerar_alertas(conn) -> str:
    proximas = buscar_memorias_proximas(conn)
    if not proximas:
        return "Nenhum lembrete nas próximas semanas."
    mensagens = ["🔔 Lembretes próximos:"]
    for tipo, descricao, data_evento in proximas:
        try:
            data_formatada = data_evento.strftime("%d/%m/%Y %H:%M")
        except Exception:
            data_formatada = str(data_evento)
        mensagens.append(f"- [{(tipo or '').capitalize()}] {descricao or 'Sem descrição'} em {data_formatada}")
    return "\n".join(mensagens)


# ---------------------------
# Embeddings helpers (DB)
# ---------------------------
def buscar_respostas_com_embedding(conn) -> List[Tuple[int, str, Optional[list]]]:
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, texto, embedding_resposta FROM respostas WHERE embedding_resposta IS NOT NULL")
        out = []
        for r in cur.fetchall():
            emb = None
            if r.get('embedding_resposta'):
                try:
                    import json
                    emb = json.loads(r['embedding_resposta'])
                except Exception:
                    try:
                        emb = [float(x) for x in str(r['embedding_resposta']).split(',') if x != '']
                    except Exception:
                        emb = None
            out.append((int(r['id']), r['texto'], emb))
        return out
    finally:
        try: cur.close()
        except Exception: pass


def atualizar_embedding_resposta(conn, resposta_id: int, embedding: list) -> None:
    cur = conn.cursor()
    import json
    try:
        cur.execute("UPDATE respostas SET embedding_resposta = %s WHERE id = %s", (json.dumps(embedding, ensure_ascii=False), resposta_id))
        conn.commit()
    finally:
        try: cur.close()
        except Exception: pass


def atualizar_embedding_pergunta(conn, pergunta_id: int, embedding: list) -> None:
    cur = conn.cursor()
    import json
    try:
        cur.execute("UPDATE perguntas SET embedding = %s WHERE id = %s", (json.dumps(embedding, ensure_ascii=False), pergunta_id))
        conn.commit()
    finally:
        try: cur.close()
        except Exception: pass


def buscar_resposta_por_pergunta_fulltext(conn, pergunta: str, top_n: int = 3) -> Optional[str]:
    texto_norm = normalizar(pergunta)
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT p.id, p.texto, p.texto_normalizado, r.texto AS resposta, MATCH(p.texto_normalizado) AGAINST (%s IN NATURAL LANGUAGE MODE) AS score
            FROM perguntas p
            JOIN respostas r ON p.resposta_id = r.id
            WHERE MATCH(p.texto_normalizado) AGAINST (%s IN NATURAL LANGUAGE MODE)
            ORDER BY score DESC
            LIMIT %s
        """, (texto_norm, texto_norm, top_n))
        rows = cur.fetchall()
        if rows:
            return rows[0]['resposta']
        return None
    finally:
        try: cur.close()
        except Exception: pass


def buscar_resposta_por_pergunta_embedding(conn, pergunta: str, top_n: int = 3, threshold: float = 0.60) -> Optional[str]:
    # Lazy import para evitar dependência pesada no momento do import do módulo
    from core.embeddings import calcular_embedding, cosine_similarity
    q_emb = calcular_embedding(pergunta)
    if not q_emb:
        return None
    candidates = buscar_respostas_com_embedding(conn)
    scored = []
    for rid, texto, emb in candidates:
        if emb:
            try:
                sim = float(cosine_similarity(q_emb, emb))
            except Exception:
                sim = 0.0
            scored.append((sim, texto))
    scored.sort(reverse=True, key=lambda t: t[0])
    if scored and scored[0][0] >= threshold:
        return scored[0][1]
    return None
