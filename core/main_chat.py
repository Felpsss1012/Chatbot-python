# core/main_chat.py
from __future__ import annotations

import io
import os
import re
import sys
import time
import json
import logging
import tempfile
import pygame
from TTS.api import TTS
import random
from pydub import AudioSegment
import socket
import threading
from datetime import datetime, timedelta
# imports do package (ajustados para executar como "python -m core.main_chat")
from config import LOG_DIR, ROOT
from banco import (
    inicializar_banco, adicionar_memoria, listar_memorias,
    remover_memoria_por_id, editar_memoria, gerar_alertas
)
from gerenciador_memoria import (
    adicionar_memoria_interativa, listar_memorias_interativa,
    remover_memoria_interativa, editar_memoria_interativa
)
from filtro_conteudo import (
    contem_conteudo_inadequado,
    resumir_texto,
    processar_texto,
    poluir_texto,
    traduzir_para_pt_func,
)
from gerenciador_respostas import buscar_resposta_usuario
from normalizacao import normalizar, atualizar_texto_normalizado
from embeddings import calcular_embedding, atualizar_embeddings
from tools.buscar_internet import processar_busca_internet
from contexto import GerenciadorContexto

# tenta importar schedule, caso não exista usa fallback simples
try:
    import schedule  # type: ignore
except Exception:
    class _MiniSchedule:
        def __init__(self):
            self._jobs = []
        def every(self, seconds: int):
            job = {"interval": seconds, "next": time.time() + seconds, "fn": None}
            self._jobs.append(job)
            class _Do:
                def __init__(self, job):
                    self.job = job
                def do(self, fn):
                    self.job["fn"] = fn
            return _Do(job)
        def run_pending(self):
            now = time.time()
            for job in self._jobs:
                if job["fn"] and now >= job["next"]:
                    try:
                        job["fn"]()
                    finally:
                        job["next"] = now + job["interval"]
    schedule = _MiniSchedule()

# Configs (permitir override por env var)
ENABLE_TTS = os.getenv("ENABLE_TTS", "1") == "1"
# AUDIO_DIR usa ROOT do config como base se não fornecido
AUDIO_DIR = os.getenv("AUDIO_DIR", os.path.join(ROOT, "audio"))
ALERTA_JANELA_DIAS = int(os.getenv("ALERTA_JANELA_DIAS", "14"))
ENRIQUECIMENTO_INTERVALO_MIN = int(os.getenv("ENRIQUECIMENTO_INTERVALO_MIN", "30"))
ALERTAS_VERIFICAR_CADA_MIN = int(os.getenv("ALERTAS_VERIFICAR_CADA_MIN", "5"))

# garante diretórios
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# logging
logging.getLogger().handlers.clear()
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "chat.log"),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(author)s - %(message)s'
)
class _AuthorDefault(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "author"):
            record.author = "system"
        return True
root = logging.getLogger()
for h in root.handlers:
    h.addFilter(_AuthorDefault())
logger = logging.getLogger(__name__)


