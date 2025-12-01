# core/config.py
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")

# caminhos padrão de arquivos
MEUS_QNA_CSV = os.path.join(DATA_DIR, "meus_qna.csv")
PALAVRAS_PROIBIDAS = os.path.join(DATA_DIR, "palavras_proibidas.json")
BANCO_SQL = os.path.join(DATA_DIR, "banco.sql")

# garantir diretórios existirem em runtime
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
