from __future__ import annotations
import argparse
import base64
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional, Tuple
import http.server
import urllib.parse

BUFFER = 65536
RECV_TIMEOUT = 1.0  # timeout para recv non-blocking em loops

try:
    import tkinter as tk
    TK_AVAILABLE = True
except Exception:
    tk = None
    TK_AVAILABLE = False


# ---------------- pygame init (lazy) ----------------
_pygame_available = False
pygame = None
try:
    import pygame as _pygame
    pygame = _pygame
    _pygame_available = True
except Exception:
    _pygame_available = False
    pygame = None

def _init_pygame_mixer() -> bool:
    """Inicializa pygame.mixer de forma segura (lazy init)."""
    if not _pygame_available:
        return False
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return True
    except Exception:
        return False

def play_with_pygame(path: str) -> bool:
    try:
        if not _init_pygame_mixer():
            return False
        # pygame.music lida bem com wav/ogg; blocking é feito com busy loop
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        try:
            # tenta descarregar se suportado
            pygame.mixer.music.unload()
        except Exception:
            pass
        return True
    except Exception:
        return False

def play_with_command(path: str) -> bool:
    """Fallback para players do sistema (aplay/mpv)."""
    if shutil.which("aplay"):
        try:
            subprocess.run(["aplay", path], check=True)
            return True
        except Exception:
            pass
    if shutil.which("mpv"):
        try:
            subprocess.run(["mpv", "--no-video", "--really-quiet", path], check=True)
            return True
        except Exception:
            pass
    return False

# ---------------- utilitários de ficheiros ----------------
def safe_mkdir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def atomic_write_and_replace(final_path: str, data: bytes) -> bool:
    """Escreve bytes atomicamente em final_path (usa tmp + os.replace)."""
    dirpath = os.path.dirname(final_path) or "."
    safe_mkdir(dirpath)
    fd, tmp = tempfile.mkstemp(prefix="tmp_recv_", dir=dirpath)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, final_path)  # atomic replace
        return True
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False

# ---------------- leitura de linha (header) + resto ----------------
def recv_line_and_rest(sock: socket.socket, timeout: float = 5.0) -> Tuple[Optional[str], bytes]:
    """Lê até a primeira newline (\n) e retorna (linha_decodificada, rest_bytes)."""
    sock.settimeout(timeout)
    data = b""
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                line, rest = data.split(b"\n", 1)
                return line.decode("utf-8", errors="ignore"), rest
    except socket.timeout:
        return None, b""
    except Exception:
        return None, b""
    finally:
        try:
            sock.settimeout(None)
        except Exception:
            pass
    if data:
        try:
            return data.decode("utf-8", errors="ignore"), b""
        except Exception:
            return None, data
    return None, b""

# ---------------- threads: receiver + playback ----------------
playing_event: Optional[threading.Event] = None  # criado no main e usado pelo GUI

def playback_worker(audio_q: "queue.Queue[Tuple[bytes,str]]", audio_dir: str, stop_event: threading.Event) -> None:
    """
    Consome áudios da fila e toca um a um. Remove arquivos após reprodução.
    Cada item da fila: (audio_bytes, filename)
    """
    while not stop_event.is_set():
        try:
            item = audio_q.get(timeout=0.5)
        except queue.Empty:
            continue
        if item is None:
            break
        audio_bytes, filename = item
        filepath = os.path.join(audio_dir, filename or "recv_audio.wav")
        ok = atomic_write_and_replace(filepath, audio_bytes)
        if not ok:
            print("[player] falha ao salvar áudio.")
            continue

        # sinaliza GUI que estamos reproduzindo
        if playing_event:
            playing_event.set()

        try:
            played = False
            if play_with_pygame(filepath):
                played = True
            else:
                if play_with_command(filepath):
                    played = True

            if not played:
                print("[player] nenhum player disponível para reproduzir o áudio.")
        finally:
            # limpa evento e arquivo
            if playing_event:
                try:
                    playing_event.clear()
                except Exception:
                    pass
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass

