#!/usr/bin/env python3
"""
keywords_seed.py - Gerador avançado de keywords para tabela 'perguntas'

Recursos:
 - stemming + lematização (NLTK, com fallback seguro)
 - suporte multilíngue básico (pt/en)
 - geração de unigrams e bigrams relevantes
 - filtro de stopwords e tokens curtos
 - modo incremental (--incremental)
 - dry-run (--dry-run) e limite (--limit)
 - TF-IDF opcional (--tfidf) para ranquear termos mais informativos
 - tqdm progress bar e logs
"""

import re
import os
import sys
import json
import math
import logging
import argparse
from collections import Counter, defaultdict

from banco import inicializar_banco
from normalizacao import normalizar

# ---------------------------------------------------------------------
# Stemmer / Lemmatizer
# ---------------------------------------------------------------------
try:
    from nltk.stem import RSLPStemmer, SnowballStemmer
    from nltk.corpus import wordnet
    from nltk.stem import WordNetLemmatizer
    stem_pt = RSLPStemmer()
    stem_en = SnowballStemmer("english")
    lemmatizer = WordNetLemmatizer()

    def normalize_token(t: str) -> str:
        t = t.lower()
        if len(t) <= 2:
            return t
        # tenta lematizar e depois stemmar (PT + EN)
        try:
            if any(ord(c) > 127 for c in t):  # palavra pt
                return stem_pt.stem(t)
            lemma = lemmatizer.lemmatize(t)
            return stem_en.stem(lemma)
        except Exception:
            return t
except Exception:
    def normalize_token(t: str) -> str:
        return t.lower()

# ---------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------
TOKEN_RE = re.compile(r"[^\W\d_]+", flags=re.UNICODE)

STOPWORDS = {
    # português + inglês compactas
    "a","o","as","os","um","uma","uns","umas","de","do","da","dos","das",
    "em","no","na","nos","nas","por","para","com","sem","sobre","entre",
    "e","ou","que","quem","como","quando","onde","se","não","mais","menos",
    "já","ainda","são","ser","foi","era","eis","este","esta","isto","esse",
    "essa","isso","me","te","se","lhe","nos","vos","eles","elas","eu","tu",
    "ele","ela","nós","vós","the","a","an","in","on","for","of","and","or",
    "is","are","was","were","be","been","to","by","at","from","it","this",
    "that","as","if","then","but","so","with","can","will","would","could"
}

MAX_KEYWORDS = 20

# ---------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------
def tokenize(text: str):
    """Tokeniza e limpa o texto."""
    return [t.lower() for t in TOKEN_RE.findall(text or "")]

def generate_keywords(text: str, max_keywords=MAX_KEYWORDS, tfidf_scores=None):
    """Gera lista de keywords (stems + bigrams)."""
    text = normalizar(text or "")
    toks = [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]
    if not toks:
        return []

    stems = [normalize_token(t) for t in toks]
    unigrams = []
    seen = set()

    for s in stems:
        if s not in seen:
            seen.add(s)
            unigrams.append(s)

    bigrams = []
    for i in range(len(toks) - 1):
        b = f"{toks[i]} {toks[i+1]}"
        if b not in seen:
            bigrams.append(b)
            seen.add(b)

    kws = unigrams + bigrams

    # Se TF-IDF disponível, prioriza termos com maior peso
    if tfidf_scores:
        kws = sorted(kws, key=lambda k: tfidf_scores.get(k, 0), reverse=True)

    return kws[:max_keywords]

# ---------------------------------------------------------------------
# TF-IDF
# ---------------------------------------------------------------------
def compute_tfidf(all_docs):
    """Calcula TF-IDF simples para termos em todas as perguntas."""
    df = Counter()
    tf_list = []

    for tokens in all_docs:
        uniq = set(tokens)
        for w in uniq:
            df[w] += 1
        tf = Counter(tokens)
        tf_list.append(tf)

    N = len(all_docs)
    idf = {w: math.log((N + 1) / (df[w] + 1)) + 1 for w in df}

    tfidf_docs = []
    for tf in tf_list:
        scores = {w: tf[w] * idf.get(w, 0) for w in tf}
        tfidf_docs.append(scores)
    return tfidf_docs

# ---------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Gerador de keywords para perguntas.")
    parser.add_argument("--limit", type=int, default=None, help="Limita o número de perguntas processadas.")
    parser.add_argument("--dry-run", action="store_true", help="Não grava no banco, apenas mostra resumo.")
    parser.add_argument("--incremental", action="store_true", help="Atualiza apenas perguntas sem keywords.")
    parser.add_argument("--tfidf", action="store_true", help="Usa TF-IDF global para priorizar termos relevantes.")
    args = parser.parse_args()

    import time
    start = time.time()

    conn = inicializar_banco()
    if not conn:
        print("❌ Erro: não foi possível conectar ao banco.")
        return

    cur = conn.cursor(dictionary=True)
    query = "SELECT id, texto, texto_normalizado, keywords FROM perguntas"
    if args.incremental:
        query += " WHERE keywords IS NULL OR keywords = ''"
    if args.limit:
        query += f" LIMIT {args.limit}"
    cur.execute(query)
    rows = cur.fetchall()

    if not rows:
        print("Nenhuma pergunta encontrada para processar.")
        return

    print(f"🔍 Processando {len(rows)} perguntas...")

    # ---------------------------------------------------------------
    # Se TF-IDF habilitado, primeiro tokeniza tudo
    # ---------------------------------------------------------------
    all_docs_tokens = [tokenize(normalizar(r["texto"] or r["texto_normalizado"] or "")) for r in rows]
    tfidf_docs = compute_tfidf(all_docs_tokens) if args.tfidf else [None] * len(rows)

    from tqdm import tqdm
    updated = 0
    for i, r in enumerate(tqdm(rows, desc="Gerando keywords", unit="q")):
        pid = r["id"]
        texto = r["texto"] or r["texto_normalizado"] or ""
        tfidf_scores = tfidf_docs[i] if args.tfidf else None
        kws = generate_keywords(texto, tfidf_scores=tfidf_scores)
        if not kws:
            continue
        kws_json = json.dumps(kws, ensure_ascii=False)
        if not args.dry_run:
            try:
                cur.execute("UPDATE perguntas SET keywords = %s WHERE id = %s", (kws_json, pid))
                updated += 1
            except Exception as e:
                print(f"⚠️ Erro ao atualizar id={pid}: {e}")

    if not args.dry_run:
        conn.commit()

    cur.close()
    conn.close()

    elapsed = time.time() - start
    print(f"✅ Keywords geradas para {updated} perguntas em {elapsed:.2f}s")
    if args.dry_run:
        print("⚠️ Dry-run: nenhuma alteração gravada no banco.")

# ---------------------------------------------------------------------
if __name__ == "__main__":
    main()
