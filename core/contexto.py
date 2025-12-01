# core/contexto.py
from __future__ import annotations

import json
import threading
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import List, Dict, Callable, Tuple, Optional, Any

from difflib import SequenceMatcher

# imports opcionais pesados (numpy) carregados dinamicamente para evitar erro se não instalado
try:
    import numpy as _np  # type: ignore
except Exception:
    _np = None  # fallback - algumas operações usarão text-similarity

from config import LOG_DIR

logger = logging.getLogger(__name__)
# garante diretório de logs
try:
    import os as _os
    _os.makedirs(LOG_DIR, exist_ok=True)
except Exception:
    pass


def _default_embedding_func_try_load():
    """
    Tenta carregar core.embeddings.calcular_embedding dinamicamente.
    Retorna None se não for possível.
    """
    try:
        from core.embeddings import calcular_embedding  # type: ignore
        return calcular_embedding
    except Exception:
        logger.debug("core.embeddings.calcular_embedding não disponível; contexto sem embeddings.")
        return None


def _cosine_similarity_vec(a: Any, b: Any) -> float:
    """
    Similaridade de cosseno robusta. Aceita numpy arrays, listas, etc.
    Se numpy não estiver disponível, tenta fallback com SequenceMatcher sobre strings (menos preciso).
    """
    if _np is not None:
        try:
            v1 = _np.array(a, dtype=float)
            v2 = _np.array(b, dtype=float)
            n1 = _np.linalg.norm(v1)
            n2 = _np.linalg.norm(v2)
            if n1 == 0 or n2 == 0:
                return 0.0
            return float(_np.dot(v1, v2) / (n1 * n2))
        except Exception as e:
            logger.debug("Erro em cosine np: %s", e)
            return 0.0
    # fallback string similarity
    try:
        s1 = str(a)
        s2 = str(b)
        return SequenceMatcher(None, s1, s2).ratio()
    except Exception:
        return 0.0


