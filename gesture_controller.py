"""
gesture_controller.py
Sistema de Visão Computacional Controlado por Gestos de Mão
Desenvolvido para a Feira Cultural de TI.

Funcionalidades:
1. Deteção de Mão Aberta (5 dedos estendidos) invariante à rotação.
2. Cálculo de Rotação no Sentido Horário (0° a 90°) em relação à vertical.
3. Servidor WebSocket integrado para escurecimento progressivo do index.html em tempo real.
4. Transição automática aos 90° para a página creditos.html com cooldown de segurança.
5. Manutenção dos gestos de 'Joia' (abrir index.html) e 'Dois' (fechar navegador).
6. Compatível com Windows e Linux.
"""

import os
import sys
import time
import math
import json
import asyncio
import threading
import subprocess
import urllib.request
import webbrowser
import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Detecção de plataforma
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"

# Importações condicionais para Windows
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

# ---------------------------------------------------------------------------
# Caminhos dos Arquivos
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
CREDITOS_HTML_PATH = os.path.join(BASE_DIR, "creditos.html")
AUDIO_FILE_NAME = "Efeito Sonoro de Transição - [Crescendo Reverse 1].mp3"
TRANSITION_AUDIO_PATH = os.path.join(BASE_DIR, AUDIO_FILE_NAME)

# Configuração de Reprodução de Áudio durante a Rotação
# Windows: reprodução nativa via WinMM MCI (latência zero)
# Linux/Mac: via subprocess (mpg123, afplay) ou delega ao front-end
PLAY_AUDIO_NATIVELY = IS_WINDOWS  # True no Windows, False no Linux/Mac

# ---------------------------------------------------------------------------
# Parâmetros de Gestos e Rotação
# ---------------------------------------------------------------------------
ROTATION_TARGET_ANGLE = 90.0        # Ângulo máximo para a transição (graus)
ROTATION_TRIGGER_FRAMES = 5         # Frames necessários a 90° para disparar transição
ROTATION_COOLDOWN_SECONDS = 3.5     # Cooldown após abrir creditos.html

REQUIRED_CONSECUTIVE_FRAMES = 18   # Debouncing para 'Joia' e 'Dois'
COOLDOWN_SECONDS = 2.0             # Cooldown para ações de atalho

# Cores em formato BGR (OpenCV)
COLOR_BG_HUD = (24, 24, 32)
COLOR_TEXT_WHITE = (255, 255, 255)
COLOR_TEXT_MUTED = (160, 160, 175)
COLOR_ACCENT_GREEN = (46, 204, 113)
COLOR_ACCENT_BLUE = (235, 130, 60)
COLOR_ACCENT_RED = (70, 70, 230)
COLOR_ACCENT_PURPLE = (200, 100, 240)
COLOR_ACCENT_YELLOW = (40, 200, 250)

# ---------------------------------------------------------------------------
# Servidor WebSocket Local Assíncrono (Comunicação com o index.html)
# ---------------------------------------------------------------------------
connected_clients = set()
ws_loop = None


async def ws_handler(websocket):
    """Gerencia novas conexões WebSocket provenientes do index.html."""
    connected_clients.add(websocket)
    try:
        # Envia estado inicial neutro
        init_payload = json.dumps({
            "type": "rotation",
            "angle": 0.0,
            "progress": 0.0,
            "sound_handled_by_backend": PLAY_AUDIO_NATIVELY,
        })
        await websocket.send(init_payload)
        async for _ in websocket:
            pass
    except Exception:
        pass
    finally:
        connected_clients.discard(websocket)


async def _broadcast(message_str):
    """Envia mensagem para todos os clientes conectados."""
    if connected_clients:
        dead = []
        for client in list(connected_clients):
            try:
                await client.send(message_str)
            except Exception:
                dead.append(client)
        for d in dead:
            connected_clients.discard(d)


