# core/embeddings.py
from __future__ import annotations

import os
import json
import time
import hashlib
import logging
from typing import List, Optional, Any

import numpy as np

from normalizacao import normalizar

logger = logging.getLogger(__name__)

# Modelo padrão (pode ajustar)
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "distiluse-base-multilingual-cased-v1")

# lazy-loaded model (pode ser None se não instalado)
_model = None

def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _model = SentenceTransformer(MODEL_NAME)
        logger.info("SentenceTransformer carregado: %s", MODEL_NAME)
    except Exception as e:
        _model = None
        logger.warning("SentenceTransformer não disponível: %s", e)
    return _model

def _fallback_embedding(texto: str, dim: int = 384) -> List[float]:
    """
    Fallback determinístico: usa SHA256 do texto para gerar vetor de dimensão `dim`.
    Não é semântico como embedding real, mas é determinístico e rápido (útil offline).
    """
    if texto is None:
        texto = ""
    h = hashlib.sha256(texto.encode("utf-8")).digest()
    # expandir digest para vetor float no intervalo [-1,1]
    vals = []
    i = 0
    while len(vals) < dim:
        # use slices de 4 bytes -> uint32 -> normalize
        chunk = h[i % len(h):(i % len(h)) + 4]
        if len(chunk) < 4:
            chunk = chunk.ljust(4, b"\0")
        num = int.from_bytes(chunk, "big", signed=False)
        # map num -> float [-1,1]
        vals.append(((num / 0xFFFFFFFF) * 2.0) - 1.0)
        i += 4
    return vals[:dim]

def calcular_embedding(texto: str) -> List[float]:
    """
    Retorna embedding em formato list[float].
    Tenta usar SentenceTransformer se disponível, caso contrário usa fallback determinístico.
    """
    txt = "" if texto is None else str(texto)
    model = _load_model()
    if model is not None:
        try:
            vec = model.encode([txt], show_progress_bar=False)[0]
            return list(map(float, vec.tolist() if hasattr(vec, "tolist") else vec))
        except Exception as e:
            logger.warning("Erro ao gerar embedding com modelo (%s). Usando fallback. Erro: %s", MODEL_NAME, e)
    # fallback
    return _fallback_embedding(normalizar(txt))

def calcular_embeddings_batch(textos: List[str], batch_size: int = 64) -> List[List[float]]:
    """
    Batch encode: usa modelo quando possível, senão aplica fallback por item.
    """
    if not textos:
        return []
    model = _load_model()
    if model is not None:
        try:
            vectors = model.encode(list(textos), batch_size=batch_size, show_progress_bar=False)
            out = []
            for v in vectors:
                if hasattr(v, "tolist"):
                    out.append(list(map(float, v.tolist())))
                else:
                    out.append(list(map(float, v)))
            return out
        except Exception as e:
            logger.warning("Erro batch encoding (%s). Fallback por item. Erro: %s", MODEL_NAME, e)

    # fallback item-a-item
    return [ _fallback_embedding(normalizar(t or "")) for t in textos ]

def atualizar_embeddings(conn, tabela: str = "perguntas", batch_size: int = 64, throttle_sec: float = 0.0):
    """
    Atualiza embeddings no banco para linhas sem embedding (compatível com seu esquema).
    Gera JSON string para armazenamento.
    """
    if tabela not in ("perguntas", "respostas"):
        raise ValueError("tabela deve ser 'perguntas' ou 'respostas'")

    cur = conn.cursor()
    if tabela == "perguntas":
        cur.execute("SELECT id, texto FROM perguntas WHERE embedding IS NULL OR embedding = ''")
    else:
        cur.execute("SELECT id, texto FROM respostas WHERE embedding_resposta IS NULL OR embedding_resposta = ''")
    rows = cur.fetchall()
    if not rows:
        logger.info("Nenhuma linha sem embedding encontrada em %s", tabela)
        cur.close()
        return

    ids = []
    texts = []
    for r in rows:
        rid = r[0]
        txt = r[1] if len(r) > 1 else ""
        ids.append(rid)
        texts.append(txt or "")

    total = len(ids)
    logger.info("Processando %d entradas sem embedding em '%s' (batch %d)", total, tabela, batch_size)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch_ids = ids[start:end]
        batch_texts = texts[start:end]
        try:
            batch_embs = calcular_embeddings_batch(batch_texts, batch_size=batch_size)
        except Exception as e:
            logger.exception("Erro ao gerar embeddings batch; tentando um-a-um: %s", e)
            batch_embs = []
            for t in batch_texts:
                try:
                    batch_embs.append(calcular_embedding(t))
                except Exception:
                    batch_embs.append(None)

        for rid, emb in zip(batch_ids, batch_embs):
            if not emb:
                continue
            emb_json = json.dumps(emb, ensure_ascii=False)
            try:
                if tabela == "perguntas":
                    cur.execute("UPDATE perguntas SET embedding = %s WHERE id = %s", (emb_json, rid))
                else:
                    cur.execute("UPDATE respostas SET embedding_resposta = %s WHERE id = %s", (emb_json, rid))
            except Exception as e:
                logger.exception("Erro ao atualizar embedding id=%s: %s", rid, e)
        try:
            conn.commit()
        except Exception:
            pass
        logger.info("Batch %d-%d salvo.", start, end)
        if throttle_sec and end < total:
            time.sleep(throttle_sec)

    cur.close()
    logger.info("Embeddings atualizados.")

def atualizar_embedding_resposta(conn, resposta_id: int, embedding: List[float]):
    cur = conn.cursor()
    emb_json = json.dumps(embedding, ensure_ascii=False)
    cur.execute("UPDATE respostas SET embedding_resposta = %s WHERE id = %s", (emb_json, resposta_id))
    try:
        conn.commit()
    except Exception:
        pass
    cur.close()

def validar_palavra_chave(pergunta: str, resposta: str, limite: int = 70) -> bool:
    """
    Usa rapidfuzz se disponível; se não, fallback simples baseado em token overlap.
    """
    try:
        from rapidfuzz import fuzz  # type: ignore
        score = fuzz.token_set_ratio(normalizar(pergunta or ""), normalizar(resposta or ""))
        return score >= limite
    except Exception:
        # fallback simples: proporção de tokens em comum
        q = set(normalizar(pergunta or "").split())
        a = set(normalizar(resposta or "").split())
        if not q:
            return False
        inter = q.intersection(a)
        score = (len(inter) / max(1, len(q))) * 100.0
        return score >= limite

def cosine_similarity(vec1: Any, vec2: Any) -> float:
    """
    Cosine similarity robusta entre dois vetores.
    Aceita listas, numpy arrays, etc.
    """
    try:
        v1 = np.array(vec1, dtype=float)
        v2 = np.array(vec2, dtype=float)
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (n1 * n2))
    except Exception as e:
        logger.debug("Erro cosine_similarity: %s", e)
        return 0.0
