"""
pipeline_search.py
Módulo autocontido para:
 - normalizar pergunta
 - buscar de forma segura no MySQL (parametrizado)
 - fallback local via meus_qna.csv + embeddings
 - formatação leve: números por extenso, extração quando usuário pede "só a data", "só o número", etc.
 - retorna texto pronto para TTS e meta (fonte/id/similaridade)

Dependências (já instaladas por você): mysql-connector-python, numpy, num2words
Reutiliza: normalizacao.normalizar, banco.inicializar_banco, core.embeddings (calcular_embedding, cosine_similarity)
"""

from __future__ import annotations
import json
import csv
import re
from typing import Optional, List, Dict, Any, Tuple
import os
from datetime import date
import unicodedata
import math

# bibliotecas do seu projeto (assume que estão presentes)
try:
    from core.normalizacao import normalizar
except Exception:
    def normalizar(s: str) -> str:
        return (s or "").strip().casefold()

try:
    from core.banco import inicializar_banco
except Exception:
    inicializar_banco = None

try:
    import core.embeddings as embmod
except Exception:
    embmod = None

try:
    from num2words import num2words
except Exception:
    num2words = None

# parâmetros configuráveis
DEFAULT_CSV = os.environ.get("MEUS_QNA_CSV", "meus_qna.csv")
SQL_LIMIT = int(os.environ.get("PIPELINE_SQL_LIMIT", "200"))
EMB_WEIGHT = float(os.environ.get("PIPELINE_EMB_WEIGHT", "0.75"))
KW_WEIGHT = 1.0 - EMB_WEIGHT
EMB_THRESHOLD_FALLBACK = float(os.environ.get("PIPELINE_EMB_THRESHOLD", "0.62"))


# ---------------------------------------------------------------------
# Helpers: text formatting & intent detection
# ---------------------------------------------------------------------
_RE_NUMBER = re.compile(r"\d+(?:[.,]\d+)?", flags=re.UNICODE)


def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


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
    """
    Detecta intenção simples do usuário pedindo "só" algo (com ou sem acento).
    """
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