class Speaker:
    """
    Classe de síntese de fala usando Coqui XTTS-v2 com voz personalizada
    ou amostra padrão. Agora 100% integrada ao seu projeto.
    """

    def __init__(self, enabled=True, audio_dir=None):
        # aceita parâmetro enabled e audio_dir para compatibilidade com a chamada externa
        self.enabled = bool(enabled)
        self.ok = False
        # garante que audio_dir exista e esteja acessível externamente
        self.audio_dir = audio_dir or os.getenv("AUDIO_DIR", os.path.join(ROOT, "audio"))
        try:
            if not self.enabled:
                print("🔕 TTS desativado via configuração (enabled=False).")
                self.ok = False
                # não tenta carregar nada se TTS desabilitado
                return

            print("\n🔊 Carregando modelo XTTS-v2...")

            # 1 — Carrega modelo XTTS-v2 via API
            self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
            # alias para compatibilidade com código que espera speaker._tts
            self._tts = self.tts

            # 2 — Caminho do WAV da voz de referência (clonagem)
            self.speaker_wav = os.getenv(
                "TTS_SPEAKER_WAV",
                r"C:\Users\felip\Downloads\TCC\Assistente\Referencia.wav"  # <- ajuste se desejar
            )

            if not os.path.exists(self.speaker_wav):
                raise FileNotFoundError(f"Arquivo de voz não encontrado: {self.speaker_wav}")

            # 3 — Idioma
            self.language = os.getenv("TTS_LANGUAGE", "pt")

            # 4 — Configurações de voz
            self.temperature = float(os.getenv("TTS_TEMPERATURE", "0.25"))
            self.speed = float(os.getenv("TTS_SPEED", "1.0"))
            self.length_penalty = float(os.getenv("TTS_LENGTH_PENALTY", "1.0"))

            # 5 — Perfis de Voz
            profile = os.getenv("VOICE_PROFILE", "expressiva").lower() # Trocar o tom de voz do Enzo

            if profile == "masculina":
                self.temperature = 0.25
                self.speed = 0.92
                self.length_penalty = 1.05

            elif profile == "aguda":
                self.temperature = 0.3
                self.speed = 1.12

            elif profile == "expressiva":
                self.temperature = 0.45
                self.speed = 1.0

            elif profile == "assistente":
                self.temperature = 0.2
                self.speed = 1.0
                self.length_penalty = 1.0

            # 6 — Carrega audio system
            pygame.mixer.init()

            # prepara kwargs padrão filtrados para compatibilidade com chamadas externas
            self._tts_default_tts_kwargs = self._filter_params({
                "speaker_wav": self.speaker_wav,
                "language": self.language,
                "temperature": self.temperature,
                "speed": self.speed,
                "length_penalty": self.length_penalty
            })

            self.ok = True
            print("✅ Speaker XTTS-v2 carregado com sucesso!\n")

        except Exception as e:
            print(f"❌ Falha ao carregar TTS: {e}")
            # desativa o TTS para o restante da execução
            self.enabled = False
            self.ok = False

    # --------------------------------------------------------

    def _filter_params(self, params: dict):
        """
        Remove parâmetros inválidos para evitar erros "model_kwargs unused".
        """
        allowed = {"speaker_wav", "language", "temperature", "speed", "length_penalty"}
        return {k: v for k, v in params.items() if k in allowed and v is not None}

    # --------------------------------------------------------

    def speak(self, text: str, out_path=None):
        """
        Fala o texto usando XTTS-v2, com voz personalizada.
        """

        if not self.enabled or not self.ok:
            print("⚠ Speaker desativado ou falhou ao inicializar")
            return

        if out_path is None:
            out_path = os.path.join(tempfile.gettempdir(), "tts_output.wav")

        print("🎤 Gerando fala...")

        try:
            params = self._filter_params({
                "speaker_wav": self.speaker_wav,
                "language": self.language,
                "temperature": self.temperature,
                "speed": self.speed,
                "length_penalty": self.length_penalty
            })

            # 🔊 Gera o áudio
            self.tts.tts_to_file(
                text=text,
                file_path=out_path,
                **params
            )

            pygame.mixer.music.load(out_path)
            pygame.mixer.music.play()

        except Exception as e:
            print(f"❌ Erro ao gerar fala: {e}")

speaker = Speaker(enabled=ENABLE_TTS, audio_dir=AUDIO_DIR)

# ---------------------------------------------
# Contexto e utilitários
# ---------------------------------------------
gerenciador_contexto = GerenciadorContexto(
    tamanho_maximo=5,
    timeout_minutos=10,
    embedding_func=calcular_embedding,
)

_MYSQL_DT_FORMATS = ("%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M","%Y-%m-%d",)
def parse_mysql_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except Exception:
            return None
    s = str(value).strip()
    if "." in s:
        s = s.split(".", 1)[0]
    for fmt in _MYSQL_DT_FORMATS:
        try: return datetime.strptime(s, fmt)
        except ValueError: continue
    return None

def _datas_no_intervalo(d: datetime, inicio: datetime, fim: datetime) -> bool:
    return inicio <= d <= fim

