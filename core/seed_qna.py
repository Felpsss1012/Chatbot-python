#!/usr/bin/env python3
"""
seed_qna.py - Importador robusto de QnA (CSV -> banco)

Recursos:
 - valida CSV (colunas 'pergunta' e 'resposta')
 - --dry-run para ver o que seria inserido
 - --update para atualizar perguntas existentes
 - --dedupe-semantic para detectar near-duplicates via embeddings (threshold configurável)
 - --compute-emb para calcular embeddings imediatamente para entradas novas
 - logging, tqdm progress bar e resumo final

Uso:
 python core/seed_qna.py data/meus_qna.csv [--update] [--dry-run] [--dedupe-semantic 0.88] [--compute-emb]
"""
import csv
import sys
import os
import json
import argparse
import logging
from datetime import datetime

from banco import inicializar_banco
from normalizacao import normalizar

# tentativa de importar util de embeddings (opcional)
try:
    from embeddings import calcular_embedding, cosine_similarity
except Exception:
    calcular_embedding = None
    cosine_similarity = None

# tqdm optional
try:
    from tqdm import tqdm
except Exception:
    tqdm = lambda x, **k: x

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_qna")

def _parse_embedding_json(maybe):
    if not maybe:
        return None
    if isinstance(maybe, (list, tuple)):
        return maybe
    try:
        return json.loads(maybe)
    except Exception:
        try:
            s = str(maybe).strip().strip('"')
            return json.loads(s)
        except Exception:
            return None

def fetch_existing_embeddings(conn):
    """Retorna dict {id: embedding_list} para respostas existentes (embedding_resposta quando disponível)."""
    cur = conn.cursor()
    cur.execute("SELECT id, embedding_resposta FROM respostas WHERE embedding_resposta IS NOT NULL AND embedding_resposta != ''")
    rows = cur.fetchall() or []
    res = {}
    for r in rows:
        rid = r[0]
        emb = _parse_embedding_json(r[1])
        if emb:
            res[rid] = emb
    try:
        cur.close()
    except Exception:
        pass
    return res

def semantic_duplicate_check(text_emb, existing_emb_map, threshold=0.9):
    """Retorna True se existir embedding no mapa com cosine >= threshold."""
    if not text_emb or not existing_emb_map or cosine_similarity is None:
        return False
    try:
        for emb in existing_emb_map.values():
            try:
                sim = float(cosine_similarity(text_emb, emb))
            except Exception:
                continue
            if sim >= threshold:
                return True
    except Exception:
        return False
    return False

