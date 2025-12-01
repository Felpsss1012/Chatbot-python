# core/gerenciador_respostas.py
from __future__ import annotations

import os
import re
import json
import csv
import logging
import unicodedata
import math
from datetime import date, datetime
from typing import Any, List, Optional, Tuple, Dict

import numpy as np

from config import LOG_DIR
from normalizacao import normalizar, humanize_text
from embeddings import calcular_embedding, cosine_similarity
from banco import buscar_respostas_com_embedding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Configs / constantes
# ---------------------------------------------------------------------
DEFAULT_CSV = os.environ.get("MEUS_QNA_CSV", "data/meus_qna.csv")
SQL_LIMIT = int(os.environ.get("PIPELINE_SQL_LIMIT", "80"))
EMB_WEIGHT_DEFAULT = float(os.environ.get("PIPELINE_EMB_WEIGHT", "0.75"))
KW_WEIGHT_DEFAULT = 1.0 - EMB_WEIGHT_DEFAULT
EMB_THRESHOLD_FALLBACK = float(os.environ.get("PIPELINE_EMB_THRESHOLD", "0.62"))

# -----------------------
# Helpers de query / texto (originais + pipeline)
# -----------------------
def _get_ft_min_word_len(conn, default: int = 4) -> int:
    try:
        cur = conn.cursor()
        cur.execute("SHOW VARIABLES LIKE 'ft_min_word_len'")
        row = cur.fetchone()
        try:
            cur.close()
        except Exception:
            pass
        if row and len(row) >= 2:
            return int(row[1])
    except Exception as e:
        logger.debug("Não foi possível obter ft_min_word_len: %s", e)
    return default


def _tokens_para_boolean_query(texto_norm: str, min_len: int = 3, max_terms: int = 8) -> str:
    tokens = [t.strip() for t in texto_norm.split() if t.strip()]
    tokens = [t for t in tokens if len(t) >= min_len]
    if not tokens:
        tokens = [t for t in texto_norm.split()][:max_terms]
    tokens = tokens[:max_terms]
    boolean = " ".join("+" + t for t in tokens)
    return boolean


def _parse_keywords_field(kws_field: Any) -> List[str]:
    if not kws_field:
        return []
    if isinstance(kws_field, (list, tuple)):
        return list(kws_field)
    try:
        if isinstance(kws_field, str):
            return json.loads(kws_field)
    except Exception:
        try:
            s = str(kws_field)
            return [k.strip() for k in s.split(",") if k.strip()]
        except Exception:
            return []
    return []


def _keyword_overlap_score(q_kws: List[str], cand_kws: List[str]) -> float:
    if not q_kws or not cand_kws:
        return 0.0
    set_q = set(q_kws)
    set_c = set(cand_kws)
    inter = set_q.intersection(set_c)
    return len(inter) / max(len(set_q), 1)

# -----------------------
# Embedding parsing/pick
# -----------------------

def _parse_embedding(emb_str: Any) -> Optional[np.ndarray]:
    if not emb_str:
        return None
    # pode ser JSON string, lista, ou string com vírgulas
    if isinstance(emb_str, (list, tuple)):
        try:
            return np.array(list(map(float, emb_str)), dtype=float)
        except Exception:
            return None
    if isinstance(emb_str, str):
        try:
            parsed = json.loads(emb_str)
            if isinstance(parsed, (list, tuple)):
                return np.array(list(map(float, parsed)), dtype=float)
        except Exception:
            pass
        try:
            parts = [p for p in emb_str.replace("[", "").replace("]", "").split(",") if p.strip()]
            return np.array(list(map(float, parts)), dtype=float)
        except Exception:
            logger.debug("Falha ao parsear embedding (prefix): %s", (emb_str[:80] if emb_str else ""))
            return None
    return None


def _pick_vector_from_row(row: dict) -> Optional[np.ndarray]:
    emb_field = row.get("resposta_embedding") or row.get("embedding_resposta") or row.get("pergunta_embedding") or row.get("embedding")
    return _parse_embedding(emb_field)