def receiver_loop(sock: socket.socket, audio_q: "queue.Queue[Tuple[bytes,str]]", stop_event: threading.Event) -> None:
    """
    Lê continuamente mensagens do servidor.
    Aceita:
      - uma linha JSON com header {"type":"audio","size":N}
        seguido por N bytes de áudio
      - uma linha JSON com {"type":"audio","content":"<base64>"} (inline)
      - {"type":"text","content":"..."}
    """
    sock.settimeout(RECV_TIMEOUT)
    while not stop_event.is_set():
        try:
            header_line, rest = recv_line_and_rest(sock, timeout=RECV_TIMEOUT)
            if not header_line:
                continue
            # tenta carregar JSON do header_line
            try:
                hdr = json.loads(header_line)
            except Exception:
                # tenta juntar rest e decodificar (caso JSON tenha vindo tudo junto)
                try:
                    combined = header_line
                    if rest:
                        combined = header_line + rest.decode("utf-8", errors="ignore")
                    js = json.loads(combined)
                    if isinstance(js, dict):
                        if js.get("type") == "audio" and js.get("content"):
                            audio_bytes = base64.b64decode(js.get("content"))
                            audio_q.put((audio_bytes, js.get("filename") or "recv_audio.wav"))
                            continue
                        if js.get("type") == "text":
                            print("Assistente:", js.get("content", ""))
                            continue
                except Exception:
                    continue
                continue

            tipo = hdr.get("type")
            if tipo == "audio" and "size" in hdr:
                size = int(hdr.get("size", 0))
                audio_bytes = b""
                if rest:
                    audio_bytes += rest
                while len(audio_bytes) < size:
                    chunk = sock.recv(BUFFER)
                    if not chunk:
                        break
                    audio_bytes += chunk
                audio_bytes = audio_bytes[:size]
                audio_q.put((audio_bytes, hdr.get("filename") or "recv_audio.wav"))
                continue
            elif tipo == "audio" and hdr.get("content"):
                audio_bytes = base64.b64decode(hdr.get("content"))
                audio_q.put((audio_bytes, hdr.get("filename") or "recv_audio.wav"))
                continue
            elif tipo == "cmd":
                action = hdr.get("action")
                if action == "run":
                    emulator = hdr.get("emulator")
                    rom_path = hdr.get("rom_path")
                    game = hdr.get("game", "unknown")
                    if emulator == "mgba" and rom_path:
                        try:
                            subprocess.Popen(["mgba", rom_path], start_new_session=True)
                            msg = {"type": "text", "content": f"Iniciando '{game}' via mGBA."}
                            sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
                        except Exception as e:
                            err = {"type": "text", "content": f"Erro ao iniciar mGBA: {e}"}
                            sock.sendall((json.dumps(err) + "\n").encode("utf-8"))
                    else:
                        msg = {"type": "text", "content": "Comando inválido ou ROM não especificada."}
                        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
                    continue
                else:
                    # ações futuras
                    print("[client] cmd desconhecido:", hdr)
                continue
            elif tipo == "text":
                print("Assistente:", hdr.get("content", ""))
                continue
            else:
                # desconhecido -> ignora
                continue
        except (socket.timeout, BlockingIOError):
            continue
        except Exception as e:
            print("[receiver] erro:", e)
            break

# ---------------- cliente (rede) ----------------
def run_client(args, send_q=None) -> None:
    safe_mkdir(args.audio_dir)
    audio_q: "queue.Queue[Tuple[bytes,str]]" = queue.Queue()
    stop_event = threading.Event()

    if send_q is None:
        send_q: "queue.Queue[Optional[str]]" = queue.Queue()

        def input_thread(q: "queue.Queue[Optional[str]]"):
            while True:
                try:
                    # tenta ler do /dev/tty (caso você rode via systemd ou ssh sem tty)
                    with open('/dev/tty', 'r') as tty:
                        for line in tty:
                            msg = line.strip()
                            if msg:
                                q.put(msg)
                except Exception:
                    # fallback para input() quando /dev/tty não existir
                    try:
                        msg = input("Você: ").strip()
                        if msg:
                            q.put(msg)
                    except (EOFError, KeyboardInterrupt):
                        print("\nEncerrando cliente (input).")
                        q.put(None)
                        return
        threading.Thread(target=input_thread, args=(send_q,), daemon=True).start()

    else:
        # Se send_q foi passada (GUI será usada), ainda criamos uma thread de input como fallback.
        def input_thread(q: "queue.Queue[Optional[str]]"):
            while True:
                try:
                    msg = input("Você: ").strip()
                    if msg:
                        q.put(msg)
                except (EOFError, KeyboardInterrupt):
                    print("\nEncerrando cliente (input).")
                    q.put(None)
                    return

        threading.Thread(target=input_thread, args=(send_q,), daemon=True).start()

    while True:
        try:
            print(f"Tentando conectar em {args.server}:{args.port} ...")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((args.server, args.port))
                s.settimeout(None)
                print("Conectado ao servidor! Digite suas mensagens. Ctrl+C para sair.")

                # iniciar receiver + playback threads
                recv_stop = threading.Event()
                play_stop = threading.Event()
                recv_thread = threading.Thread(target=receiver_loop, args=(s, audio_q, recv_stop), daemon=True)
                play_thread = threading.Thread(target=playback_worker, args=(audio_q, args.audio_dir, play_stop), daemon=True)
                recv_thread.start()
                play_thread.start()

                # loop principal apenas envia mensagens (recebimento é assíncrono)
                while True:
                    try:
                        msg = send_q.get()
                        if msg is None:
                            # sinaliza parada para threads e fecha socket
                            recv_stop.set()
                            play_stop.set()
                            try:
                                s.shutdown(socket.SHUT_RDWR)
                            except Exception:
                                pass
                            s.close()
                            return
                        if not msg:
                            continue
                        s.sendall((msg + "\n").encode("utf-8"))
                    except (BrokenPipeError, ConnectionResetError) as e:
                        print("[client] conexão perdida:", e)
                        break
                    except Exception as e:
                        print("[client] erro ao enviar:", e)
                        break

                # final do while-> tentar reconectar
        except KeyboardInterrupt:
            print("\nCliente finalizado pelo usuário.")
            return
        except Exception as e:
            print(f"Conexão falhou: {e}. Tentando novamente em 5s...")
            time.sleep(5)

