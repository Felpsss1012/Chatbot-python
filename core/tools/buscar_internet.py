# buscar_internet.py
import asyncio
import wikipedia
import json
from datetime import datetime
from normalizacao import normalizar
from filtro_conteudo import resumir_texto, processar_texto
# calcular_embedding será passado pela chamada (evita import direto pesado)

# configurar wikipedia
wikipedia.set_lang("pt")

async def buscar_wikipedia(pergunta: str, max_sentences: int = 2):
    """
    Busca Wikipedia: faz search -> pega primeira página relevante -> resumo curto (max_sentences)
    Retorna tupla (fonte, texto_curto) ou None.
    """
    try:
        # busca páginas
        results = await asyncio.to_thread(wikipedia.search, pergunta, results=3)
        if not results:
            return None
        # escolher primeiro resultado e pegar resumo/primeiro parágrafo
        page_title = results[0]
        try:
            page = await asyncio.to_thread(wikipedia.page, page_title, auto_suggest=False)
        except Exception:
            # tentar sem auto_suggest
            try:
                page = await asyncio.to_thread(wikipedia.page, page_title)
            except Exception:
                page = None
        if not page:
            return None
        # obter resumo com limite de sentenças
        resumo = await asyncio.to_thread(wikipedia.summary, page_title, sentences=max_sentences)
        if not resumo:
            # fallback para conteúdo da página
            content = getattr(page, "content", "")
            resumo = (content.split("\n\n", 1)[0] if content else None)
        if not resumo:
            return None
        # limpeza básica
        texto_limpo = processar_texto(resumo) if callable(processar_texto) else resumo
        texto_curto = resumir_texto(texto_limpo, max_sentences=max_sentences) if callable(resumir_texto) else texto_limpo
        return ("Wikipedia", texto_curto)
    except Exception:
        return None


def processar_busca_internet(
    pergunta: str,
    conn,
    aprender_resposta_func=None,
    normalizar_func=None,
    calcular_embedding_func=None,
    remover_pergunta_log_func=None,
    poluir_func=None,
    traduzir_para_pt_func=None,
    interativo: bool = False,
):
    """
    Pipeline simplificada: usa apenas Wikipedia para gerar proposta de resposta.
    -> Se encontra texto, grava em tabela pendencias_revisao (aprovado = FALSE).
    Não realiza inserção automática em produção sem revisão humana.
    """
    try:
        resultado = asyncio.run(buscar_wikipedia(pergunta))
    except Exception as e:
        resultado = None

    if not resultado:
        # nada encontrado
        if aprender_resposta_func:
            try:
                aprender_resposta_func(pergunta, conn)
            except Exception:
                pass
        return

    fonte, texto = resultado
    if not texto:
        if aprender_resposta_func:
            try:
                aprender_resposta_func(pergunta, conn)
            except Exception:
                pass
        return

    # normalizar e calcular embedding se querermos armazenar meta
    texto_norm = None
    emb = None
    try:
        if normalizar_func:
            texto_norm = normalizar_func(texto)
        if calcular_embedding_func:
            try:
                emb = calcular_embedding_func(texto_norm or texto)
            except Exception:
                emb = None
    except Exception:
        texto_norm = None
        emb = None

    # gravar como pendência para revisão
    try:
        cur = conn.cursor()
        sql = "INSERT INTO pendencias_revisao (pergunta_texto, resposta_texto, fonte, aprovado, meta) VALUES (%s, %s, %s, %s, %s)"
        meta = {"normalizado": texto_norm, "embedding_present": bool(emb)}
        cur.execute(sql, (pergunta, texto, "wikipedia", False, json.dumps(meta, ensure_ascii=False)))
        try:
            conn.commit()
        except Exception:
            pass
        try:
            cur.close()
        except Exception:
            pass
    except Exception:
        # se falhar no DB, não interrompe: registra em arquivo de não-respondidas
        try:
            from log_nao_respondidas import registrar_nao_respondida
            registrar_nao_respondida(pergunta)
        except Exception:
            pass

    # quando interativo, perguntar se quer aprovar direto (útil em execução manual)
    if interativo:
        try:
            print(f"Proposta (Wikipedia):\n{texto}\n")
            ans = input("Aprovar e inserir como resposta imediata? (s/n): ").strip().lower()
            if ans == "s":
                if aprender_resposta_func:
                    try:
                        aprender_resposta_func(pergunta, conn, texto)
                    except Exception:
                        pass
        except Exception:
            pass