# -----------------------
# Conexão
# -----------------------

def _is_connection_obj(obj) -> bool:
    return obj is not None and hasattr(obj, "cursor") and callable(getattr(obj, "cursor"))


def _ensure_connection(conn):
    if _is_connection_obj(conn):
        return conn, False
    try:
        from core import banco as banco_mod
        init = getattr(banco_mod, "inicializar_banco", None)
        if callable(init):
            c = init()
            if _is_connection_obj(c):
                return c, True
    except Exception as e:
        logger.debug("Falha ao inicializar banco via core.banco: %s", e)
    raise RuntimeError("Não foi possível obter conexão MySQL válida. Passe uma conn com cursor()")

# -----------------------
# Pipeline helpers (do pipeline_search.py)
# -----------------------
_RE_NUMBER = re.compile(r"\d+(?:[.,]\d+)?", flags=re.UNICODE)


def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


# num2words é opcional — se não existir mantemos retorno numérico simples
try:
    from num2words import num2words
except Exception:
    num2words = None


def number_to_words_simple(token: str) -> str:
    t = token.replace(",", ".")
    try:
        if num2words:
            if "." in t:
                parts = t.split(".")
                int_part = int(parts[0])
                frac_part = parts[1]
                int_txt = num2words(int_part, lang="pt_BR")
                frac_txt = " ".join([num2words(int(d), lang="pt_BR") for d in frac_part])
                return f"{int_txt} vírgula {frac_txt}"
            else:
                n = int(t)
                return num2words(n, lang="pt_BR")
    except Exception:
        pass
    return " ".join(list(t))


def numbers_to_words_in_text(text: str) -> str:
    def _repl(m):
        tok = m.group(0)
        try:
            return number_to_words_simple(tok)
        except Exception:
            return tok
    return _RE_NUMBER.sub(_repl, text)


def user_requests_only_field(question: str) -> Optional[str]:
    q = strip_accents((question or "").lower())

    if not any(w in q for w in ("so", "apenas", "somente")):
        return None
    if "data" in q:
        return "data"
    if "numero" in q or "nº" in q:
        return "numero"
    if "nome" in q:
        return "nome"
    if "preco" in q or "preço" in q or "valor" in q:
        return "preco"
    return None