# ---------------- GUI/rostinho ----------------
try:
    import tkinter as tk
    TK_AVAILABLE = True
except Exception:
    tk = None
    TK_AVAILABLE = False

try:
    from PIL import Image, ImageSequence, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

class FaceAnimator:
    def __init__(self, playing_event: threading.Event, gif_idle="IDLE.gif", gif_speek="speek.gif", size=(480, 320), send_q=None):
        self.playing_event = playing_event
        self.gif_idle = gif_idle
        self.gif_speek = gif_speek
        self.size = size
        self.send_q = send_q #type: ignore
        self.root: Optional[tk.Tk] = None #type: ignore
        self.label: Optional[tk.Label] = None #type: ignore
        self.frames_idle = []
        self.frames_speek = []
        self.current_frames = []
        self.frame_index = 0
        self.mode = None  # 'idle' | 'speek'
        self.headless = not TK_AVAILABLE

    def _resource_path(self, name: str) -> str:
        try:
            base = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base = os.getcwd()
        return os.path.join(base, name)

    def carregar_gif_with_tk(self, caminho: str):
        frames = []
        if not TK_AVAILABLE:
            return frames
        i = 0
        while True:
            try:
                frame = tk.PhotoImage(file=caminho, format=f"gif -index {i}")
                frames.append(frame)
                i += 1
            except Exception:
                break
        return frames

    def carregar_gif_with_pil(self, caminho: str):
        frames = []
        if not PIL_AVAILABLE:
            return frames
        try:
            img = Image.open(caminho)
            for frame in ImageSequence.Iterator(img):
                frame = frame.convert("RGBA")
                if self.size:
                    # redimensiona preservando proporção e centraliza em background transparente
                    orig_w, orig_h = frame.size
                    target_w, target_h = self.size
                    scale = min(target_w / orig_w, target_h / orig_h)
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    resized = frame.resize((new_w, new_h), Image.LANCZOS)
                    bg = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                    paste_x = (target_w - new_w) // 2
                    paste_y = (target_h - new_h) // 2
                    bg.paste(resized, (paste_x, paste_y), resized)
                    tkimg = ImageTk.PhotoImage(bg)
                else:
                    tkimg = ImageTk.PhotoImage(frame)
                frames.append(tkimg)
        except Exception:
            pass
        return frames

    def load_gifs(self):
        idle_path = self._resource_path(self.gif_idle)
        speek_path = self._resource_path(self.gif_speek)
        self.frames_idle = []
        self.frames_speek = []
        if TK_AVAILABLE:
            self.frames_idle = self.carregar_gif_with_tk(idle_path) or self.carregar_gif_with_pil(idle_path)
            self.frames_speek = self.carregar_gif_with_tk(speek_path) or self.carregar_gif_with_pil(speek_path)
        elif PIL_AVAILABLE:
            self.frames_idle = self.carregar_gif_with_pil(idle_path)
            self.frames_speek = self.carregar_gif_with_pil(speek_path)

    def setup(self):
        if not TK_AVAILABLE:
            self.headless = True
            print("Tkinter não disponível: rodando em modo headless (sem janela).")
            return

        if "DISPLAY" not in os.environ:
            os.environ["DISPLAY"] = ":0"

        self.root = tk.Tk()
        self.root.title("Rostinho")
        # deixar a janela sempre por cima (sempre sobresalente)
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
            # liga um atalho para alternar (Alt+T) caso você queira desativar temporariamente
            self.root.bind('<Alt-t>', lambda e: self._toggle_topmost())
        except Exception:
            pass

        # detecta resolução da tela para evitar sobreposição com o terminal
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = self.size

        # reservar uma faixa na parte inferior para o terminal/miniterm (em px)
        reserved_bottom = max(64, int(screen_h * 0.15))

        # altura da janela será a tela inteira menos a reserva para terminal
        win_w = min(self.size[0], screen_w)
        win_h = max(120, min(self.size[1], screen_h - reserved_bottom))

        # altura disponível para o GIF (subtrai o espaço do bottom_frame)
        bottom_frame_h = 44
        gif_h = max(80, win_h - bottom_frame_h)
        gif_w = win_w

        try:
            # posiciona no topo para que o terminal (abaixo) fique visível
            self.root.geometry(f"{win_w}x{win_h}+0+0")
        except Exception:
            pass
        self.root.resizable(False, False)

        # Frame do rosto (ocupa a maior parte)
        self.label = tk.Label(self.root, bg="#60d3e6")
        self.label.pack(side="top", fill="both", expand=True)

        # atualiza o tamanho que informaremos ao loader de GIFs para redimensionar
        self.size = (gif_w, gif_h)

        self.load_gifs()
        if not (self.frames_idle or self.frames_speek):
            print("Aviso: nenhuma GIF encontrada (IDLE.gif / speek.gif). A GUI iniciará vazia.")
        self._set_mode("idle")
        self.root.after(100, self._update)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # --- caixa de texto + botão enviar para enviar ao servidor ---
        try:
            print("DEBUG: TK_AVAILABLE =", TK_AVAILABLE, " DISPLAY =", os.environ.get("DISPLAY"))
        except Exception:
            pass

        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(side="bottom", fill="x", padx=4, pady=4)

        self.entry = tk.Entry(bottom_frame)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0,4))

        # placeholder + comportamento para limpar ao focar
        try:
            self.entry.insert(0, "Digite aqui... (pressione Enter ou clique Enviar)")
            self.entry.bind("<FocusIn>", lambda e: (self.entry.delete(0, tk.END) if self.entry.get().startswith("Digite aqui") else None))
        except Exception:
            pass

        # bind Enter
        self.entry.bind("<Return>", lambda e: self._send_entry())

        # tornar óbvio e focar
        try:
            self.entry.focus_set()
            self.root.lift()
            self.root.update_idletasks()
        except Exception:
            pass

        send_btn = tk.Button(bottom_frame, text="Enviar", command=self._send_entry)
        send_btn.pack(side="right")

        print("DEBUG: widgets de envio criados (Entry + Button).")

    def _send_entry(self):
        """Pega o texto do Entry e coloca na send_q para o run_client enviar."""
        try:
            if not hasattr(self, "entry"):
                return
            msg = self.entry.get().strip()
            if not msg:
                return

            if self.send_q:
                try:
                    self.send_q.put(msg)
                    # debug: mostra no terminal que a GUI enfileirou a mensagem
                    print("ENFILEIRANDO (GUI):", msg)
                except Exception as e:
                    print("Erro ao enfileirar mensagem:", e)
            else:
                # send_q não foi passada — útil para depurar
                print("send_q não definido; mensagem não enviada:", msg)

            # limpa o campo após enviar e devolve o foco ao Entry
            try:
                self.entry.delete(0, tk.END)
                self.entry.focus_set()
            except Exception:
                pass

        except Exception as e:
            print("Erro em _send_entry:", e)

    def _on_close(self):
        try:
            if self.root:
                self.root.destroy()
        except Exception:
            pass

    def _toggle_topmost(self):
        """Alterna o atributo "-topmost" para permitir que o usuário desative/ative rapidamente."""
        try:
            cur = False
            try:
                cur = bool(self.root.attributes("-topmost"))
            except Exception:
                # alguns gerenciadores não suportam attributes de forma consistente
                pass
            try:
                self.root.attributes("-topmost", not cur)
                print(f"Topmost agora = {not cur}")
            except Exception:
                pass
        except Exception:
            pass

    def _set_mode(self, mode: str):
        if mode == self.mode:
            return
        self.mode = mode
        self.frame_index = 0
        if mode == "idle":
            self.current_frames = self.frames_idle or self.frames_speek
        else:
            self.current_frames = self.frames_speek or self.frames_idle

    def _update(self):
        if not self.root or not self.label:
            return
        try:
            is_playing = bool(self.playing_event and self.playing_event.is_set())
        except Exception:
            is_playing = False

        self._set_mode("speek" if is_playing else "idle")
        if self.current_frames:
            idx = self.frame_index % len(self.current_frames)
            try:
                self.label.config(image=self.current_frames[idx])
            except Exception:
                pass
            self.frame_index += 1
        try:
            self.root.after(100, self._update)
        except Exception:
            pass

    def headless_loop(self):
        try:
            blink = False
            while True:
                is_playing = bool(self.playing_event and self.playing_event.is_set())
                if is_playing:
                    print("[ROSTO] falando...")
                    while self.playing_event.is_set():
                        time.sleep(0.2)
                    print("[ROSTO] parou de falar.")
                else:
                    blink = not blink
                    if blink:
                        print("[ROSTO] (idle) olho fechado")
                    else:
                        print("[ROSTO] (idle) olho aberto")
                    time.sleep(2.0)
        except Exception:
            pass

    def run(self):
        self.setup()
        if self.headless:
            t = threading.Thread(target=self.headless_loop, daemon=True)
            t.start()
            return
        try:
            self.root.mainloop()
        except Exception:
            pass

