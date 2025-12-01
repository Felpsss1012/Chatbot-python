# 🧠 Manual de Atualização da Base de Conhecimento — Assistente Inteligente

Este guia explica **como adicionar novas perguntas e respostas** ao assistente, garantindo que tudo fique sincronizado com o banco de dados, embeddings e keywords para melhorar a busca semântica.

---

## 🚀 Etapas gerais do processo

Sempre que quiser **adicionar, remover ou atualizar informações**, siga a ordem abaixo:

| Etapa | Descrição | Script |
|-------|------------|---------|
| 1️⃣ | Editar o CSV com novas perguntas e respostas | `data/meus_qna.csv` |
| 2️⃣ | Importar o CSV para o banco | `python core/seed_qna.py` |
| 3️⃣ | Gerar/atualizar embeddings das perguntas | `python core/compute_embeddings.py` |
| 4️⃣ | Gerar keywords (para buscas híbridas) | `python core/keywords_seed.py` |
| 5️⃣ | Testar e validar as respostas | `python core/debug_query.py "sua pergunta"` |

---

## 📝 1️⃣ Editar o CSV (`data/meus_qna.csv`)

O arquivo CSV é o **ponto central** onde ficam armazenadas as perguntas e respostas que alimentarão o chatbot.

### 📄 Estrutura esperada
```csv
pergunta,resposta
Como alterar minha senha?,"Para alterar sua senha, vá em Configurações → Conta → Segurança e siga as instruções."
Qual é o maior osso do corpo humano?,"O maior osso do corpo humano é o fêmur."
O que é fotossíntese?,"A fotossíntese é o processo em que as plantas produzem energia a partir da luz solar."