def extract_field_from_text(field: str, text: str) -> Optional[str]:
    if not text:
        return None
    t = text

    if field == "data":
        m = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", t)
        if m:
            return m.group(0)
        m = re.search(r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b", t)
        if m:
            return m.group(0)
        m = re.search(r"\b\d{1,2}\s+de\s+\w{3,}\s+de\s+\d{4}\b", t, flags=re.IGNORECASE)
        if m:
            return m.group(0)
        return None

    if field == "numero":
        m = re.search(r"\d+(?:[.,]\d+)?", t)
        return m.group(0) if m else None

    if field == "preco":
        m = re.search(r"R\$\s*\d+(?:[.,]\d+)?", t)
        if m:
            return m.group(0)
        m = re.search(r"\d+(?:[.,]\d+)?\s*(reais|rs|r\$)?", t, flags=re.IGNORECASE)
        return m.group(0) if m else None

    if field == "nome":
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        if lines:
            first = lines[0]
            if len(first.split()) <= 6:
                return first
        m = re.search(r"\b([A-ZÀ-Ý][a-zà-ÿ]{1,}\s?){1,4}\b", t)
        if m:
            return m.group(0).strip()
        return None

    return None

# -----------------------
# DB search (LIKE param)
# -----------------------

def sql_search(conn, normalized_query: str, limit: int = SQL_LIMIT) -> List[Dict[str, Any]]:
    if conn is None:
        return []

    cur = conn.cursor()
    try:
        # obter ft_min_word_len e montar tokens
        ft_min = _get_ft_min_word_len(conn, default=3)
        tokens = [t.strip() for t in normalized_query.split() if t.strip()]
        tokens = [t for t in tokens if len(t) >= ft_min]
        if not tokens:
            tokens = [t.strip() for t in normalized_query.split()][:8]
        tokens = tokens[:12]
        # boolean wildcard: +token*
        boolean_wild = " ".join("+" + t + "*" for t in tokens)

        # consulta FULLTEXT (p/ perguntas e respostas). Se algum MATCH não tiver FT index
        # o execute pode lançar, daí caímos no fallback.
        sql = """
        SELECT
          p.id AS pergunta_id,
          p.texto AS pergunta_texto,
          p.texto_normalizado AS pergunta_norm,
          p.embedding AS pergunta_embedding,
          r.id AS resposta_id,
          r.texto AS resposta_texto,
          r.texto_normalizado AS resposta_norm,
          r.embedding_resposta AS resposta_embedding,
          MATCH(p.texto_normalizado) AGAINST (%s IN BOOLEAN MODE) AS score_p,
          MATCH(r.texto_normalizado) AGAINST (%s IN BOOLEAN MODE) AS score_r
        FROM perguntas p
        LEFT JOIN respostas r ON p.resposta_id = r.id
        WHERE
          MATCH(p.texto_normalizado) AGAINST (%s IN BOOLEAN MODE)
          OR MATCH(r.texto_normalizado) AGAINST (%s IN BOOLEAN MODE)
        ORDER BY GREATEST(
          IFNULL(MATCH(p.texto_normalizado) AGAINST (%s IN BOOLEAN MODE), 0),
          IFNULL(MATCH(r.texto_normalizado) AGAINST (%s IN BOOLEAN MODE), 0)
        ) DESC
        LIMIT %s
        """
        params = (boolean_wild, boolean_wild, boolean_wild, boolean_wild, boolean_wild, boolean_wild, limit)
        cur.execute(sql, params)
        rows = cur.fetchall()

    except Exception as e:
        # fulltext falhou (provavelmente índice faltando ou sintaxe não suportada) -> fallback para LIKE
        logger.debug("FT search failed, falling back to LIKE. Erro: %s", e)
        try:
            like_pat = f"%{normalized_query}%"
            sql2 = """
            SELECT
              p.id AS pergunta_id,
              p.texto AS pergunta_texto,
              p.texto_normalizado AS pergunta_norm,
              p.embedding AS pergunta_embedding,
              r.id AS resposta_id,
              r.texto AS resposta_texto,
              r.texto_normalizado AS resposta_norm,
              r.embedding_resposta AS resposta_embedding
            FROM perguntas p
            LEFT JOIN respostas r ON p.resposta_id = r.id
            WHERE p.texto_normalizado LIKE %s OR r.texto_normalizado LIKE %s
            LIMIT %s
            """
            cur.execute(sql2, (like_pat, like_pat, limit))
            rows = cur.fetchall()
        except Exception as e2:
            logger.debug("LIKE fallback also failed: %s", e2)
            try:
                cur.close()
            except Exception:
                pass
            return []

    # normalize rows into list[dict] with expected keys
    results = []
    # rows may be tuples (default cursor) or dicts depending on connector; handle ambos
    for r in rows:
        rec = {}
        if isinstance(r, dict):
            # keep the same field names
            rec["pergunta_id"] = r.get("pergunta_id")
            rec["pergunta_texto"] = r.get("pergunta_texto")
            rec["pergunta_norm"] = r.get("pergunta_norm")
            rec["pergunta_embedding"] = r.get("pergunta_embedding")
            rec["resposta_id"] = r.get("resposta_id")
            rec["resposta_texto"] = r.get("resposta_texto")
            rec["resposta_norm"] = r.get("resposta_norm")
            rec["resposta_embedding"] = r.get("resposta_embedding")
        else:
            # fallback tuple mapping (compat com implementação antiga)
            keys = ["pergunta_id","pergunta_texto","pergunta_norm","pergunta_embedding",
                    "resposta_id","resposta_texto","resposta_norm","resposta_embedding"]
            for i,k in enumerate(keys):
                rec[k] = r[i] if i < len(r) else None
        results.append(rec)

    try:
        cur.close()
    except Exception:
        pass

    return results

# -----------------------
# Ranking + CSV fallback
# -----------------------

def _parse_embedding_json(maybe_json: Optional[str]) -> Optional[List[float]]:
    if not maybe_json:
        return None
    try:
        return json.loads(maybe_json)
    except Exception:
        try:
            return json.loads(maybe_json.strip().strip('"'))
        except Exception:
            return None


def rank_candidates(candidates: List[Dict[str, Any]], query_emb: Optional[List[float]], query_norm: str,
                    weight_emb: float = EMB_WEIGHT_DEFAULT, weight_kw: float = KW_WEIGHT_DEFAULT) -> List[Tuple[Dict[str, Any], float]]:
    out = []
    q_tokens = set((query_norm or "").split())
    for c in candidates:
        resp_norm = (c.get("resposta_norm") or c.get("pergunta_norm") or "") or ""
        resp_tokens = set(resp_norm.split())
        kw_score = 0.0
        if q_tokens and resp_tokens:
            inter = q_tokens.intersection(resp_tokens)
            kw_score = len(inter) / max(1, len(q_tokens))
        emb_score = 0.0
        if query_emb is not None:
            emb_json = c.get("resposta_embedding") or c.get("pergunta_embedding")
            target_emb = _parse_embedding_json(emb_json)
            if target_emb:
                try:
                    emb_score = float(cosine_similarity(query_emb, target_emb))
                except Exception:
                    emb_score = 0.0
        score = (weight_emb * emb_score) + (weight_kw * kw_score)
        out.append((c, float(score)))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def csv_fallback_search(csv_path: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    if not os.path.exists(csv_path):
        return []
    q_norm = normalizar(query)
    query_emb = None
    try:
        query_emb = calcular_embedding(q_norm)
    except Exception:
        query_emb = None
    results = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            texto = row.get("resposta") or row.get("answer") or row.get("resposta_texto") or row.get("texto") or ""
            texto_norm = row.get("texto_normalizado") or normalizar(texto)
            emb = None
            if row.get("embedding"):
                try:
                    emb = json.loads(row.get("embedding"))
                except Exception:
                    emb = None
            rec = {
                "pergunta_id": row.get("id") or row.get("pergunta_id"),
                "pergunta_texto": row.get("pergunta") or "",
                "pergunta_norm": row.get("pergunta") or "",
                "pergunta_embedding": None,
                "resposta_id": row.get("id") or None,
                "resposta_texto": texto,
                "resposta_norm": texto_norm,
                "resposta_embedding": json.dumps(emb, ensure_ascii=False) if emb else None
            }
            results.append(rec)
    ranked = rank_candidates(results, query_emb, q_norm)
    top = [r for r,score in ranked[:top_k]]
    return top

# -----------------------
# Main pipeline: find_answer
# -----------------------

def find_answer(
    pergunta: str,
    conn=None,
    use_db: bool = True,
    csv_path: str = DEFAULT_CSV,
    top_k: int = 3,
    weight_embedding: float = EMB_WEIGHT_DEFAULT,
    weight_keywords: float = KW_WEIGHT_DEFAULT,
    emb_threshold: float = EMB_THRESHOLD_FALLBACK,
) -> Dict[str, Any]:
    if not pergunta:
        return {"text": "", "raw": "", "source": "none", "id": None, "score": 0.0, "explain": {}}

    q_norm = normalizar(pergunta)

    # 1️⃣ detectar pedidos diretos de data
    def _data_hoje_extenso() -> str:
        meses = [
            "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
        ]
        d = date.today()
        return f"{d.day} de {meses[d.month - 1]} de {d.year}"

    _field_req_early = user_requests_only_field(pergunta)
    if _field_req_early == "data":
        q_raw = strip_accents(pergunta.lower())
        if len(q_raw.split()) <= 6 and not any(x in q_raw for x in (
            "evento", "aniversario", "nascimento", "vencimento", "prazo", "reuniao", "contrato"
        )):
            hoje = _data_hoje_extenso()
            return {
                "text": hoje,
                "raw": hoje,
                "source": "generated",
                "id": None,
                "score": 1.0,
                "explain": {"generated": "today_date", "from_db_attempted": False, "used_csv": False}
            }

    # 2️⃣ calcular embedding
    try:
        query_emb = calcular_embedding(q_norm)
    except Exception:
        query_emb = None

    explain = {"from_db_attempted": False, "attempts": [], "used_csv": False}
    candidates = []
    conn_obj = None
    created_conn = False

    # 3️⃣ tenta várias buscas no banco
    if use_db:
        try:
            conn_obj, created_conn = _ensure_connection(conn)
            explain["from_db_attempted"] = True
            explain["attempts"] = []

            def _try_sql(limit):
                try:
                    c = sql_search(conn_obj, q_norm, limit=limit)
                    explain["attempts"].append({"type": "sql_like", "limit": limit, "count": len(c)})
                    return c
                except Exception as e:
                    logger.debug("Erro SQL_SEARCH (limit=%s): %s", limit, e)
                    return []

            # Tenta limites progressivos — agora com amostras maiores
            for lim in [SQL_LIMIT, max(60, SQL_LIMIT * 2), 120, 200]:
                cands = _try_sql(lim)
                if cands:
                    candidates.extend(cands)
                # se já conseguiu um número razoável de candidatos, interrompe
                if len(cands) >= lim // 2:
                    break

            # ---------------------------------------------------------
            # Tenta full-text (caso o índice esteja criado)
            # ---------------------------------------------------------
            # ---------------------------------------------------------
            # Tenta full-text boolean com tokens +wildcard (mais robusto)
            # ---------------------------------------------------------
            try:
                cur = conn_obj.cursor()
                # pega ft_min_word_len para não descartar tokens curtos
                ft_min = _get_ft_min_word_len(conn_obj, default=3)
                boolean_query = _tokens_para_boolean_query(q_norm, min_len=ft_min, max_terms=12)
                # consulta fulltext nos campos normalizados de perguntas e respostas
                q_ft = f"""
                SELECT
                    p.id AS pergunta_id,
                    p.texto AS pergunta_texto,
                    r.id AS resposta_id,
                    r.texto AS resposta_texto,
                    MATCH(p.texto_normalizado) AGAINST (%s IN BOOLEAN MODE) AS score_p,
                    MATCH(r.texto_normalizado) AGAINST (%s IN BOOLEAN MODE) AS score_r
                FROM perguntas p
                LEFT JOIN respostas r ON p.resposta_id = r.id
                WHERE
                    MATCH(p.texto_normalizado) AGAINST (%s IN BOOLEAN MODE)
                    OR MATCH(r.texto_normalizado) AGAINST (%s IN BOOLEAN MODE)
                LIMIT 200
                """
                params = (boolean_query, boolean_query, boolean_query, boolean_query)
                cur.execute(q_ft, params)
                ft = cur.fetchall()
                explain["attempts"].append({"type": "fulltext_boolean", "count": len(ft)})
                for f in ft:
                    candidates.append({
                        "pergunta_id": f[0],
                        "pergunta_texto": f[1],
                        "resposta_id": f[2],
                        "resposta_texto": f[3],
                        "resposta_norm": normalizar(f[3] or ""),
                    })
                try:
                    cur.close()
                except Exception:
                    pass
            except Exception as e:
                logger.debug("Fulltext falhou (boolean): %s", e)

            # ---------------------------------------------------------
            # Tenta carregar respostas com embeddings salvos no BD
            # ---------------------------------------------------------
            try:
                emb_rows = buscar_respostas_com_embedding(conn_obj)
                explain["attempts"].append({"type": "db_embeddings", "count": len(emb_rows)})
                for rid, texto, emb in emb_rows:
                    candidates.append({
                        "pergunta_id": None,
                        "pergunta_texto": "",
                        "resposta_id": rid,
                        "resposta_texto": texto,
                        "resposta_norm": normalizar(texto),
                        "resposta_embedding": json.dumps(emb, ensure_ascii=False) if emb is not None else None,
                    })
            except Exception as e:
                logger.debug("Erro buscar_respostas_com_embedding: %s", e)

            # ---------------------------------------------------------
            # Contagem de candidatos e de quantos têm embeddings válidos
            # ---------------------------------------------------------
            explain["db_count"] = len(candidates)
            emb_ok = 0
            for c in candidates:
                emb = c.get("resposta_embedding") or c.get("pergunta_embedding")
                if _parse_embedding_json(emb):
                    emb_ok += 1
            explain["db_embeddings_count"] = emb_ok

        except Exception as e:
            logger.debug("Erro geral na busca DB: %s", e)


    # 4️⃣ ranking dos candidatos DB
    ranked_db = rank_candidates(
        candidates, query_emb, q_norm,
        weight_emb=weight_embedding, weight_kw=weight_keywords
    ) if candidates else []

    # melhor score vindo do DB (ou -1 se vazio)
    best_db_score = ranked_db[0][1] if ranked_db else -1.0

    # CSV fallback (somente se DB não trouxe candidatos fortes)
    ranked_csv = []
    explain["used_csv"] = False
    if not ranked_db or (best_db_score < emb_threshold):
        csv_cands = csv_fallback_search(csv_path, pergunta, top_k=top_k)
        explain["used_csv"] = True if csv_cands else False
        if csv_cands:
            ranked_csv = rank_candidates(csv_cands, query_emb, q_norm,
                                         weight_emb=weight_embedding,
                                         weight_kw=weight_keywords)

    # armazenar os melhores scores para telemetria (antes do rerank global)
    best_csv_score = ranked_csv[0][1] if ranked_csv else -1.0
    explain["best_db_score"] = float(best_db_score) if best_db_score is not None else None
    explain["best_csv_score"] = float(best_csv_score) if best_csv_score is not None else None

    # -------------------------
    # Segunda fase: rerank híbrido (amostra unificada e rerank com peso maior para embeddings)
    # -------------------------
    reranked_all = []
    try:
        rerank_sample_size = 100  # quantos candidatos vamos considerar no rerank global
        sample = []
        seen_keys = set()
        for lst in (ranked_db, ranked_csv):
            for rec, sc in lst:
                key = (rec.get("resposta_id") or rec.get("pergunta_id"))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                sample.append(rec)
                if len(sample) >= rerank_sample_size:
                    break
            if len(sample) >= rerank_sample_size:
                break

        explain["rerank_sample_size"] = len(sample)

        if sample:
            # dar mais confiança ao embedding nesta fase
            rerank_emb_w = max(0.7, weight_embedding)
            rerank_kw_w = 1.0 - rerank_emb_w
            reranked_all = rank_candidates(sample, query_emb, q_norm,
                                           weight_emb=rerank_emb_w,
                                           weight_kw=rerank_kw_w)
            explain["rerank_emb_w"] = rerank_emb_w
            explain["rerank_kw_w"] = rerank_kw_w
            explain["reranked_count"] = len(reranked_all)
    except Exception as e:
        logger.debug("Erro na fase de rerank híbrido: %s", e)
        reranked_all = []


    # 5️⃣ se DB não for suficiente, tenta CSV
    ranked_csv = []
    if not ranked_db or best_db_score < emb_threshold:
        csv_cands = csv_fallback_search(csv_path, pergunta, top_k=top_k)
        explain["used_csv"] = True if csv_cands else False
        if csv_cands:
            ranked_csv = rank_candidates(
                csv_cands, query_emb, q_norm,
                weight_emb=weight_embedding, weight_kw=weight_keywords
            )

    best_csv_score = ranked_csv[0][1] if ranked_csv else -1.0

    explain["best_db_score"] = float(best_db_score)
    explain["best_csv_score"] = float(best_csv_score)

    # 6️⃣ seleção de melhor resposta
    chosen, chosen_score, chosen_source = None, 0.0, None

    best_rerank_score = reranked_all[0][1] if reranked_all else -1.0
    
    explain["best_rerank_score"] = float(best_rerank_score) if best_rerank_score is not None else None

    # Ordem de preferência:
    # 1) top do rerank (reranked_all) se tiver score >= emb_threshold
    # 2) melhor do DB se tiver score >= emb_threshold
    # 3) melhor do CSV se tiver score >= emb_threshold
    # 4) top do rerank quando estiver razoavelmente abaixo do threshold (0.9 * threshold)
    # 5) melhor do DB quando estiver em nível aceitável (0.8 * threshold)
    # caso contrário -> sem resposta
    if best_rerank_score >= emb_threshold:
        chosen, chosen_score = reranked_all[0]
    elif best_db_score >= emb_threshold:
        chosen, chosen_score = ranked_db[0]
    elif best_csv_score >= emb_threshold:
        chosen, chosen_score = ranked_csv[0]
    elif best_rerank_score >= (emb_threshold * 0.9):
        # rerank quase no threshold — aceitável como fallback
        chosen, chosen_score = reranked_all[0]
    elif best_db_score >= (emb_threshold * 0.8):
        # DB razoável, aceitável em modo fuzzy (comportamento antigo)
        chosen, chosen_score = ranked_db[0]
    else:
        # nenhuma fonte com confiança suficiente
        try:
            if created_conn and conn_obj:
                conn_obj.close()
        except Exception:
            pass
        return {"text": "Desculpe — não encontrei uma resposta adequada.", "raw": "", "source": "none", "id": None, "score": 0.0, "explain": explain}

    top_rec = chosen
    top_score = float(chosen_score)
    source = chosen_source

    explain["chosen_source"] = chosen_source
    explain["chosen_score"] = float(top_score)

    if top_score < emb_threshold:
        logger.warning("Resposta escolhida com baixa similaridade (%.3f, src=%s)", top_score, chosen_source)

    raw_text = top_rec.get("resposta_texto") or top_rec.get("pergunta_texto") or ""
    fuzzy = top_score < emb_threshold

    # 7️⃣ tratamento de campo solicitado
    field = user_requests_only_field(pergunta)
    final_text = raw_text
    if field:
        extracted = extract_field_from_text(field, raw_text)
        if extracted:
            if field in ("numero", "preco", "data"):
                try:
                    final_text = numbers_to_words_in_text(extracted)
                except Exception:
                    final_text = extracted
            else:
                final_text = extracted
        # se não encontrou, mantém o texto original
    else:
        try:
            final_text = numbers_to_words_in_text(final_text)
        except Exception:
            pass

    src_id = top_rec.get("resposta_id") or top_rec.get("pergunta_id")
    meta = {
        "source": source,
        "resposta_id": src_id,
        "raw_score": top_score,
        "fuzzy": fuzzy,
        "explain": explain
    }

    if created_conn and conn_obj:
        try:
            conn_obj.close()
        except Exception:
            pass

    try:
        final_text = humanize_text(final_text, source_meta=meta, for_tts=False)
    except Exception:
        pass
            
    return {
        "text": final_text,
        "raw": raw_text,
        "source": source,
        "id": src_id,
        "score": top_score,
        "explain": meta
    }


# -----------------------
# Função pública original: buscar_resposta_usuario
# -----------------------

def buscar_resposta_usuario(pergunta: str,
                           conn,
                           limite_similaridade: float = 0.65,
                           max_candidatos: int = 50,
                           weight_embedding: float = 0.5,
                           weight_keywords: float = 0.5,
                           combined_threshold: float = 0.65,
                           top_rerank_k: int = 10,
                           debug_candidates: bool = False,
                           debug_log_path: Optional[str] = None) -> Optional[str]:
    """
    Compatibilidade com main_chat.py: usamos o pipeline integrado (find_answer) e retornamos apenas o texto final
    (pronto para TTS). Parâmetros antigos continuam disponíveis — mapeamos pesos e thresholds para find_answer.
    """
    try:
        # mapear parâmetros para o pipeline
        emb_w = weight_embedding if weight_embedding is not None else EMB_WEIGHT_DEFAULT
        kw_w = weight_keywords if weight_keywords is not None else KW_WEIGHT_DEFAULT
        emb_threshold = limite_similaridade if limite_similaridade is not None else EMB_THRESHOLD_FALLBACK

        result = find_answer(pergunta, conn=conn, use_db=True, csv_path=DEFAULT_CSV,
                             top_k=3, weight_embedding=emb_w, weight_keywords=kw_w, emb_threshold=emb_threshold)
        text = result.get("text") if isinstance(result, dict) else None

        # se estiver vazio ou for mensagem de não-encontrado, retornamos None para o fluxo antigo
        if not text or text.strip().startswith("Desculpe"):
            return None

        # opcional: gravar debug candidates
        if debug_candidates:
            try:
                if debug_log_path is None:
                    try:
                        os.makedirs(LOG_DIR, exist_ok=True)
                    except Exception:
                        pass
                    debug_log_path = os.path.join(LOG_DIR, "candidates_debug.jsonl")
                entry = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "pergunta": pergunta,
                    "result_meta": result.get("explain")
                }
                with open(debug_log_path, "a", encoding="utf-8") as lf:
                    lf.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                logger.debug("Falha ao gravar debug candidates integrado", exc_info=True)

        return text
    except Exception as e:
        logger.error("Erro em buscar_resposta_usuario (integrado): %s", e)
        return None


# -----------------------
# Helper: obter_top_k_respostas (mantido para compatibilidade)
# -----------------------

def obter_top_k_respostas(pergunta: str, conn, k: int = 3, max_candidatos: int = 50,
                          weight_embedding: float = 0.5, weight_keywords: float = 0.5) -> List[str]:
    """Mantive a função original — ela usa a estratégia de buscar candidatos e rerankar (modo simples)."""
    pergunta_norm = normalizar(pergunta) if pergunta else pergunta
    try:
        conn, created = _ensure_connection(conn)
    except Exception:
        try:
            from core import banco as banco_mod
            conn = banco_mod.inicializar_banco()
            created = True
        except Exception:
            conn = None
            created = False

    cursor = None
    try:
        cursor = conn.cursor()
        sql = """
            SELECT p.id AS pid, p.texto AS pergunta_texto, p.texto_normalizado AS pergunta_norm,
                   p.embedding AS pergunta_embedding, p.keywords AS pergunta_keywords,
                   r.id AS rid, r.texto AS resposta_texto,
                   r.texto_normalizado AS resposta_norm, r.embedding_resposta AS resposta_embedding
            FROM perguntas p
            JOIN respostas r ON p.resposta_id = r.id
            LIMIT %s
        """
        cursor.execute(sql, (max_candidatos,))
        candidatos = cursor.fetchall() or []

        try:
            q_emb = calcular_embedding(pergunta_norm)
        except Exception:
            q_emb = None

        scored = []
        q_toks = [t for t in re.findall(r"[^\W\d_]+", pergunta_norm or "", flags=re.UNICODE) if len(t) > 1]
        q_kws = q_toks[:10]

        for row in candidatos:
            # adaptar row para dict caso venha como tupla
            if not isinstance(row, dict):
                continue
            cand_vec = _pick_vector_from_row(row)
            emb_sim = 0.0
            if q_emb is not None and cand_vec is not None:
                try:
                    emb_sim = float(cosine_similarity(q_emb, cand_vec))
                except Exception:
                    emb_sim = 0.0
            cand_kws = _parse_keywords_field(row.get("pergunta_keywords") or row.get("keywords"))
            kw_score = _keyword_overlap_score(q_kws, cand_kws)
            combined = weight_embedding * emb_sim + weight_keywords * kw_score
            scored.append((combined, row.get("resposta_texto")))

        scored.sort(key=lambda t: t[0], reverse=True)
        respostas = [r for _, r in scored[:k]]
        return respostas

    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if created and conn:
                conn.close()
        except Exception:
            pass