# ---------------- small webserver to accept messages (useful when headless) ----------------
class _SimpleSendHandler(http.server.BaseHTTPRequestHandler):
    send_q_ref: Optional[queue.Queue] = None

    def do_GET(self):
        if self.path.startswith('/static'):
            self.send_response(404)
            self.end_headers()
            return
        # Página simples com um formulário
        html = ("<html><head><meta charset='utf-8'><title>Enviar Mensagem</title></head>"
                "<body><h2>Enviar mensagem ao servidor</h2>"
                "<form method='POST' action='/send'>"
                "<input type='text' name='msg' style='width:80%%' placeholder='Digite a mensagem'/>"
                "<input type='submit' value='Enviar'/>"
                "</form>"
                "<p>Feche o navegador quando terminar.</p>"
                "</body></html>")
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def do_POST(self):
        if self.path != '/send':
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get('Content-Length', '0'))
        data = self.rfile.read(length)
        params = urllib.parse.parse_qs(data.decode('utf-8', errors='ignore'))
        msg = params.get('msg', [''])[0].strip()
        if msg and _SimpleSendHandler.send_q_ref is not None:
            try:
                _SimpleSendHandler.send_q_ref.put(msg)
                print("ENFILEIRANDO (WEB):", msg)
                response = "OK"
            except Exception as e:
                print("ERRO ao enfileirar via WEB:", e)
                response = "ERRO"
        else:
            response = "VAZIO"
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

