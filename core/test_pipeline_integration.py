# core/test_search_pool.py
import banco
from gerenciador_respostas import buscar_resposta_usuario

conn = banco.inicializar_banco()
perguntas = ["Einstein", "como alterar senha", "fotossíntese", "minecraft", "cat tower", "Dumont", "Roblox", "Maior osso do corpo humano"]
for q in perguntas:
    res = buscar_resposta_usuario(q, conn, debug_candidates=True)
    print("Q:", q, "->", res)
conn.close()