class GerenciadorContexto:
    """
    Mantém histórico recente de (usuario, bot) em memória com embeddings opcionais.

    Uso:
        - gc = GerenciadorContexto(tamanho_maximo=6, timeout_minutos=10, embedding_func=minha_func)
        - gc.adicionar_mensagem("Oi", autor="usuario")
        - flag, score, msg = gc.mensagem_repetida("Oi de novo")
        - contexto_texto = gc.obter_contexto()
    """

    def __init__(
        self,
        tamanho_maximo: int = 5,
        timeout_minutos: int = 10,
        embedding_func: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._lock = threading.Lock()
        self.historico: deque[Dict[str, Any]] = deque(maxlen=max(1, int(tamanho_maximo)))
        self.embeddings: deque[Any] = deque(maxlen=max(1, int(tamanho_maximo)))
        self.timeout: timedelta = timedelta(minutes=max(0, int(timeout_minutos)))
        # se não foi passada, tentamos carregar lazy
        if embedding_func is None:
            embedding_func = _default_embedding_func_try_load()
        self.embedding_func = embedding_func
        self.ultima_interacao: Optional[datetime] = None

    # -------------------
    # Adição / limpeza
    # -------------------
    def adicionar_mensagem(self, texto: str, autor: str = "usuário", embedding: Any | None = None) -> None:
        """
        Adiciona uma nova mensagem ao histórico. Calcula embedding se função fornecida.
        Thread-safe.
        """
        if texto is None:
            return
        texto = str(texto).strip()
        if not texto:
            return

        agora = datetime.now()

        with self._lock:
            # limpar contexto se timeout expirou
            if self.ultima_interacao and (agora - self.ultima_interacao) > self.timeout:
                self.limpar_contexto()

            emb_obj = None
            if embedding is not None:
                emb_obj = embedding
            else:
                if callable(self.embedding_func):
                    try:
                        emb_raw = self.embedding_func(texto)
                        emb_obj = (_np.array(emb_raw, dtype=float) if (_np is not None and emb_raw is not None) else emb_raw)
                    except Exception as e:
                        logger.debug("Falha ao gerar embedding para contexto: %s", e)
                        emb_obj = None

            self.historico.append({"texto": texto, "timestamp": agora, "autor": autor})
            self.embeddings.append(emb_obj)
            self.ultima_interacao = agora

            logger.debug("Contexto adicionado: %s (autor=%s)", texto[:120], autor)

    def limpar_contexto(self) -> None:
        with self._lock:
            self.historico.clear()
            self.embeddings.clear()
            self.ultima_interacao = None
            logger.debug("Contexto limpo por timeout/ação manual.")

    # -------------------
    # Query / repetição
    # -------------------
    def mensagem_repetida(
        self,
        texto: str,
        thresh_embed: float = 0.85,
        thresh_texto: float = 0.9,
        k: int = 3,
    ) -> Tuple[bool, float, Optional[Dict[str, Any]]]:
        """
        Verifica se 'texto' repete/continua uma das últimas 'k' mensagens.
        Retorna (flag_repetida, melhor_score, mensagem_encontrada_ou_None).

        Estratégia:
            - tenta calcular embedding para o texto (se embedding_func disponível).
            - compara com embeddigns recentes por cosine (se existirem embeddings).
            - caso contrário usa SequenceMatcher para semelhante textual.
        """
        if texto is None:
            return False, 0.0, None
        texto = str(texto)

        # prepara vetor novo (se possível)
        vetor_novo = None
        if callable(self.embedding_func):
            try:
                emb_raw = self.embedding_func(texto)
                vetor_novo = (_np.array(emb_raw, dtype=float) if (_np is not None and emb_raw is not None) else emb_raw)
            except Exception as e:
                logger.debug("Falha ao calcular embedding p/ mensagem_repetida: %s", e)
                vetor_novo = None

        with self._lock:
            historico_recent = list(self.historico)[-k:] if k > 0 else list(self.historico)
            emb_recent = list(self.embeddings)[-k:] if k > 0 else list(self.embeddings)

        melhor_sim = 0.0
        melhor_msg = None

        # iterar reverso: compara com as mensagens mais recentes primeiro
        for msg, emb in zip(reversed(historico_recent), reversed(emb_recent)):
            try:
                if vetor_novo is not None and emb is not None:
                    sim = _cosine_similarity_vec(vetor_novo, emb)
                else:
                    sim = SequenceMatcher(None, texto, msg.get("texto", "")).ratio()
            except Exception:
                sim = 0.0
            if sim > melhor_sim:
                melhor_sim = sim
                melhor_msg = msg

        # decidir qual threshold usar
        if (vetor_novo is not None) and any(e is not None for e in emb_recent):
            flag = melhor_sim >= float(thresh_embed)
        else:
            flag = melhor_sim >= float(thresh_texto)

        return bool(flag), float(melhor_sim), (melhor_msg if melhor_msg is not None else None)

    # -------------------
    # utilitários de acesso
    # -------------------
    def obter_contexto(self) -> str:
        """Retorna o histórico formatado (autor: texto), do mais antigo ao mais recente."""
        with self._lock:
            return "\n".join(f"{m['autor']}: {m['texto']}" for m in self.historico).strip()

    def obter_ultimas_mensagens(self, n: int) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.historico)[-max(0, int(n)):] if n > 0 else []

    def exportar_historico(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.historico)

    def obter_mensagem(self, indice: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            try:
                return list(self.historico)[int(indice)]
            except Exception:
                return None

    def obter_mensagem_por_autor(self, autor: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [m for m in self.historico if m.get("autor") == autor]

    def obter_mensagem_por_data(self, data: datetime) -> List[Dict[str, Any]]:
        with self._lock:
            return [m for m in self.historico if m.get("timestamp") and m["timestamp"].date() == data.date()]

    def obter_ultima_mensagem(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.historico[-1] if self.historico else None

    # -------------------
    # persistência simples (JSON)
    # -------------------
    def salvar_em_arquivo(self, nome_arquivo: Optional[str] = None) -> str:
        """
        Salva o histórico atual em JSON no LOG_DIR. Retorna o caminho do arquivo salvo.
        """
        nome = nome_arquivo or f"contexto_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        caminho = _os.path.join(LOG_DIR, nome)
        payload = {"exported_at": datetime.utcnow().isoformat() + "Z", "historico": self.exportar_historico()}
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            logger.info("Contexto salvo em %s", caminho)
            return caminho
        except Exception as e:
            logger.error("Erro ao salvar contexto em arquivo: %s", e)
            raise

    def carregar_de_arquivo(self, caminho_arquivo: str) -> int:
        """
        Carrega histórico a partir de arquivo JSON (substitui o estado atual).
        Retorna número de mensagens carregadas.
        """
        try:
            with open(caminho_arquivo, "r", encoding="utf-8") as f:
                data = json.load(f)
            historico = data.get("historico") if isinstance(data, dict) else None
            if not isinstance(historico, list):
                return 0
            with self._lock:
                self.historico.clear()
                self.embeddings.clear()
                for item in historico:
                    txt = item.get("texto") or ""
                    autor = item.get("autor") or "usuario"
                    ts = item.get("timestamp")
                    try:
                        ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else None
                    except Exception:
                        ts_dt = None
                    # embedding não é carregado (preserva None) — pode ser recomputado quando necessário
                    self.historico.append({"texto": txt, "timestamp": ts_dt or datetime.now(), "autor": autor})
                    self.embeddings.append(None)
                self.ultima_interacao = datetime.now()
            logger.info("Contexto carregado de %s (%d itens)", caminho_arquivo, len(historico))
            return len(historico)
        except Exception as e:
            logger.error("Falha ao carregar contexto de arquivo %s: %s", caminho_arquivo, e)
            return 0
