# debug_pipeline.py
"""
Script de debug para pipeline_search.
Execute da raiz do projeto com o venv ativado:
    python debug_pipeline.py
"""
import os
import sys
from pprint import pprint

# --- garantir que a raiz do projeto está no sys.path ---
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# --- import do pipeline (ajusta-se à sua estrutura de pastas) ---
# se o seu pipeline estiver em tools/pipeline_search.py (raiz/tools), use:
try:
    from core.pipeline_search import find_answer, DEFAULT_CSV
except Exception:
    # fallback: se você mantiver o módulo em core/tools, tente esse import
    try:
        from core.pipeline_search import find_answer, DEFAULT_CSV
    except Exception as e:
        print("Erro ao importar pipeline_search:", e)
        raise

# --- opcional: caminho absoluto para seu CSV (modifique se precisar) ---
# Por padrão o script usa DEFAULT_CSV do módulo pipeline_search.
# Se você quiser usar um caminho específico, altere abaixo:
custom_csv = r"C:\Users\felip\Downloads\TCC\Assistente\data\meus_qna.csv"  # <--- ajuste aqui se necessário

# escolhe CSV disponível
csv_path = custom_csv if os.path.exists(custom_csv) else DEFAULT_CSV
print("Usando CSV:", csv_path, "| existe?", os.path.exists(csv_path))

# queries de exemplo
queries = [
    "me diga só a data"
]

# executa buscas
for q in queries:
    try:
        print("Q:", q)
        # use_db=True para tentar MySQL (vai chamar banco.inicializar_banco() internamente)
        res = find_answer(q, use_db=True, csv_path=csv_path)
        print("=>", res.get("text"))
        print("META:")
        pprint(res.get("explain", res.get("meta", {})))
    except Exception as ex:
        print("Erro ao processar consulta:", ex)
    print("-----")
