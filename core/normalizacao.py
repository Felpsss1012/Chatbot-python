from __future__ import annotations

import re
import unicodedata
import logging
from typing import Optional

logger = logging.getLogger("normalizacao")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


def normalizar(texto: Optional[str]) -> str:
    """Normaliza texto para buscas/índices.
    - lowercasing
    - remoção de acentos (NFD)
    - remoção de pontuação (mantém dígitos e underscores)
    - compactação de espaços
    Retorna string vazia para entradas None/sempre string.
    """
    if texto is None:
        return ""
    s = str(texto)
    s = s.strip().lower()

    # decompor acentos e remover marcas
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

    # substituir quebras por espaço
    s = re.sub(r"[\r\n\t]+", " ", s)

    # remover pontuação mas preservar underscores/dígitos/letras
    s = re.sub(r"[^\w\s]", "", s)

    # compactar espaços
    s = re.sub(r"\s+", " ", s).strip()

    return s


def atualizar_texto_normalizado(conn) -> None:
    """Atualiza colunas texto_normalizado nas tabelas perguntas e respostas."""
    if conn is None:
        logger.warning("atualizar_texto_normalizado: conexão nula informada")
        return

    cur = conn.cursor()
    try:
        cur.execute("SELECT id, texto FROM perguntas WHERE texto_normalizado IS NULL OR texto_normalizado = ''")
        perguntas = cur.fetchall() or []
        for pergunta_id, texto in perguntas:
            t = normalizar(texto)
            cur.execute(
                "UPDATE perguntas SET texto_normalizado = %s WHERE id = %s",
                (t, pergunta_id)
            )

        cur.execute("SELECT id, texto FROM respostas WHERE texto_normalizado IS NULL OR texto_normalizado = ''")
        respostas = cur.fetchall() or []
        for resposta_id, texto in respostas:
            t = normalizar(texto)
            cur.execute(
                "UPDATE respostas SET texto_normalizado = %s WHERE id = %s",
                (t, resposta_id)
            )

        conn.commit()
        logger.info(
            "✅ %d entradas normalizadas (%d perguntas, %d respostas).",
            len(perguntas) + len(respostas), len(perguntas), len(respostas)
        )
    except Exception as e:
        logger.exception("Falha ao atualizar texto_normalizado: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            cur.close()
        except Exception:
            pass


def humanize_text(raw_text: Optional[str], source_meta: Optional[dict] = None, for_tts: bool = True) -> str:
    """Limpa e humaniza texto em PT-BR.

    - normaliza espaços
    - pontuação final garantida
    - capitalização
    - conversão de números para extenso quando for_tts=True
    - tratamento de listas/bullets
    - nota de fonte opcional
    """
    if not raw_text and raw_text != 0:
        return ""

    text = str(raw_text)

    # normalizar finais de linha
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")

    # separar parágrafos
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    processed = []
    for p in paragraphs:
        p = re.sub(r"\s+", " ", p).strip()
        p = re.sub(r"\s+([,.!?;:])", r"\1", p)

        if not re.search(r"[.!?…]$", p):
            p += "."

        # capitalizar
        if p:
            p = p[0].upper() + p[1:]

        # detectar bullets
        lines = [l.strip() for l in p.splitlines() if l.strip()]
        bullets = [l for l in lines if re.match(r"^[-•\*]\s+", l)]
        if bullets:
            items = [re.sub(r"^[-•\*]\s*", "", l).rstrip(".") for l in bullets]
            if len(items) == 1:
                p = items[0] + "."
            elif len(items) <= 3:
                p = ", ".join(items[:-1]) + " e " + items[-1] + "."
            else:
                p = "Principais pontos: " + "; ".join(items) + "."

        # converter números → extenso (opcional)
        if for_tts:
            try:
                from num2words import num2words

                def repl(m):
                    t = m.group(0)
                    clean = t.replace(".", "").replace(",", "")
                    try:
                        n = int(clean)
                        try:
                            return num2words(n, lang="pt_BR")
                        except Exception:
                            return num2words(n, lang="pt")
                    except Exception:
                        return t

                p = re.sub(r"\d[\d.,]*", repl, p)
            except Exception:
                pass

        processed.append(p)

    final = "\n\n".join(processed).strip()

    # nota de fonte opcional
    try:
        if source_meta and isinstance(source_meta, dict):
            src = source_meta.get("source")
            sid = source_meta.get("resposta_id") or source_meta.get("pergunta_id") or source_meta.get("id")
            if src and sid:
                final += f"\n\nFonte: #{sid} ({src})"
    except Exception:
        pass

    final = re.sub(r"\s+", " ", final).strip()
    return final
