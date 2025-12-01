# 🧠 keywords_seed.py — Gerador Inteligente de Keywords

Este script gera **keywords otimizadas (stems + bigrams + TF-IDF)** para cada pergunta registrada no banco de dados.  
Ele atualiza o campo `perguntas.keywords` em lote, com suporte a **modo incremental, TF-IDF, lematização, dry-run e barra de progresso**.

---

## 🚀 Recursos Principais

✅ Geração automática de **keywords** para todas as perguntas  
✅ Suporte a **Português e Inglês**  
✅ **Stemming + lematização** (usa NLTK se disponível)  
✅ **Unigrams e bigrams relevantes**  
✅ **TF-IDF opcional** para priorizar termos mais informativos  
✅ **Modo incremental** — só atualiza perguntas sem keywords  
✅ **Dry-run** (simulação sem gravar no banco)  
✅ **Limite de processamento** (`--limit`)  
✅ **Barra de progresso** com `tqdm`  
✅ Fallback seguro se o NLTK não estiver instalado

---

## ⚙️ Requisitos

- Python 3.8+
- Bibliotecas:
  ```bash
  pip install mysql-connector-python tqdm nltk