def importar_csv(path: str, atualizar_existentes: bool=False, dry_run: bool=False,
                 dedupe_semantic: bool=False, dedupe_threshold: float=0.9,
                 compute_emb: bool=False):
    if not os.path.exists(path):
        log.error("Arquivo não encontrado: %s", path)
        return

    conn = inicializar_banco()
    if not conn:
        log.error("Não foi possível inicializar conexão com o banco.")
        return

    cur = conn.cursor()
    inserted_q = inserted_r = updated = skipped = semantic_skipped = 0
    start = datetime.now()

    # carregar embeddings existentes se for dedupe semântico ou compute_emb
    existing_emb_map = {}
    if dedupe_semantic or compute_emb:
        try:
            existing_emb_map = fetch_existing_embeddings(conn)
            log.info("Carregadas %d embeddings existentes para checagem semântica.", len(existing_emb_map))
        except Exception as e:
            log.debug("Falha ao carregar embeddings existentes: %s", e)

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not {"pergunta", "resposta"}.issubset(reader.fieldnames or []):
            log.error("CSV inválido: precisa ter colunas 'pergunta' e 'resposta'")
            cur.close()
            conn.close()
            return

        rows = list(reader)
        for row in tqdm(rows, desc="Processando linhas", unit="lin"):
            pergunta = (row.get("pergunta") or "").strip()
            resposta = (row.get("resposta") or "").strip()
            if not pergunta or not resposta:
                skipped += 1
                continue

            p_norm = normalizar(pergunta)
            r_norm = normalizar(resposta)

            # se dedupe semântico ativo, calcular embedding da resposta/pergunta e comparar
            if dedupe_semantic and calcular_embedding is not None:
                try:
                    emb_q = calcular_embedding(p_norm)
                except Exception:
                    emb_q = None
                # Checamos contra embeddings de respostas existentes
                if emb_q and semantic_duplicate_check(emb_q, existing_emb_map, threshold=dedupe_threshold):
                    semantic_skipped += 1
                    continue

            # evitar duplicata exata de resposta (texto_normalizado)
            cur.execute("SELECT id FROM respostas WHERE texto_normalizado = %s", (r_norm,))
            r = cur.fetchone()
            if r:
                resposta_id = r[0]
            else:
                if dry_run:
                    resposta_id = None
                else:
                    cur.execute("INSERT INTO respostas (texto, texto_normalizado) VALUES (%s, %s)",
                                (resposta, r_norm))
                    resposta_id = cur.lastrowid
                    inserted_r += 1
                    # opcional: registrar embedding novo no map para futuras comparações dentro deste run
                    if compute_emb and calcular_embedding is not None and resposta_id:
                        try:
                            emb_new = calcular_embedding(r_norm)
                            existing_emb_map[resposta_id] = emb_new
                            # gravar direto no campo embedding_resposta
                            cur.execute("UPDATE respostas SET embedding_resposta = %s WHERE id = %s",
                                        (json.dumps(list(map(float, emb_new)), ensure_ascii=False), resposta_id))
                        except Exception:
                            log.debug("Falha ao calcular/gravar embedding para resposta_id=%s", resposta_id)

            # checar pergunta duplicada por normalização
            cur.execute("SELECT id, resposta_id FROM perguntas WHERE texto_normalizado = %s", (p_norm,))
            existing = cur.fetchone()
            if existing:
                if atualizar_existentes:
                    if not dry_run:
                        cur.execute("UPDATE perguntas SET resposta_id = %s WHERE id = %s", (resposta_id, existing[0]))
                    updated += 1
                else:
                    skipped += 1
                continue

            if dry_run:
                inserted_q += 1  # contar como se fosse inserida no dry-run
            else:
                cur.execute("INSERT INTO perguntas (texto, texto_normalizado, resposta_id) VALUES (%s, %s, %s)",
                            (pergunta, p_norm, resposta_id))
                inserted_q += 1

    if not dry_run:
        conn.commit()
    try:
        cur.close()
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass

    elapsed = (datetime.now() - start).total_seconds()
    log.info("Import finalizado: perguntas inseridas=%d respostas inseridas=%d atualizadas=%d ignoradas=%d semantic_skipped=%d tempo=%.2fs",
             inserted_q, inserted_r, updated, skipped, semantic_skipped, elapsed)
    return {
        "inserted_q": inserted_q,
        "inserted_r": inserted_r,
        "updated": updated,
        "skipped": skipped,
        "semantic_skipped": semantic_skipped,
        "time_s": elapsed
    }

def main():
    parser = argparse.ArgumentParser(description="Importador CSV -> DB para QnA (seed)")
    parser.add_argument("csv_path", nargs="?", default=os.path.join("data", "meus_qna.csv"))
    parser.add_argument("--update", action="store_true", help="Atualiza perguntas existentes (por normalização) com nova resposta_id")
    parser.add_argument("--dry-run", action="store_true", help="Não grava nada, só mostra o que aconteceria")
    parser.add_argument("--dedupe-semantic", type=float, nargs="?", const=0.9,
                        help="Ativa checagem semântica e define threshold (0..1). Requer embeddings/calcular_embedding")
    parser.add_argument("--compute-emb", action="store_true", help="Calcula e grava embeddings para novas respostas (requer sentence-transformers)")
    args = parser.parse_args()

    stats = importar_csv(
        args.csv_path,
        atualizar_existentes=args.update,
        dry_run=args.dry_run,
        dedupe_semantic=(args.dedupe_semantic is not None),
        dedupe_threshold=(args.dedupe_semantic or 0.9),
        compute_emb=args.compute_emb
    )
    print("Resumo:", stats)

if __name__ == "__main__":
    main()
