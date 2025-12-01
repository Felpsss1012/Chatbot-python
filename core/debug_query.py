# core/debug_query.py
import sys
import json
import banco
import pipeline_search
from gerenciador_respostas import find_answer, rank_candidates, _parse_embedding_json, normalizar

def debug_query(q):
    conn = banco.inicializar_banco()
    q_norm = normalizar(q)
    print("QUERY:", q)
    print("NORMALIZADA:", q_norm)
    # 1) candidatos do sql_search direto
    cands = pipeline_search.sql_search(conn, q_norm, limit=200)
    print("sql_search candidatos:", len(cands))
    for i,c in enumerate(cands[:20],1):
        emb = c.get("resposta_embedding") or c.get("pergunta_embedding")
        emb_ok = bool(_parse_embedding_json(emb))
        print(f"{i:02d}. pid={c.get('pergunta_id')} rid={c.get('resposta_id')} emb_ok={emb_ok}")
        print("    pergunta:", (c.get("pergunta_texto") or "")[:140])
        print("    resposta:", (c.get("resposta_texto") or "")[:140])
    # 2) run find_answer and show explain
    res = find_answer(q, conn=conn, use_db=True, csv_path=pipeline_search.DEFAULT_CSV, top_k=5)
    print("\n== find_answer result ==")
    print(json.dumps(res.get("explain"), ensure_ascii=False, indent=2))
    print("TEXT:", res.get("text"))
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python core/debug_query.py \"sua pergunta aqui\"")
    else:
        debug_query(sys.argv[1])
