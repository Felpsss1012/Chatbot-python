# tune_grid.py
import csv, os, itertools
from banco import inicializar_banco
from gerenciador_respostas import obter_top_k_respostas
from normalizacao import normalizar as normalizar_texto

# localizar csv como fizemos em avaliar.py (se preferir edite caminho absoluto)
def localizar_csv(nome="meus_qna.csv"):
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, nome),
        os.path.join(here, "..", nome),
        os.path.join(os.getcwd(), "Data", nome),
    ]
    for p in candidates:
        if os.path.exists(os.path.normpath(p)):
            return os.path.normpath(p)
    raise FileNotFoundError(f"'{nome}' não encontrado. Procurei em:\n" + "\n".join(candidates))

CSV_PATH = localizar_csv("meus_qna.csv")
N = 200  # número de amostras (mude para 500 para avaliar tudo)

def normalize(s):
    if not s: return ""
    try:
        return normalizar_texto(s).strip().lower()
    except Exception:
        return s.strip().lower()

def avaliar_com_parametros(weight_embedding, weight_keywords, limite_similaridade):
    conn = inicializar_banco()
    total = 0; top1 = 0; top3 = 0
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= N: break
            pergunta = row.get("pergunta") or row.get("question") or row.get("q") or row.get("texto") or ""
            resposta_esperada = row.get("resposta") or row.get("answer") or row.get("a") or row.get("resposta_texto") or ""
            if not pergunta or not resposta_esperada:
                continue
            total += 1
            topk = obter_top_k_respostas(pergunta, conn, k=3, weight_embedding=weight_embedding, weight_keywords=weight_keywords)
            topk_norm = [normalize(x) for x in topk]
            esperado_norm = normalize(resposta_esperada)
            if topk_norm:
                if topk_norm[0] == esperado_norm:
                    top1 += 1
                if esperado_norm in topk_norm:
                    top3 += 1
    conn.close()
    if total == 0: return 0.0, 0.0
    return top1/total, top3/total

def main():
    # grade de parâmetros (ajuste se quiser)
    weights = [0.5, 0.6, 0.7, 0.8]  # weight_embedding
    limites = [0.65, 0.70, 0.72, 0.75]  # limite_similaridade
    resultados = []
    for w in weights:
        for lim in limites:
            wk = 1.0 - w
            print(f"Testando weight_embedding={w:.2f}, weight_keywords={wk:.2f}, limite={lim:.2f}")
            p1, p3 = avaliar_com_parametros(w, wk, lim)
            print(f"  -> precisão@1={p1:.4f}, precisão@3={p3:.4f}")
            resultados.append((w, wk, lim, p1, p3))
    # ordenar por precisão@1 desc, depois p3
    resultados.sort(key=lambda t: (t[3], t[4]), reverse=True)
    print("\nMelhores combinações (top 5):")
    for r in resultados[:5]:
        print(f"weight_emb={r[0]:.2f}, weight_kw={r[1]:.2f}, lim={r[2]:.2f} => p@1={r[3]:.4f}, p@3={r[4]:.4f}")

if __name__ == "__main__":
    main()