def start_web_server(send_q: queue.Queue, host='0.0.0.0', port=8080):
    _SimpleSendHandler.send_q_ref = send_q
    server = http.server.ThreadingHTTPServer((host, port), _SimpleSendHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Web input server iniciado em http://{host}:{port} — abra no navegador para enviar mensagens")
    return server

# ---------------- main ----------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", "-s", default="192.168.6.5", help="IP do servidor (PC)") #10.0.62.220 ip do raspberry
    parser.add_argument("--port", "-p", default=5000, type=int, help="Porta do servidor")
    parser.add_argument("--audio-dir", default="~/chatbot/audio_received", help="Pasta para salvar áudios")
    parser.add_argument("--gif-idle", default="IDLE.gif", help="GIF idle (piscar)")
    parser.add_argument("--gif-speek", default="speek.gif", help="GIF falando")
    parser.add_argument("--no-web", action='store_true', help="Não iniciar webserver automático quando headless")
    args = parser.parse_args()

    args.audio_dir = os.path.expanduser(args.audio_dir)
    safe_mkdir(args.audio_dir)

    # evento global usado pela GUI para mostrar quando está tocando
    global playing_event
    playing_event = threading.Event()

    # inicia o cliente TCP em thread (para manter a GUI no main thread)
    send_q = queue.Queue()
    client_thread = threading.Thread(target=run_client, args=(args, send_q), daemon=True)
    client_thread.start()

    # inicia o animador (GUI) no main thread
    animator = FaceAnimator(playing_event, gif_idle=args.gif_idle, gif_speek=args.gif_speek, size=(480, 320), send_q=send_q)
    animator.run()

    # se headless (sem GUI), mantém processo vivo e cria webserver para entrada de texto
    if animator.headless:
        if not args.no_web:
            try:
                #server = start_web_server(send_q, host='0.0.0.0', port=8080)
                print("Acesse no navegador: http://<IP-do-Raspberry>:8080 para enviar mensagens.")
            except Exception as e:
                print("Falha ao iniciar webserver:", e)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Encerrando (headless).")

if __name__ == "__main__":
    main()