def broadcast_message(data_dict):
    """Helper síncrono para enviar dados via WebSocket a partir do loop OpenCV."""
    global ws_loop
    if ws_loop and ws_loop.is_running() and connected_clients:
        msg = json.dumps(data_dict)
        asyncio.run_coroutine_threadsafe(_broadcast(msg), ws_loop)


def start_websocket_server(host="127.0.0.1", port=8765):
    """Inicia o servidor WebSocket em uma thread dedicada em background."""
    global ws_loop

    def run_server():
        global ws_loop
        ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)

        import websockets

        async def main():
            async with websockets.serve(ws_handler, host, port):
                print(f"[WEBSOCKET] Servidor ativo em ws://{host}:{port}")
                await asyncio.Future()  # Mantém ativo

        ws_loop.run_until_complete(main())

    t = threading.Thread(target=run_server, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Gerenciador de Áudio Nativo de Transição (Multiplataforma)
# ---------------------------------------------------------------------------
class TransitionSoundManager:
    """
    Gerencia a reprodução nativa do efeito sonoro durante a rotação da mão aberta.
    - Windows: usa WinMM MCI (latência zero, sem restrição de autoplay).
    - Linux: usa mpg123, ffplay ou vlc via subprocess.
    - Mac: usa afplay via subprocess.
    Se nenhum player estiver disponível, delega ao front-end (via WebSocket).
    """

    def __init__(self, audio_path):
        self.audio_path = os.path.abspath(audio_path)
        self.is_playing = False
        self.available = False
        self._proc = None  # Para Linux/Mac

        if IS_WINDOWS:
            self._init_windows()
        elif IS_LINUX or IS_MAC:
            self._init_unix()
        else:
            print("[ÁUDIO] Plataforma não suportada para áudio nativo. Front-end reproduzirá o som.")

    # ── Windows: WinMM MCI ──
    def _init_windows(self):
        if not os.path.exists(self.audio_path):
            print(f"[ÁUDIO] Arquivo não encontrado: {self.audio_path}")
            return
        try:
            self.alias = "trans_crescendo_sfx"
            self.mci = ctypes.windll.winmm.mciSendStringW
            self._cmd(f'close {self.alias}')
            err, _ = self._cmd(f'open "{self.audio_path}" type mpegvideo alias {self.alias}')
            if err == 0:
                self.available = True
                self._cmd(f"setaudio {self.alias} volume to 1000")
                print(f"[ÁUDIO] Som carregado (Windows MCI): {os.path.basename(self.audio_path)}")
            else:
                print(f"[ÁUDIO] Erro MCI (código {err}). Áudio será reproduzido pelo navegador.")
        except Exception as e:
            print(f"[ÁUDIO] Erro ao inicializar Windows MCI: {e}")

    def _cmd(self, cmd_str):
        buf = ctypes.create_unicode_buffer(128)
        err = self.mci(cmd_str, buf, 128, None)
        return err, buf.value

    # ── Linux / Mac: subprocess com player de linha de comando ──
    def _init_unix(self):
        if not os.path.exists(self.audio_path):
            print(f"[ÁUDIO] Arquivo não encontrado: {self.audio_path}")
            return
        # Detecta player disponível
        players = ["mpg123", "ffplay", "vlc", "afplay"]
        self._player_cmd = None
        for player in players:
            try:
                result = subprocess.run(
                    ["which", player], capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0 and result.stdout.strip():
                    self._player_cmd = player
                    break
            except Exception:
                continue

        if self._player_cmd:
            self.available = True
            print(f"[ÁUDIO] Player detectado: {self._player_cmd} — Som de transição ativo.")
        else:
            print("[ÁUDIO] Nenhum player (mpg123/ffplay/vlc) encontrado. Instale com:")
            print("        sudo apt install mpg123   (Ubuntu/Debian)")
            print("        sudo dnf install mpg123   (Fedora)")
            print("        O som será reproduzido pelo navegador.")

    def start_or_continue(self, progress=1.0):
        """Inicia ou mantém a música de fundo tocando durante a rotação."""
        if not self.available:
            return
        if IS_WINDOWS:
            if not self.is_playing:
                self._cmd(f"seek {self.alias} to start")
                self._cmd(f"play {self.alias}")
                self.is_playing = True
            else:
                _, mode = self._cmd(f"status {self.alias} mode")
                if mode == "stopped":
                    self._cmd(f"seek {self.alias} to start")
                    self._cmd(f"play {self.alias}")
        else:
            if not self.is_playing or (self._proc and self._proc.poll() is not None):
                try:
                    if self._player_cmd == "mpg123":
                        self._proc = subprocess.Popen(
                            ["mpg123", "-q", self.audio_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                    elif self._player_cmd == "ffplay":
                        self._proc = subprocess.Popen(
                            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", self.audio_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                    elif self._player_cmd == "vlc":
                        self._proc = subprocess.Popen(
                            ["vlc", "--play-and-exit", "--quiet", self.audio_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                    elif self._player_cmd == "afplay":  # macOS
                        self._proc = subprocess.Popen(
                            ["afplay", self.audio_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                    self.is_playing = True
                except Exception as e:
                    print(f"[ÁUDIO] Erro ao iniciar player: {e}")

    def stop_and_reset(self):
        """Pausa e rebobina a música quando a rotação cessa."""
        if not self.available:
            return
        if IS_WINDOWS:
            if self.is_playing:
                self._cmd(f"stop {self.alias}")
                self._cmd(f"seek {self.alias} to start")
                self.is_playing = False
        else:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1)
                except Exception:
                    self._proc.kill()
            self._proc = None
            self.is_playing = False

    def close(self):
        """Libera o arquivo de áudio no encerramento."""
        if not self.available:
            return
        if IS_WINDOWS:
            self._cmd(f"stop {self.alias}")
            self._cmd(f"close {self.alias}")
        else:
            self.stop_and_reset()
        self.is_playing = False


# ---------------------------------------------------------------------------
# Funções de Controle do Sistema Operacional (Multiplataforma)
# ---------------------------------------------------------------------------

def open_browser_interface():
    """Abre o index.html da feira cultural no navegador padrão."""
    print("\n" + "=" * 65)
    print(" [COMANDO] Gesto 'Joia' detectado e confirmado!")
    print(f" -> Abrindo interface principal: {INDEX_HTML_PATH}")
    print("=" * 65 + "\n")

    try:
        if IS_WINDOWS:
            os.startfile(INDEX_HTML_PATH)
        elif IS_LINUX:
            subprocess.Popen(["xdg-open", f"file://{INDEX_HTML_PATH}"])
        elif IS_MAC:
            subprocess.Popen(["open", INDEX_HTML_PATH])
        else:
            webbrowser.open(f"file://{INDEX_HTML_PATH}")
    except Exception as e:
        print(f"[ERRO] Falha ao abrir navegador: {e}")
        webbrowser.open(f"file://{INDEX_HTML_PATH}")


def open_credits_interface():
    """Abre a página de créditos aos 90° de rotação da mão."""
    print("\n" + "=" * 65)
    print(" [TRANSIÇÃO 90° ATINGIDA] Mão aberta rotacionada para a direita!")
    print(" -> Escurecimento total concluído no front-end.")
    print(f" -> Abrindo página de créditos: {CREDITOS_HTML_PATH}")
    print("=" * 65 + "\n")

    # Notifica via WebSocket para transição imediata no front-end
    broadcast_message({"type": "transition_credits", "url": "creditos.html"})

    # Abre no navegador via SO para garantir exibição
    time.sleep(0.15)
    try:
        if IS_WINDOWS:
            os.startfile(CREDITOS_HTML_PATH)
        elif IS_LINUX:
            subprocess.Popen(["xdg-open", f"file://{CREDITOS_HTML_PATH}"])
        elif IS_MAC:
            subprocess.Popen(["open", CREDITOS_HTML_PATH])
        else:
            webbrowser.open(f"file://{CREDITOS_HTML_PATH}")
    except Exception as e:
        print(f"[ERRO] Falha ao abrir creditos.html: {e}")
        webbrowser.open(f"file://{CREDITOS_HTML_PATH}")


def close_browser_interface():
    """Fecha a janela ou aba do navegador aberta (multiplataforma)."""
    print("\n" + "=" * 65)
    print(" [COMANDO] Gesto 'Dois' detectado e confirmado!")
    print(" -> Fechando janela/aba do navegador...")
    print("=" * 65 + "\n")

    if IS_WINDOWS:
        _close_browser_windows()
    elif IS_LINUX:
        _close_browser_linux()
    elif IS_MAC:
        _close_browser_mac()
    else:
        print("[AVISO] Fechar navegador não suportado nesta plataforma.")


def _close_browser_windows():
    """Fecha o navegador no Windows via EnumWindows + WM_CLOSE."""
    closed = False
    user32 = ctypes.windll.user32

    def enum_windows_callback(hwnd, extra):
        nonlocal closed
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if any(keyword in title for keyword in ["BYTE 3D", "Feira Cultural", "Créditos", "index.html", "creditos.html"]):
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    print(f" -> Janela fechada: '{title}'")
                    closed = True
        return True

    try:
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
    except Exception as e:
        print(f"[AVISO] Busca por janela: {e}")

    if not closed:
        print(" -> Enviando Ctrl+W para fechar aba ativa...")
        time.sleep(0.1)
        user32.keybd_event(0x11, 0, 0, 0)
        user32.keybd_event(0x57, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(0x57, 0, 2, 0)
        user32.keybd_event(0x11, 0, 2, 0)


def _close_browser_linux():
    """Fecha o navegador no Linux via xdotool (se disponível) ou wmctrl."""
    try:
        # Tenta xdotool (mais amplo)
        result = subprocess.run(
            ["xdotool", "search", "--name", "BYTE 3D|Feira Cultural|Creditos"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            wids = result.stdout.strip().split("\n")
            for wid in wids:
                subprocess.run(["xdotool", "windowclose", wid], timeout=2)
            print(f" -> Janela(s) fechada(s) via xdotool.")
            return
    except Exception:
        pass

    try:
        # Fallback: wmctrl
        subprocess.run(["wmctrl", "-c", "BYTE 3D"], timeout=2)
        subprocess.run(["wmctrl", "-c", "Feira Cultural"], timeout=2)
        print(" -> Tentativa de fechar via wmctrl.")
    except Exception:
        print(" -> xdotool/wmctrl não encontrado. Instale com: sudo apt install xdotool")
        print("    Alternativa: feche o navegador manualmente.")


def _close_browser_mac():
    """Fecha o navegador no macOS via AppleScript."""
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to close (every tab whose title contains "BYTE 3D" or title contains "Feira Cultural")'],
            timeout=2
        )
    except Exception:
        try:
            subprocess.run(["osascript", "-e", 'tell application "Safari" to close (every tab whose name contains "BYTE 3D")'], timeout=2)
        except Exception:
            print(" -> Feche o navegador manualmente (macOS).")


# ---------------------------------------------------------------------------
# Inicialização do Rastreador de Mãos MediaPipe (Tasks API / Solutions)
# ---------------------------------------------------------------------------
class HandTracker:
    """Wrapper universal compatível com MediaPipe Tasks API e Solutions."""

    def __init__(self):
        import mediapipe as mp

        self.mp = mp
        self.use_tasks = False
        self.detector = None
        self.solutions_hands = None

        if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
            print("[INFO] Inicializando MediaPipe Hands (Solutions API)...")
            self.mp_hands = mp.solutions.hands
            self.solutions_hands = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.6,
            )
            self.use_tasks = False
        else:
            print("[INFO] Inicializando MediaPipe Tasks HandLandmarker...")
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            model_path = os.path.join(BASE_DIR, "hand_landmarker.task")
            if not os.path.exists(model_path):
                print("[INFO] Baixando modelo oficial hand_landmarker.task...")
                url = (
                    "https://storage.googleapis.com/mediapipe-models/"
                    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
                )
                urllib.request.urlretrieve(url, model_path)
                print("[INFO] Download concluído com sucesso.")

            base_options = python.BaseOptions(model_asset_path=model_path)
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                num_hands=1,
                min_hand_detection_confidence=0.7,
                min_hand_presence_confidence=0.6,
                min_tracking_confidence=0.6,
            )
            self.detector = vision.HandLandmarker.create_from_options(options)
            self.use_tasks = True

        self.HAND_CONNECTIONS = [
            (0, 1), (1, 2), (2, 3), (3, 4),
            (0, 5), (5, 6), (6, 7), (7, 8),
            (5, 9), (9, 10), (10, 11), (11, 12),
            (9, 13), (13, 14), (14, 15), (15, 16),
            (13, 17), (17, 18), (18, 19), (19, 20),
            (0, 17)
        ]

    def process(self, rgb_frame):
        if self.use_tasks:
            mp_image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb_frame)
            result = self.detector.detect(mp_image)
            if result.hand_landmarks and len(result.hand_landmarks) > 0:
                return result.hand_landmarks[0]
            return None
        else:
            results = self.solutions_hands.process(rgb_frame)
            if results.multi_hand_landmarks:
                return results.multi_hand_landmarks[0].landmark
            return None

    def draw_landmarks(self, frame, landmarks, is_open=False):
        h, w, _ = frame.shape
        coords = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]

        line_color = (200, 100, 240) if is_open else (70, 210, 120)
        for p1, p2 in self.HAND_CONNECTIONS:
            cv2.line(frame, coords[p1], coords[p2], line_color, 2, cv2.LINE_AA)

        for idx, (cx, cy) in enumerate(coords):
            if idx in [4, 8, 12, 16, 20]:
                cv2.circle(frame, (cx, cy), 7, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(frame, (cx, cy), 5, (230, 80, 50), -1, cv2.LINE_AA)
            else:
                cv2.circle(frame, (cx, cy), 4, (40, 120, 240), -1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Geometria e Rotação da Mão
# ---------------------------------------------------------------------------
def _dist(p1, p2):
    """Distância euclidiana 2D normalizada."""
    return math.hypot(p1.x - p2.x, p1.y - p2.y)


def check_is_hand_open(landmarks):
    """
    Verifica se a mão está ABERTA (cinco dedos estendidos).
    Utiliza distâncias radiais relativas ao pulso para ser invariante à rotação da mão.
    """
    wrist = landmarks[0]

    index_open = _dist(landmarks[8], wrist) > _dist(landmarks[6], wrist) * 1.15
    middle_open = _dist(landmarks[12], wrist) > _dist(landmarks[10], wrist) * 1.15
    ring_open = _dist(landmarks[16], wrist) > _dist(landmarks[14], wrist) * 1.15
    pinky_open = _dist(landmarks[20], wrist) > _dist(landmarks[18], wrist) * 1.15

    thumb_open = (
        _dist(landmarks[4], wrist) > _dist(landmarks[2], wrist) * 1.12
        and _dist(landmarks[4], landmarks[17]) > _dist(landmarks[2], landmarks[17])
    )

    return index_open and middle_open and ring_open and pinky_open and thumb_open


def calculate_clockwise_rotation(landmarks):
    """
    Calcula o ângulo de rotação no sentido horário (para a direita) em relação à vertical (0° a 90°).
    Vetor: pulso (landmark 0) -> base do dedo médio (landmark 9).
    """
    wrist = landmarks[0]
    middle_mcp = landmarks[9]

    dx = middle_mcp.x - wrist.x
    dy = middle_mcp.y - wrist.y

    raw_angle = math.degrees(math.atan2(dx, -dy))

    if raw_angle < -8.0:
        angle = 0.0
    elif raw_angle < 0.0:
        angle = 0.0
    else:
        angle = min(raw_angle, ROTATION_TARGET_ANGLE)

    progress = angle / ROTATION_TARGET_ANGLE
    return angle, progress


def classify_gesture(landmarks):
    """Classifica 'joia', 'dois' ou 'desconhecido' quando a mão não está aberta."""
    if not landmarks or len(landmarks) < 21:
        return "nenhum"

    wrist = landmarks[0]
    thumb_mcp = landmarks[2]
    thumb_ip = landmarks[3]
    thumb_tip = landmarks[4]

    index_mcp = landmarks[5]
    index_pip = landmarks[6]
    index_tip = landmarks[8]

    middle_mcp = landmarks[9]
    middle_pip = landmarks[10]
    middle_tip = landmarks[12]

    ring_pip = landmarks[14]
    ring_tip = landmarks[16]

    pinky_pip = landmarks[18]
    pinky_tip = landmarks[20]

    index_extended = (index_tip.y < index_pip.y < index_mcp.y)
    middle_extended = (middle_tip.y < middle_pip.y < middle_mcp.y)
    ring_extended = (ring_tip.y < ring_pip.y)
    pinky_extended = (pinky_tip.y < pinky_pip.y)

    thumb_pointing_up = (thumb_tip.y < thumb_ip.y < thumb_mcp.y)
    thumb_above_fingers = (thumb_tip.y < index_mcp.y - 0.04)
    other_fingers_closed = (
        not index_extended
        and not middle_extended
        and not ring_extended
        and not pinky_extended
        and (index_tip.y > index_mcp.y - 0.02)
        and (middle_tip.y > middle_mcp.y - 0.02)
    )

    if thumb_pointing_up and thumb_above_fingers and other_fingers_closed:
        return "joia"

    two_fingers_up = (
        index_extended
        and middle_extended
        and not ring_extended
        and not pinky_extended
    )
    thumb_not_up = (thumb_tip.y > index_pip.y or abs(thumb_tip.x - index_mcp.x) < 0.12)

    if two_fingers_up and thumb_not_up:
        return "dois"

    return "desconhecido"


# ---------------------------------------------------------------------------
# Renderização do HUD no OpenCV
# ---------------------------------------------------------------------------
def draw_hud(frame, is_hand_open, angle, progress, detected_gesture, consecutive_count, required_count, in_cooldown, cooldown_remaining):
    h, w, _ = frame.shape

    header_h = 80
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, header_h), COLOR_BG_HUD, -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)

    cv2.putText(
        frame,
        "SISTEMA DE GESTOS - FEIRA CULTURAL TI",
        (18, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        COLOR_TEXT_WHITE,
        2,
        cv2.LINE_AA,
    )

    if in_cooldown:
        status_text = f"Transicao executada! Aguardando ({cooldown_remaining:.1f}s)..."
        status_color = COLOR_ACCENT_YELLOW
    elif is_hand_open:
        audio_tag = " [AUDIO ATIVO]" if angle > 4.0 else ""
        status_text = f"MAO ABERTA: Rotacao {angle:.1f} / {ROTATION_TARGET_ANGLE:.0f}{audio_tag}  ({int(progress*100)}% escurecido)"
        status_color = COLOR_ACCENT_PURPLE if angle < ROTATION_TARGET_ANGLE else COLOR_ACCENT_GREEN
    elif detected_gesture == "joia":
        pct = int((consecutive_count / required_count) * 100)
        status_text = f"Gesto: POLEGAR PARA CIMA (Joia) - {pct}%"
        status_color = COLOR_ACCENT_GREEN
    elif detected_gesture == "dois":
        pct = int((consecutive_count / required_count) * 100)
        status_text = f"Gesto: DOIS DEDOS (Fechar) - {pct}%"
        status_color = COLOR_ACCENT_RED
    elif detected_gesture == "desconhecido":
        status_text = "Mao detectada (posicione ou gire a mao aberta)"
        status_color = COLOR_TEXT_MUTED
    else:
        status_text = "Aguardando mao em frente a camera..."
        status_color = COLOR_TEXT_MUTED

    cv2.putText(
        frame,
        status_text,
        (18, 56),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        status_color,
        2,
        cv2.LINE_AA,
    )

    bar_x, bar_y = 18, 68
    bar_w, bar_h = w - 36, 5
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (55, 55, 65), -1)

    if is_hand_open and not in_cooldown:
        fill_w = int(bar_w * progress)
        color = COLOR_ACCENT_GREEN if angle >= ROTATION_TARGET_ANGLE else COLOR_ACCENT_PURPLE
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), color, -1)
    elif detected_gesture in ["joia", "dois"] and not in_cooldown:
        ratio = min(consecutive_count / required_count, 1.0)
        fill_w = int(bar_w * ratio)
        color = COLOR_ACCENT_GREEN if detected_gesture == "joia" else COLOR_ACCENT_RED
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), color, -1)

    footer_h = 42
    footer_y = h - footer_h
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, footer_y), (w, h), COLOR_BG_HUD, -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)

    guide_text = "Mao Aberta + Girar 90: Creditos  |  Joia: Abrir BYTE  |  Dois: Fechar  |  Q: Sair"
    cv2.putText(
        frame,
        guide_text,
        (18, footer_y + 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.44,
        COLOR_TEXT_WHITE,
        1,
        cv2.LINE_AA,
    )


# ---------------------------------------------------------------------------
# Loop Principal do Sistema
# ---------------------------------------------------------------------------
def main():
    print("\n" + "=" * 68)
    print(" SISTEMA DE VISÃO COMPUTACIONAL E CONTROLE POR GESTOS")
    print(" Feira Cultural de TI · Rastreamento de Mão e Rotação")
    print(f" Plataforma: {'Windows' if IS_WINDOWS else 'Linux' if IS_LINUX else 'macOS' if IS_MAC else sys.platform}")
    print("=" * 68)
    print(" [*] Gire a mão aberta no sentido horário de 0° a 90°")
    print("     -> Música de fundo toca durante a rotação (Crescendo Reverse)")
    print("     -> Escurece o index.html e aos 90° abre creditos.html")
    print(" [*] Gesto 'Joia' (Polegar para cima) -> Abre index.html")
    print(" [*] Gesto 'Dois' (Dois dedos)       -> Fecha a janela aberta")
    print(" [*] Pressione 'Q' ou 'ESC' para sair do sistema.")
    print("=" * 68 + "\n")

    # Inicia o servidor WebSocket local
    start_websocket_server(host="127.0.0.1", port=8765)

    # Inicializa gerenciador de áudio nativo de transição
    sfx_manager = TransitionSoundManager(TRANSITION_AUDIO_PATH)

    # Inicializa rastreador e câmera
    tracker = HandTracker()
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERRO] Não foi possível acessar a webcam. Verifique a conexão da câmera.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # Variáveis de estado e debouncing
    consecutive_frames = 0
    last_detected_gesture = "nenhum"

    rotation_consecutive_trigger = 0
    last_rotation_action_timestamp = 0.0

    last_broadcast_angle = -1.0
    last_terminal_log_timestamp = 0.0

    print("[INFO] Câmera e rastreamento ativos. Janela de visualização aberta.\n")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[AVISO] Falha ao capturar frame da câmera.")
                break

            frame = cv2.flip(frame, 1)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            landmarks = tracker.process(rgb_frame)

            is_open = False
            rotation_angle = 0.0
            rotation_progress = 0.0
            current_gesture = "nenhum"

            current_time = time.time()
            time_since_rotation_action = current_time - last_rotation_action_timestamp
            in_rotation_cooldown = time_since_rotation_action < ROTATION_COOLDOWN_SECONDS
            rotation_cooldown_rem = max(0.0, ROTATION_COOLDOWN_SECONDS - time_since_rotation_action)

            if landmarks:
                is_open = check_is_hand_open(landmarks)
                tracker.draw_landmarks(frame, landmarks, is_open=is_open)

                if is_open:
                    rotation_angle, rotation_progress = calculate_clockwise_rotation(landmarks)

                    if rotation_angle > 4.0:
                        sfx_manager.start_or_continue(rotation_progress)
                    else:
                        sfx_manager.stop_and_reset()

                    if abs(rotation_angle - last_broadcast_angle) > 0.5:
                        broadcast_message({
                            "type": "rotation",
                            "angle": round(rotation_angle, 1),
                            "progress": round(rotation_progress, 3),
                            "sound_handled_by_backend": sfx_manager.available,
                        })
                        last_broadcast_angle = rotation_angle

                    if current_time - last_terminal_log_timestamp > 0.4 and rotation_angle > 5.0:
                        pct = int(rotation_progress * 100)
                        print(f"[ROTAÇÃO MÃO ABERTA] Ângulo: {rotation_angle:5.1f}° / {ROTATION_TARGET_ANGLE:.0f}° | Escurecimento: {pct:3d}%")
                        last_terminal_log_timestamp = current_time

                    if not in_rotation_cooldown:
                        if rotation_angle >= ROTATION_TARGET_ANGLE:
                            rotation_consecutive_trigger += 1
                            if rotation_consecutive_trigger >= ROTATION_TRIGGER_FRAMES:
                                open_credits_interface()
                                last_rotation_action_timestamp = time.time()
                                rotation_consecutive_trigger = 0
                        else:
                            rotation_consecutive_trigger = 0
                else:
                    sfx_manager.stop_and_reset()
                    if last_broadcast_angle > 0.0:
                        broadcast_message({
                            "type": "rotation",
                            "angle": 0.0,
                            "progress": 0.0,
                            "sound_handled_by_backend": sfx_manager.available,
                        })
                        last_broadcast_angle = 0.0

                    current_gesture = classify_gesture(landmarks)
                    rotation_consecutive_trigger = 0
            else:
                sfx_manager.stop_and_reset()
                if last_broadcast_angle > 0.0:
                    broadcast_message({
                        "type": "rotation",
                        "angle": 0.0,
                        "progress": 0.0,
                        "sound_handled_by_backend": sfx_manager.available,
                    })
                    last_broadcast_angle = 0.0
                rotation_consecutive_trigger = 0

            # Debouncing para Gestos 'Joia' e 'Dois'
            if not in_rotation_cooldown:
                if current_gesture in ["joia", "dois"]:
                    if current_gesture == last_detected_gesture:
                        consecutive_frames += 1
                    else:
                        consecutive_frames = 1
                        last_detected_gesture = current_gesture
                        print(f"[RECONHECENDO] Sustentando gesto: '{current_gesture}'...")

                    if consecutive_frames >= REQUIRED_CONSECUTIVE_FRAMES:
                        if current_gesture == "joia":
                            open_browser_interface()
                        elif current_gesture == "dois":
                            close_browser_interface()

                        last_rotation_action_timestamp = time.time()
                        consecutive_frames = 0
                        last_detected_gesture = "nenhum"
                else:
                    consecutive_frames = 0
                    last_detected_gesture = "nenhum"
            else:
                consecutive_frames = 0
                last_detected_gesture = "nenhum"

            draw_hud(
                frame,
                is_open,
                rotation_angle,
                rotation_progress,
                current_gesture,
                consecutive_frames,
                REQUIRED_CONSECUTIVE_FRAMES,
                in_rotation_cooldown,
                rotation_cooldown_rem,
            )

            cv2.imshow("Controle por Gestos e Rotacao - Feira Cultural TI", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == ord("Q") or key == 27:
                print("\n[INFO] Encerrando sistema a pedido do usuário...")
                break

    except KeyboardInterrupt:
        print("\n[INFO] Interrupção detectada.")
    finally:
        sfx_manager.close()
        broadcast_message({
            "type": "rotation",
            "angle": 0.0,
            "progress": 0.0,
            "sound_handled_by_backend": False,
        })
        cap.release()
        cv2.destroyAllWindows()
        print("[INFO] Câmera, áudio e janelas liberadas com sucesso. Sistema finalizado.")


if __name__ == "__main__":
    main()