# ---------------------------------------------------------------------
# DB search
# ---------------------------------------------------------------------
def sql_search(conn, normalized_query: str, limit: int = SQL_LIMIT) -> List[Dict[str, Any]]:
    if conn is None:
        return []

    cur = conn.cursor()
    like_pat = f"%{normalized_query}%"
    sql = """
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
    try:
        cur.execute(sql, (like_pat, like_pat, limit))
        rows = cur.fetchall()
    except Exception:
        try:
            sql2 = "SELECT id, texto, texto_normalizado, embedding FROM perguntas WHERE texto_normalizado LIKE %s LIMIT %s"
            cur.execute(sql2, (like_pat, limit))
            rows0 = cur.fetchall()
            rows = [(r[0], r[1], r[2], r[3], None, None, None, None) for r in rows0]
        except Exception:
            cur.close()
            return []
    results = []
    for r in rows:
        rec = {}
        keys = ["pergunta_id","pergunta_texto","pergunta_norm","pergunta_embedding",
                "resposta_id","resposta_texto","resposta_norm","resposta_embedding"]
        for i,k in enumerate(keys):
            rec[k] = r[i] if i < len(r) else None
        results.append(rec)
    cur.close()
    return results


# ---------------------------------------------------------------------
# Ranking + fallback CSV
# ---------------------------------------------------------------------
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
                    weight_emb: float = EMB_WEIGHT, weight_kw: float = KW_WEIGHT) -> List[Tuple[Dict[str, Any], float]]:
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
        if query_emb is not None and embmod is not None:
            emb_json = c.get("resposta_embedding") or c.get("pergunta_embedding")
            target_emb = _parse_embedding_json(emb_json)
            if target_emb:
                try:
                    emb_score = float(embmod.cosine_similarity(query_emb, target_emb))
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
    query_emb = embmod.calcular_embedding(q_norm) if embmod else None
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


# ---------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------
def find_answer(
    pergunta: str,
    conn=None,
    use_db: bool = True,
    csv_path: str = DEFAULT_CSV,
    top_k: int = 3,
    weight_embedding: float = EMB_WEIGHT,
    weight_keywords: float = KW_WEIGHT,
    emb_threshold: float = EMB_THRESHOLD_FALLBACK,
) -> Dict[str, Any]:

    if not pergunta:
        return {"text": "", "raw": "", "source": "none", "id": None, "score": 0.0, "explain": {}}

    q_norm = normalizar(pergunta)

    def _data_hoje_extenso() -> str:
        meses = ["janeiro","fevereiro","março","abril","maio","junho",
                 "julho","agosto","setembro","outubro","novembro","dezembro"]
        d = date.today()
        return f"{d.day} de {meses[d.month-1]} de {d.year}"

# detectar se o usuário quer "só a data" ANTES de qualquer busca
    _field_req_early = user_requests_only_field(pergunta)
    if _field_req_early == "data":
        q_raw = strip_accents(pergunta.lower())
        # ignorar frases muito curtas, tipo "me diga só a data", "só a data", etc.
        if len(q_raw.split()) <= 6 and not any(x in q_raw for x in (
            "evento","aniversario","nascimento","vencimento","prazo","reuniao","contrato"
        )):
            hoje = _data_hoje_extenso()
            formatted = f"{hoje}\n\nFonte: (gerado)"
            return {
                "text": formatted,
                "raw": hoje,
                "source": "generated",
                "id": None,
                "score": 1.0,
                "explain": {
                    "generated": "today_date",
                    "from_db_attempted": False,
                    "used_csv": False
                }
            }
    

    query_emb = None
    try:
        if embmod:
            query_emb = embmod.calcular_embedding(q_norm)
    except Exception:
        query_emb = None

    candidates = []
    explain = {"from_db_attempted": False, "db_count": 0, "used_csv": False}
    if use_db and inicializar_banco is not None:
        conn_local = conn or inicializar_banco()
        try:
            explain["from_db_attempted"] = True
            candidates = sql_search(conn_local, q_norm, limit=SQL_LIMIT)
            explain["db_count"] = len(candidates)
        finally:
            if conn is None and conn_local:
                try:
                    conn_local.close()
                except Exception:
                    pass

    ranked = rank_candidates(candidates, query_emb, q_norm, weight_emb=weight_embedding, weight_kw=weight_keywords) if candidates else []

    if not ranked or (ranked and ranked[0][1] < emb_threshold):
        csv_cands = csv_fallback_search(csv_path, pergunta, top_k=top_k)
        explain["used_csv"] = True if csv_cands else False
        if csv_cands:
            ranked_csv = rank_candidates(csv_cands, query_emb, q_norm, weight_emb=weight_embedding, weight_kw=weight_keywords)
            ranked = (ranked or []) + ranked_csv
            ranked.sort(key=lambda t: t[1], reverse=True)

    if not ranked:
        return {"text": "Desculpe — não encontrei uma resposta adequada.", "raw": "", "source": "none", "id": None, "score": 0.0, "explain": explain}

    top_rec, top_score = ranked[0]
    raw_text = top_rec.get("resposta_texto") or top_rec.get("pergunta_texto") or ""
    source = "db" if explain.get("db_count",0) > 0 and top_rec.get("resposta_id") else ("csv" if explain.get("used_csv") else "db")
    fuzzy = top_score < emb_threshold

    field = user_requests_only_field(pergunta)
    final_text = raw_text
    extracted = None
    if field:
        extracted = extract_field_from_text(field, raw_text)
        if extracted:
            if field in ("numero","preco","data"):
                try:
                    extracted_for_tts = numbers_to_words_in_text(extracted)
                except Exception:
                    extracted_for_tts = extracted
            else:
                extracted_for_tts = extracted
            final_text = extracted_for_tts
        else:
            final_text = raw_text

    if not field:
        try:
            final_text = numbers_to_words_in_text(final_text)
        except Exception:
            pass

    src_id = top_rec.get("resposta_id") or top_rec.get("pergunta_id")
    meta = {
        "source": source,
        "resposta_id": src_id,
        "raw_score": float(top_score),
        "fuzzy": bool(fuzzy),
        "explain": explain
    }
    formatted = f"{final_text}\n\nFonte: #{src_id} ({source})"
    if fuzzy:
        formatted += f" — similaridade baixa ({top_score:.2f})"

    return {
        "text": formatted,
        "raw": raw_text,
        "source": source,
        "id": src_id,
        "score": float(top_score),
        "explain": meta
    }