def verificar_alertas(conn) -> None:
    print(f"\n🔔 Verificando lembretes e eventos para os próximos {ALERTA_JANELA_DIAS} dias...\n")
    hoje = datetime.now()
    limite = hoje + timedelta(days=ALERTA_JANELA_DIAS)
    memorias = listar_memorias(conn)
    for memoria in memorias:
        try:
            memoria_id, tipo, descricao, data_evento, repetir_anualmente, prioridade, tags = memoria
        except Exception:
            continue
        dt = parse_mysql_datetime(data_evento)
        if not dt: continue
        if repetir_anualmente:
            try:
                dt = dt.replace(year=hoje.year)
            except ValueError:
                continue
        if _datas_no_intervalo(dt, hoje, limite):
            msg = f"[{(tipo or '').upper()}] {descricao or '(sem descrição)'} - {dt.strftime('%d/%m/%Y %H:%M')}"
            print("📌", msg)
            speaker.speak(msg)

def iniciar_alertas_periodicos(conn, intervalo_minutos: int = ALERTAS_VERIFICAR_CADA_MIN) -> None:
    def _loop():
        while True:
            try: verificar_alertas(conn)
            except Exception as e: logger.error(f"Erro em verificar_alertas: {e}", extra={"author":"system"})
            time.sleep(max(1,int(intervalo_minutos)) * 60)
    threading.Thread(target=_loop, daemon=True).start()

def iniciar_agendador_alertas(conn, horarios: list[str] | None = None) -> None:
    horarios = horarios or ["09:00","18:00"]
    def _mk_job():
        def _job():
            try: verificar_alertas(conn)
            except Exception as e: logger.error(f"Erro no job de alertas: {e}", extra={"author":"system"})
        return _job
    try:
        import schedule as _rsched
        for h in horarios: _rsched.every().day.at(h).do(_mk_job())
        def _runner():
            while True:
                _rsched.run_pending()
                time.sleep(30)
        threading.Thread(target=_runner, daemon=True).start()
    except Exception:
        iniciar_alertas_periodicos(conn, ALERTAS_VERIFICAR_CADA_MIN)

