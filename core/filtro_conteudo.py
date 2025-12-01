# core/filtro_conteudo.py
from __future__ import annotations

import os
import json
import re
import logging
from typing import Set

from config import DATA_DIR

logger = logging.getLogger(__name__)

# caminho padrão do arquivo de palavras proibidas
_ARQUIVO_PALAVRAS_PROIBIDAS = os.path.join(DATA_DIR, "palavras_proibidas.json")

# Carregamento preguiçoso das palavras proibidas (permite atualizar em runtime)
def carregar_palavras_proibidas(path: str | None = None) -> Set[str]:
    caminho = path or _ARQUIVO_PALAVRAS_PROIBIDAS
    if not caminho or not os.path.exists(caminho):
        logger.debug("Arquivo palavras proibidas não encontrado: %s", caminho)
        return set()
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(x.strip().lower() for x in data if isinstance(x, str) and x.strip())
        logger.warning("palavras_proibidas.json não é lista; ignorando.")
        return set()
    except Exception as e:
        logger.exception("Falha ao carregar palavras proibidas: %s", e)
        return set()

# cache simples
PALAVRAS_PROIBIDAS = carregar_palavras_proibidas()

# --- tradução (opcional) ---
# Tentamos usar googletrans se instalado; se não, a função traduzir retorna o texto original.
try:
    from googletrans import Translator  # type: ignore
    _translator = Translator()
except Exception:
    _translator = None
    logger.debug("googletrans não disponível; tradução desativada.")

def traduzir_para_pt_func(texto: str) -> str:
    """
    Detecta e traduz (se english detected) usando googletrans quando disponível.
    Em falha, retorna o texto original.
    """
    if not texto:
        return texto
    if _translator is None:
        return texto
    try:
        det = _translator.detect(texto)
        if hasattr(det, "lang") and det.lang and det.lang.startswith("en"):
            translated = _translator.translate(texto, src="en", dest="pt").text
            logger.debug("Texto detectado em inglês e traduzido.")
            return translated
    except Exception as e:
        logger.debug("Falha tradução (continuando sem traduzir): %s", e)
    return texto

# --- sumarização (opcional, usa sumy se disponível) ---
try:
    from sumy.parsers.plaintext import PlaintextParser  # type: ignore
    from sumy.nlp.tokenizers import Tokenizer  # type: ignore
    from sumy.summarizers.lex_rank import LexRankSummarizer  # type: ignore
    _HAS_SUMY = True
except Exception:
    _HAS_SUMY = False
    logger.debug("sumy não disponível; resumir_texto usará fallback simples.")

def resumir_texto(texto: str, sentencas: int = 2) -> str:
    """
    Tenta resumir com sumy; em falta usa truncamento por sentenças.
    """
    if not texto:
        return texto
    if _HAS_SUMY:
        try:
            parser = PlaintextParser.from_string(texto, Tokenizer("portuguese"))
            summarizer = LexRankSummarizer()
            resumo = summarizer(parser.document, sentencas)
            return " ".join(str(s) for s in resumo)
        except Exception as e:
            logger.debug("sumy falhou em resumir, fallback: %s", e)
    # Fallback: pegar as primeiras N sentenças básicas
    sentences = re.split(r'(?<=[.!?])\s+', texto.strip())
    return " ".join(sentences[:sentencas]).strip()

def contem_conteudo_inadequado(texto: str, palavras_proibidas: set | None = None) -> bool:
    """
    Retorna True se qualquer palavra proibida for encontrada no texto (word-boundary).
    Usa regex seguro (re.escape) e comparação case-insensitive.
    """
    if not texto:
        return False
    voc = palavras_proibidas if palavras_proibidas is not None else PALAVRAS_PROIBIDAS
    if not voc:
        return False
    texto_lower = texto.lower()
    for palavra in voc:
        if not palavra:
            continue
        # busca por palavra inteira
        if re.search(rf"\b{re.escape(palavra)}\b", texto_lower, flags=re.UNICODE):
            logger.info("Conteúdo bloqueado pela palavra proibida: %s", palavra)
            return True
    return False

def processar_texto(texto: str, max_len: int = 500, sentencas_resumo: int = 2) -> str:
    """
    Limpa espaços, checa palavras proibidas e resume se maior que max_len.
    Retorna texto "limpo" apropriado para exibir.
    """
    if texto is None:
        return ""
    txt = re.sub(r"\s+", " ", texto).strip()
    if contem_conteudo_inadequado(txt):
        return "Desculpe, não posso exibir esse conteúdo."
    if len(txt) > max_len:
        try:
            resumo = resumir_texto(txt, sentencas=sentencas_resumo)
            return resumo
        except Exception:
            # fallback truncado
            return txt[:max_len].rsplit(" ", 1)[0] + "..."
    return txt

def poluir_texto(texto: str) -> str:
    """Hook para possíveis transformações leves; por enquanto retorna igual."""
    return texto
