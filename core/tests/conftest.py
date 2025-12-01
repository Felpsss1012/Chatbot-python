# core/tests/test_pipeline.py (adição obrigatória no topo)
import os
import sys

# calcula a raiz do projeto a partir da pasta core/tests
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# insere a raiz na frente do sys.path para garantir imports locais
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# agora o import deve encontrar 'tools' que está na raiz do projeto
from core.pipeline_search import find_answer, numbers_to_words_in_text, user_requests_only_field


# Calcula a raiz do projeto a partir da localização deste arquivo (core/tests)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

if ROOT not in sys.path:
    # Insere a raiz na frente para priorizar imports locais
    sys.path.insert(0, ROOT)