# ---------------------------------------------
# Enviar áudio via socket
# ---------------------------------------------
def enviar_audio_para_cliente(client_socket: socket.socket, caminho_arquivo: str):
    if not os.path.exists(caminho_arquivo):
        logger.error(f"Arquivo de áudio não encontrado: {caminho_arquivo}", extra={"author":"system"})
        return False
    try:
        tamanho = os.path.getsize(caminho_arquivo)
        header = {"type":"audio","format":"wav","filename": os.path.basename(caminho_arquivo), "size": tamanho}
        client_socket.sendall((json.dumps(header) + "\n").encode("utf-8"))
        with open(caminho_arquivo, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk: break
                client_socket.sendall(chunk)
        logger.info(f"Áudio enviado ({tamanho} bytes).", extra={"author":"system"})
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar áudio via socket: {e}", extra={"author":"system"})
        return False

# ---------------------------------------------
# Função principal de processamento de pergunta
# ---------------------------------------------
def processar_pergunta(pergunta: str, conn, enviar_resposta=None):
    encerrar = False
    if pergunta.lower() == "sair":
        resposta = "🤖 Até logo 👋"
        print(resposta)
        speaker.speak("Até logo, até a próxima!")
        if enviar_resposta:
            try: enviar_resposta(resposta)
            except Exception as e: logger.error(f"Erro ao enviar resposta via rede: {e}", extra={"author":"system"})
        return resposta, True

    cmd = pergunta.lower()
    if cmd in {"add", "+"}:
        try: adicionar_memoria_interativa(conn)
        except Exception as e: logger.error(f"add erro: {e}", extra={"author":"user"})
        return None, False
    # suporte genérico a "run <nome do jogo>"
    if cmd.startswith("run "):
        game_name = cmd[4:].strip().lower()
        # mapeie nomes de comando para executáveis/paths no Raspberry Pi
        jogos = {
            "abyss of shadows": {
                "id": "abyss_of_shadows",
                "rom": "/home/far/games/abyss_of_shadows.gba"
            },
            "cat tower": {
                "id": "cat_tower",
                "rom": "/home/far/games/cat_tower.gba"
            }
        }
        info = jogos.get(game_name)
        if not info:
            msg = f"Jogo '{game_name}' não reconhecido."
            print(msg)
            try:
                if enviar_resposta:
                    # envia resposta de texto normal (será mostrado no cliente)
                    enviar_resposta({"type": "text", "content": msg})
                else:
                    speaker.speak(msg)
            except Exception as e:
                logger.error(f"erro ao enviar resposta de jogo desconhecido: {e}", extra={"author":"system"})
            return None, False

        payload = {
            "type": "cmd",
            "action": "run",
            "emulator": "mgba",
            "rom_path": info["rom"],
            "game": info["id"]
        }

        try:
            if enviar_resposta:
                enviar_resposta(payload)
                print(f"Enviando comando para abrir {game_name} no cliente...")
            else:
                print("Nenhum cliente conectado para rodar o jogo.")
                import subprocess
                try:
                    subprocess.Popen(info["exec"], shell=True, start_new_session=True)
                    speaker.speak(f"Iniciando {game_name} localmente.")
                except Exception as e:
                    logger.error(f"falha ao iniciar jogo localmente: {e}", extra={"author":"system"})
                    speaker.speak("Falha ao iniciar o jogo localmente.")
        except Exception as e:
            logger.error(f"erro ao enviar comando run para cliente: {e}", extra={"author":"system"})
        return None, False
    if cmd in {"list", "ls"}:
        try: listar_memorias_interativa(conn)
        except Exception as e: logger.error(f"list erro: {e}", extra={"author":"user"})
        return None, False
    if cmd in {"remove", "rm"}:
        try: remover_memoria_interativa(conn)
        except Exception as e: logger.error(f"remove erro: {e}", extra={"author":"user"})
        return None, False
    if cmd in {"edit", "ed"}:
        try: editar_memoria_interativa(conn)
        except Exception as e: logger.error(f"edit erro: {e}", extra={"author":"user"})
        return None, False
    if cmd in {"alert", "alerts"}:
        try:
            msg = gerar_alertas(conn)
            print(msg)
            speaker.speak(msg)
            if enviar_resposta: enviar_resposta(msg)
        except Exception as e:
            logger.error(f"alert erro: {e}", extra={"author":"user"})
        return None, False

    try:
        gerenciador_contexto.adicionar_mensagem(pergunta)
    except Exception:
        pass

    resposta = None
    try:
        debug_flag = os.getenv("DEBUG_CANDIDATES", "0") == "1"
        # caminho de log para debug candidates (usa LOG_DIR do core.config)
        debug_log_path = os.path.join(LOG_DIR, "candidates_debug.jsonl")

        resposta = buscar_resposta_usuario(pergunta, conn,
                                           debug_candidates=debug_flag,
                                           debug_log_path=debug_log_path)
    except Exception as e:
        logger.error(f"Erro ao buscar_resposta_usuario: {e}", extra={"author":"system"})

    if resposta:
        print(f"Chatbot: {resposta}\n")
        if enviar_resposta:
            try:
                enviar_resposta(resposta)
            except Exception as e:
                logger.error(f"Erro ao enviar resposta via rede: {e}", extra={"author":"system"})
        else:
            speaker.speak(resposta)

        try:
            gerenciador_contexto.adicionar_mensagem(resposta, autor="bot")
        except Exception:
            pass
        return resposta, False

    # fallback: quando não sabe
    if enviar_resposta is None:
        usar_internet = input(f"🤖 Não sei responder '{pergunta}'. Buscar na internet? (s/n): ").strip().lower()
        if usar_internet == "s":
            try:
                resp2 = None
                try: resp2 = buscar_resposta_usuario(pergunta, conn)
                except Exception: pass
                if resp2:
                    print(f"Chatbot: {resp2}\n")
                    speaker.speak(resp2)
                    try: gerenciador_contexto.adicionar_mensagem(resp2, autor="bot")
                    except Exception: pass
                    return resp2, False
            except Exception as e:
                logger.error(f"Erro ao processar busca na internet: {e}", extra={"author":"system"})
        return None, False
    else:
        resposta = f"🤖 Não sei responder '{pergunta}'."
        print(resposta)
        try:
            enviar_resposta(resposta)
        except Exception as e:
            logger.error(f"Erro ao enviar resposta via rede: {e}", extra={"author":"system"})
        return resposta, False

# ---------------------------------------------
# Loop do servidor (rede)
# ---------------------------------------------
def iniciar_chat(modo_rede: bool = False, host: str = "0.0.0.0", port: int = 5000) -> None:
    conn = inicializar_banco()
    # pre-aquecimento (normalização/embeddings)
    try:
        atualizar_texto_normalizado(conn)
    except Exception as e:
        logger.error(f"Erro ao atualizar texto normalizado: {e}", extra={"author":"system"})
    try:
        buf = io.StringIO(); old = sys.stdout; sys.stdout = buf
        try: atualizar_embeddings(conn)
        finally: sys.stdout = old
    except Exception as e:
        logger.error(f"Erro ao atualizar embeddings: {e}", extra={"author":"system"})

    try:
        verificar_alertas(conn)
    except Exception as e:
        logger.error(f"Erro inicial em verificar_alertas: {e}", extra={"author":"system"})

    if not modo_rede:
        # REPL local
        print("\n🤖 Chatbot iniciado! (digite 'sair' para encerrar)\n")
        speaker.speak("Chatbot iniciado! Digite sair para encerrar.")
        while True:
            try:
                pergunta = input("Você: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n🤖 Até logo 👋")
                speaker.speak("Até logo, até a próxima!")
                break
            if not pergunta:
                continue
            resp, enc = processar_pergunta(pergunta, conn)
            if enc:
                break
    else:
        # socket TCP tradicional — compatível com seu cliente
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.listen()
            print(f"\n🤖 Servidor do Chatbot rodando em {host}:{port}\n")
            speaker.speak("Servidor do Chatbot iniciado.")
            while True:
                client, addr = s.accept()
                threading.Thread(target=_handle_client, args=(client, addr, conn), daemon=True).start()

def _handle_client(client, addr, conn):
    with client:
        print(f"Conectado por {addr}")
        while True:
            try:
                data = client.recv(4096)
            except Exception as e:
                print("Erro recv:", e); break
            if not data:
                break
            pergunta = data.decode("utf-8", errors="ignore").strip()
            if not pergunta:
                continue
            print(f"Você: {pergunta}")

            def enviar_resposta_cliente(text_or_json):
                try:
                    # Se já vier um dict (payload JSON), envie-o diretamente como JSON (linha única + \n)
                    if isinstance(text_or_json, dict):
                        client.sendall((json.dumps(text_or_json) + "\n").encode("utf-8"))
                        return

                    if isinstance(text_or_json, bytes):
                        text = text_or_json.decode("utf-8", errors="ignore")
                    else:
                        text = str(text_or_json)

                    # comportamento antigo: se TTS habilitado, envia áudio; senão envia como text payload
                    if ENABLE_TTS and speaker.enabled and speaker.ok:
                        arquivo_wav = os.path.join(speaker.audio_dir, "output.wav")
                        try:
                            # pega kwargs default (p.ex. {"speaker_wav": [...], "language": "pt"}) se existirem
                            kws = getattr(speaker, "_tts_default_tts_kwargs", {}) or {}
                            try:
                                # Chamada preferida: passa os kwargs (clonagem, idioma, etc.)
                                speaker._tts.tts_to_file(text=text, file_path=arquivo_wav, **kws)
                            except TypeError:
                                # Caso a assinatura seja diferente/antiga, tente sem kwargs
                                speaker._tts.tts_to_file(text, arquivo_wav)
                        except Exception:
                            # fallback para o método speak (mantendo compatibilidade com versões antigas)
                            try:
                                speaker.speak(text)
                            except Exception:
                                pass

                        enviar_audio_para_cliente(client, arquivo_wav)
                    else:
                        payload = {"type":"text","content": text}
                        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                except Exception as e:
                    logger.error(f"enviar_resposta_cliente erro: {e}", extra={"author":"system"})

            resposta, encerrar = processar_pergunta(pergunta, conn, enviar_resposta=enviar_resposta_cliente)
            if encerrar:
                break

# ---------------------------------------------
# Entry point
# ---------------------------------------------
if __name__ == "__main__":
    conn = inicializar_banco()
    iniciar_agendador_alertas(conn, horarios=["09:00", "18:00"])
    #iniciar_alertas_periodicos(conn, ALERTAS_VERIFICAR_CADA_MIN)
    
    # rodar server em modo rede por padrão (altere aqui se quiser REPL local)
    iniciar_chat(modo_rede=True, host="0.0.0.0", port=5000)
