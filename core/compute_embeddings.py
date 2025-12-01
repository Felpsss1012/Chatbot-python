# compute_embeddings.py
import argparse
from banco import inicializar_banco
from embeddings import atualizar_embeddings

def main():
    p = argparse.ArgumentParser(description="Compute embeddings for perguntas/respostas")
    p.add_argument("--tabela", choices=["perguntas", "respostas"], default="perguntas")
    p.add_argument("--batch", type=int, default=64, help="batch size para encoding")
    p.add_argument("--throttle", type=float, default=0.0, help="seconds to sleep between batches")
    args = p.parse_args()

    conn = inicializar_banco()
    try:
        atualizar_embeddings(conn, tabela=args.tabela, batch_size=args.batch, throttle_sec=args.throttle)
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
