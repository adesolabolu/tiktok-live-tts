import sys
import os
import re
import json
import multiprocessing

multiprocessing.freeze_support()

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import uvicorn
import uvicorn.config
import uvicorn.main
import uvicorn.logging
import uvicorn.loops
import uvicorn.loops.auto
import uvicorn.protocols
import uvicorn.protocols.http
import uvicorn.protocols.http.auto
import uvicorn.protocols.http.h11_impl
import uvicorn.protocols.websockets
import uvicorn.protocols.websockets.auto
import uvicorn.protocols.websockets.websockets_impl
import uvicorn.lifespan
import uvicorn.lifespan.on
import uvicorn.lifespan.off

import asyncio
import base64
import time
import uuid
import socket
import threading
import tempfile
import zipfile
import shutil
import subprocess
import httpx
import urllib.request
from typing import Optional, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

CURRENT_VERSION = "1.9.9"
GITHUB_REPO = "adesolabolu/tiktok-live-tts"
DEFAULT_PORT = 28730
active_port: int = DEFAULT_PORT

# Determine config and asset file location
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, '_MEIPASS', BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR

def _resolve_data_dir() -> str:
    # MSIX installs into read-only WindowsApps; keep user config & voices in LocalAppData.
    if getattr(sys, "frozen", False) and "WindowsApps" in BASE_DIR:
        return os.path.join(os.environ.get("LOCALAPPDATA", BASE_DIR), "TTSLiveStudio")
    try:
        test_path = os.path.join(BASE_DIR, ".write_test")
        with open(test_path, "w") as f:
            f.write("")
        os.remove(test_path)
        return BASE_DIR
    except OSError:
        return os.path.join(os.environ.get("LOCALAPPDATA", BASE_DIR), "TTSLiveStudio")

DATA_DIR = _resolve_data_dir()
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
VOICES_DIR = os.path.join(DATA_DIR, "voices")
os.makedirs(VOICES_DIR, exist_ok=True)

def get_piper_executable() -> Optional[str]:
    candidates = [
        os.path.join(DATA_DIR, "bin", "piper", "piper.exe"),
        os.path.join(BASE_DIR, "bin", "piper", "piper.exe"),
        os.path.join(BUNDLE_DIR, "bin", "piper", "piper.exe"),
        os.path.join(os.path.dirname(sys.executable), "bin", "piper", "piper.exe"),
        os.path.join(BASE_DIR, "piper", "piper.exe"),
        shutil.which("piper")
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.path.isfile(c):
            return c
    return None

def ensure_piper_engine() -> bool:
    exe = get_piper_executable()
    if exe and os.path.exists(exe):
        return True
    dest_dir = os.path.join(DATA_DIR, "bin", "piper")
    os.makedirs(dest_dir, exist_ok=True)
    zip_url = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
    try:
        req = urllib.request.Request(zip_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.infolist():
                fn = member.filename
                if fn.startswith("piper/"):
                    fn = fn[6:]
                if not fn: continue
                target = os.path.join(dest_dir, fn)
                if member.is_dir():
                    os.makedirs(target, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as f:
                        f.write(z.read(member))
        return os.path.exists(os.path.join(dest_dir, "piper.exe"))
    except Exception as e:
        print(f"Failed to ensure piper engine: {e}")
        return False

PIPER_VOICE_CATALOG = {
    "nova": {
        "id": "nova",
        "name": "Nova",
        "subtitle": "High-Energy Anime Female",
        "badge": "Anime / Hype",
        "category": "gaming",
        "badgeStyle": "background: rgba(236, 72, 153, 0.15); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3);",
        "desc": "Expressive, cheerful, and fast-paced. Perfect for hype gaming and interactive chat reactions.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/amy/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/low/en_US-amy-low.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/low/en_US-amy-low.onnx.json"
    },
    "kael": {
        "id": "kael",
        "name": "Kael",
        "subtitle": "Deep FM Radio Announcer",
        "badge": "Deep / Radio",
        "category": "deep",
        "badgeStyle": "background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3);",
        "desc": "Resonant, bass-heavy broadcast DJ voice. Ideal for chill late-night talk streams and podcasting.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/bryce/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/bryce/medium/en_US-bryce-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/bryce/medium/en_US-bryce-medium.onnx.json"
    },
    "arthur": {
        "id": "arthur",
        "name": "Arthur",
        "subtitle": "Distinguished British Butler",
        "badge": "British / Formal",
        "category": "accents",
        "badgeStyle": "background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3);",
        "desc": "Polite, crisp UK English with formal tone. Reads chat comments with butler-like elegance.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_GB/alan/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx.json"
    },
    "viper": {
        "id": "viper",
        "name": "Viper",
        "subtitle": "Esports Shoutcaster",
        "badge": "Gaming / FPS",
        "category": "gaming",
        "badgeStyle": "background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);",
        "desc": "Fast, hype tournament commentator style. Built for high-kill FPS and battle royale streams.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/ryan/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/low/en_US-ryan-low.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/low/en_US-ryan-low.onnx.json"
    },
    "luna": {
        "id": "luna",
        "name": "Luna",
        "subtitle": "Calm & Cozy Storyteller",
        "badge": "Cozy / ASMR",
        "category": "chill",
        "badgeStyle": "background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3);",
        "desc": "Soft, gentle, relaxing voice. Ideal for art streams, cozy farming games, and quiet evening streams.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/kathleen/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/kathleen/low/en_US-kathleen-low.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/kathleen/low/en_US-kathleen-low.onnx.json"
    },
    "thor": {
        "id": "thor",
        "name": "Thor",
        "subtitle": "Nordic Warrior / Northern Male",
        "badge": "Fantasy / Epic",
        "category": "accents",
        "badgeStyle": "background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3);",
        "desc": "Thunderous, roaring, epic character. Turns simple chat messages into battle declarations.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_GB/northern_english_male/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium.onnx.json"
    },
    "danny": {
        "id": "danny",
        "name": "Danny",
        "subtitle": "Gamer / Teen Hype",
        "badge": "US / Teen Hype",
        "category": "gaming",
        "badgeStyle": "background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.3);",
        "desc": "Youthful, energetic US English voice. Awesome for gaming banter, fast-paced stream hype, and jokes.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/danny/low/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/danny/low/en_US-danny-low.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/danny/low/en_US-danny-low.onnx.json"
    },
    "lessac": {
        "id": "lessac",
        "name": "Lessac",
        "subtitle": "Studio Narrator / Pro Audiobook",
        "badge": "US / Studio Clear",
        "category": "chill",
        "badgeStyle": "background: rgba(14, 165, 233, 0.15); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.3);",
        "desc": "Pristine, neutral, studio-grade narration voice. Flawlessly clear pronunciation for reading long questions and viewer tips.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/lessac/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low/en_US-lessac-low.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low/en_US-lessac-low.onnx.json"
    },
    "joe": {
        "id": "joe",
        "name": "Joe",
        "subtitle": "Chill Streamer / Casual Male",
        "badge": "US / Casual Chill",
        "category": "chill",
        "badgeStyle": "background: rgba(139, 92, 246, 0.15); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.3);",
        "desc": "Laid-back, conversational everyday guy. Feels like a stream co-host chatting on Discord.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/joe/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/joe/medium/en_US-joe-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/joe/medium/en_US-joe-medium.onnx.json"
    },
    "kristin": {
        "id": "kristin",
        "name": "Kristin",
        "subtitle": "Warm & Cheerful Female",
        "badge": "US / Warm & Friendly",
        "category": "warm",
        "badgeStyle": "background: rgba(236, 72, 153, 0.15); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3);",
        "desc": "Friendly, inviting, and upbeat female voice. Great for welcome greetings and donor thank-yous.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/kristin/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/kristin/medium/en_US-kristin-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/kristin/medium/en_US-kristin-medium.onnx.json"
    },
    "mike": {
        "id": "mike",
        "name": "Mike",
        "subtitle": "Deep Baritone / Esports Caster",
        "badge": "US / Deep Caster",
        "category": "deep",
        "badgeStyle": "background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3);",
        "desc": "Deep, authoritative, cinematic male baritone. Gives substantial punch and weight to stream commentary.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_US/mike/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/mike/medium/en_US-mike-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/mike/medium/en_US-mike-medium.onnx.json"
    },
    "alba": {
        "id": "alba",
        "name": "Alba",
        "subtitle": "Scottish Storyteller Female",
        "badge": "Scottish / Character",
        "category": "accents",
        "badgeStyle": "background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3);",
        "desc": "Distinctive Scottish accent with lyrical warmth and charm. Captivating character voice for roleplay and storytelling.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_GB/alba/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json"
    },
    "cori": {
        "id": "cori",
        "name": "Cori",
        "subtitle": "British Queen's English Female",
        "badge": "UK / Royal Eloquent",
        "category": "accents",
        "badgeStyle": "background: rgba(6, 182, 212, 0.15); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.3);",
        "desc": "Crisp, pristine Received Pronunciation British female. Highly articulate, elegant, and sophisticated.",
        "sampleUrl": "https://rhasspy.github.io/piper-samples/samples/en/en_GB/cori/medium/speaker_0.mp3",
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/medium/en_GB-cori-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/medium/en_GB-cori-medium.onnx.json"
    }
}

def download_piper_voice(voice_id: str) -> bool:
    v = PIPER_VOICE_CATALOG.get(voice_id)
    if not v:
        return False
    target_dir = os.path.join(VOICES_DIR, voice_id)
    os.makedirs(target_dir, exist_ok=True)
    onnx_dest = os.path.join(target_dir, f"{voice_id}.onnx")
    json_dest = os.path.join(target_dir, f"{voice_id}.onnx.json")

    try:
        req = urllib.request.Request(v["json_url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(json_dest, "wb") as f:
            f.write(resp.read())

        req = urllib.request.Request(v["onnx_url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(onnx_dest, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk: break
                f.write(chunk)
        return os.path.exists(onnx_dest) and os.path.getsize(onnx_dest) > 1000000
    except Exception as e:
        print(f"Error downloading voice {voice_id}: {e}")
        return False

def synthesize_piper(voice_id: str, text: str) -> Optional[str]:
    piper_exe = get_piper_executable()
    if not piper_exe or not os.path.exists(piper_exe):
        return None
    model_path = os.path.join(VOICES_DIR, voice_id, f"{voice_id}.onnx")
    if not os.path.exists(model_path):
        return None

    piper_dir = os.path.dirname(piper_exe)
    espeak_data = os.path.join(piper_dir, "espeak-ng-data")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        out_wav = tf.name

    try:
        args = [
            piper_exe,
            "--model", model_path,
            "--output_file", out_wav
        ]
        if os.path.exists(espeak_data):
            args.extend(["--espeak_data", espeak_data])

        pinfo = subprocess.STARTUPINFO()
        pinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        pinfo.wShowWindow = 0 # SW_HIDE

        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=piper_dir,
            startupinfo=pinfo,
            creationflags=0x08000000
        )
        proc.communicate(input=text.encode("utf-8"), timeout=10)

        if os.path.exists(out_wav) and os.path.getsize(out_wav) > 1000:
            with open(out_wav, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        print(f"Piper synthesis error: {e}")
    finally:
        if os.path.exists(out_wav):
            try: os.remove(out_wav)
            except Exception: pass
    return None

DEFAULT_CONFIG = {
    "username": "",
    "engine": "instant",
    "voice": "en-US-JennyNeural",
    "native_voice_name": "",
    "audio_device_id": "default",
    "installed_voices": [],
    "volume": 1.0,
    "cooldown": 5,
    "max_chars": 120,
    "banned_words": "",
    "role_filter": "anyone",       # "anyone", "followers", "subs", "fan_club"
    "min_fan_level": 0,            # 0 = any, or 1, 5, 10...
    "fan_announcements_enabled": True,
    "gift_tts_enabled": True,
    "gift_sound_enabled": True,
    "gift_min_coins": 1,
    "spam_auto_mute": True,
    "command_prefix": "",
    "starred_voices": []
}

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg = dict(DEFAULT_CONFIG)
                cfg.update(saved)
                return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

initial_cfg = load_config()

app = FastAPI(title="TTS Live Studio", version=CURRENT_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AppState:
    def __init__(self, cfg: dict):
        self.username: str = cfg.get("username", "")
        self.client: Optional[Any] = None
        self.task: Optional[asyncio.Task] = None
        self.status: str = "disconnected"
        self.status_msg: str = "Ready to connect"
        self.engine: str = cfg.get("engine", "instant")
        self.voice: str = cfg.get("voice", "en-US-JennyNeural")
        self.native_voice_name: str = cfg.get("native_voice_name", "")
        self.audio_device_id: str = cfg.get("audio_device_id", "default")
        self.installed_voices: list[str] = cfg.get("installed_voices", [])
        self.volume: float = cfg.get("volume", 1.0)
        self.cooldown: int = cfg.get("cooldown", 5)
        self.max_chars: int = cfg.get("max_chars", 120)
        self.banned_words: list[str] = [w.strip() for w in cfg.get("banned_words", "").split(",") if w.strip()]
        self.banned_words_raw: str = cfg.get("banned_words", "")
        
        # Audience & Gating Controls
        self.role_filter: str = cfg.get("role_filter", "anyone")
        self.min_fan_level: int = cfg.get("min_fan_level", 0)
        self.fan_announcements_enabled: bool = cfg.get("fan_announcements_enabled", True)
        self.gift_tts_enabled: bool = cfg.get("gift_tts_enabled", True)
        self.gift_sound_enabled: bool = cfg.get("gift_sound_enabled", True)
        self.gift_min_coins: int = cfg.get("gift_min_coins", 1)
        self.spam_auto_mute: bool = cfg.get("spam_auto_mute", True)
        self.command_prefix: str = cfg.get("command_prefix", "")
        self.starred_voices: list[str] = cfg.get("starred_voices", [])

        self.tts_queue: asyncio.Queue = asyncio.Queue()
        self.user_last_seen: dict[str, float] = {}
        self.user_msg_history: dict[str, list[float]] = {}
        self.user_muted_until: dict[str, float] = {}
        self.websockets: set[WebSocket] = set()
        self.current_speaking: Optional[dict] = None

    def export_config(self) -> dict:
        return {
            "username": self.username,
            "engine": self.engine,
            "voice": self.voice,
            "native_voice_name": self.native_voice_name,
            "audio_device_id": self.audio_device_id,
            "installed_voices": self.installed_voices,
            "volume": self.volume,
            "cooldown": self.cooldown,
            "max_chars": self.max_chars,
            "banned_words": self.banned_words_raw,
            "role_filter": self.role_filter,
            "min_fan_level": self.min_fan_level,
            "fan_announcements_enabled": self.fan_announcements_enabled,
            "gift_tts_enabled": self.gift_tts_enabled,
            "gift_sound_enabled": self.gift_sound_enabled,
            "gift_min_coins": self.gift_min_coins,
            "spam_auto_mute": self.spam_auto_mute,
            "command_prefix": self.command_prefix,
            "starred_voices": self.starred_voices
        }

state = AppState(initial_cfg)

class ConnectRequest(BaseModel):
    username: str

class SpeakRequest(BaseModel):
    text: str
    engine: Optional[str] = None
    voice: Optional[str] = None

class SettingsRequest(BaseModel):
    engine: Optional[str] = None
    voice: Optional[str] = None
    native_voice_name: Optional[str] = None
    audio_device_id: Optional[str] = None
    installed_voices: Optional[list[str]] = None
    volume: Optional[float] = None
    cooldown: Optional[int] = None
    max_chars: Optional[int] = None
    banned_words: Optional[str] = None
    role_filter: Optional[str] = None
    min_fan_level: Optional[int] = None
    fan_announcements_enabled: Optional[bool] = None
    gift_tts_enabled: Optional[bool] = None
    gift_sound_enabled: Optional[bool] = None
    gift_min_coins: Optional[int] = None
    spam_auto_mute: Optional[bool] = None
    command_prefix: Optional[str] = None
    starred_voices: Optional[list[str]] = None

async def broadcast(data: dict):
    dead = set()
    for ws in list(state.websockets):
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    state.websockets.difference_update(dead)

def extract_user_status(target) -> tuple[int, bool, bool]:
    """
    Extracts (fan_level, is_follower, is_sub) across TikTokLive v3 event structures,
    protobuf badge lists, user_identity, and legacy user fields.
    """
    if hasattr(target, 'user'):
        user = target.user
        identity = getattr(target, 'user_identity', None)
        event = target
    else:
        user = target
        identity = getattr(target, 'user_identity', None)
        event = None

    # --- 1. Fan Level Extraction ---
    fan_level = 0
    badges = getattr(user, 'badge_list', None) or getattr(user, 'badges', None) or []
    for b in badges:
        st = str(getattr(b, 'scene_type', '') or getattr(b, 'badge_scene', '')).upper()
        if 'FANS' in st:
            ple = getattr(b, 'privilege_log_extra', None) or getattr(b, 'log_extra', None)
            if ple and hasattr(ple, 'level'):
                try:
                    lvl = int(ple.level)
                    if lvl > fan_level:
                        fan_level = lvl
                except (ValueError, TypeError):
                    pass

    if fan_level == 0 and hasattr(user, 'member_level') and user.member_level:
        try:
            lvl = int(user.member_level)
            if lvl > fan_level:
                fan_level = lvl
        except (ValueError, TypeError):
            pass

    if hasattr(user, 'fans_club') and user.fans_club:
        fc_data = getattr(user.fans_club, 'data', None)
        if fc_data and hasattr(fc_data, 'level'):
            try:
                lvl = int(fc_data.level)
                if lvl > fan_level:
                    fan_level = lvl
            except (ValueError, TypeError):
                pass
        prefer_data = getattr(user.fans_club, 'prefer_data', None)
        if isinstance(prefer_data, dict):
            for fd in prefer_data.values():
                lvl = getattr(fd, 'level', 0)
                if lvl > fan_level:
                    fan_level = lvl

    if hasattr(user, 'fans_club_info') and user.fans_club_info:
        lvl = getattr(user.fans_club_info, 'fans_level', 0)
        if lvl > fan_level:
            fan_level = lvl

    # --- 2. Subscriber Check ---
    is_sub = False
    if identity and getattr(identity, 'is_subscriber_of_anchor', False):
        is_sub = True
    elif event and getattr(event, 'user_is_super_fan', False):
        is_sub = True
    elif hasattr(user, 'subscribe_info') and user.subscribe_info:
        if getattr(user.subscribe_info, 'is_subscribe', False) or getattr(user.subscribe_info, 'is_subscribed_to_anchor', False):
            is_sub = True
    elif getattr(user, 'is_subscribe', False):
        is_sub = True
    else:
        for b in badges:
            st = str(getattr(b, 'scene_type', '') or getattr(b, 'badge_scene', '')).upper()
            if 'SUB' in st:
                is_sub = True
                break

    # --- 3. Follower Check ---
    is_follower = False
    if identity and (getattr(identity, 'is_follower_of_anchor', False) or getattr(identity, 'is_mutual_following_with_anchor', False) or getattr(identity, 'is_anchor', False) or getattr(identity, 'is_moderator_of_anchor', False)):
        is_follower = True
    elif hasattr(user, 'follow_info') and user.follow_info:
        if getattr(user.follow_info, 'follow_status', 0) >= 1:
            is_follower = True
    elif getattr(user, 'follow_status', 0) >= 1:
        is_follower = True
    elif getattr(user, 'is_follower', False) or getattr(user, 'is_friend', False):
        is_follower = True
    elif is_sub or fan_level > 0:
        is_follower = True

    return fan_level, is_follower, is_sub

EMOJI_PATTERN = re.compile(
    '['
    '\U0001F600-\U0001F64F'  # emoticons
    '\U0001F300-\U0001F5FF'  # symbols & pictographs
    '\U0001F680-\U0001F6FF'  # transport & map symbols
    '\U0001F1E0-\U0001F1FF'  # flags
    '\U00002702-\U000027B0'  # dingbats
    '\U000024C2-\U0001F251'  # enclosed chars
    '\U0001F900-\U0001F9FF'  # supplemental symbols & pictographs
    '\U0001FA70-\U0001FAFF'  # symbols & pictographs ext-a
    '\U00002600-\U000026FF'  # misc symbols
    '\U00002B00-\U00002BFF'  # misc symbols & arrows
    '\U0000200D'             # zero width joiner
    '\U0000FE0F'             # variation selector
    ']+', flags=re.UNICODE
)

def strip_emojis(text: str) -> str:
    """Completely remove all unicode emojis from speech string."""
    if not text:
        return ""
    return EMOJI_PATTERN.sub('', text).strip()

def clean_speech_username(raw_name: str) -> str:
    """
    Extract clean English alphanumeric characters from user nickname for TTS.
    Strips decorative symbols, crosses, wings, katakana/kanji glyphs, and emojis.
    If name has no English letters or is unpronounceable, returns empty string so TTS omits it.
    """
    if not raw_name:
        return ""
    no_emoji = strip_emojis(raw_name)
    # Strip special symbols, accents, runes, wingdings: keep only standard a-z, A-Z, 0-9, and spaces
    clean = re.sub(r'[^a-zA-Z0-9 ]+', '', no_emoji)
    clean = re.sub(r'\s+', ' ', clean).strip()
    # If fewer than 2 letters, TTS will struggle with weird phonemes or random noise: omit the name
    letters = re.findall(r'[a-zA-Z]', clean)
    if len(letters) < 2:
        return ""
    return clean

def check_filters(target, text: str) -> tuple[bool, str, int]:
    now = time.time()
    user = getattr(target, 'user', target)
    user_id = getattr(user, 'unique_id', str(getattr(user, 'id', 'user')))
    clean_text = text.strip()

    # 0. Emoji-only / No speech text check
    # Skip totally if comment only contains emojis, punctuation, or no readable alphanumeric words
    text_without_emojis = strip_emojis(clean_text)
    if not re.search(r'[a-zA-Z0-9]', text_without_emojis):
        return False, "Emoji only / no speech text", 0

    # 1. Command Prefix Trigger Check (Options: '.', '/', '!')
    if state.command_prefix and state.command_prefix in [".", "/", "!"]:
        if not clean_text.startswith(state.command_prefix):
            return False, f"Requires prefix '{state.command_prefix}'", 0
        clean_text = clean_text[len(state.command_prefix):].strip()
        if not clean_text:
            return False, "Empty message after prefix", 0
        if not re.search(r'[a-zA-Z0-9]', strip_emojis(clean_text)):
            return False, "Emoji only / no speech text", 0
    
    # 2. Spam Auto-Mute Check (3+ messages in 10s = 30s mute)
    if state.spam_auto_mute:
        mute_until = state.user_muted_until.get(user_id, 0)
        if now < mute_until:
            rem = int(mute_until - now)
            return False, f"Auto-muted for spam ({rem}s left)", 0
            
        history = state.user_msg_history.setdefault(user_id, [])
        history = [t for t in history if (now - t) < 10.0]
        if len(history) >= 3:
            state.user_muted_until[user_id] = now + 30.0
            return False, "Auto-muted 30s (rapid spam)", 0
        history.append(now)
        state.user_msg_history[user_id] = history

    # 3. Fan Club & Role Filter Check
    fan_level, is_follower, is_sub = extract_user_status(target)

    if state.role_filter == "followers" and not is_follower:
        return False, "Followers only", fan_level
    if state.role_filter == "subs" and not is_sub:
        return False, "Subscribers only", fan_level
    if state.role_filter == "fan_club" and fan_level < 1:
        return False, "Fan Club only", fan_level
    if state.min_fan_level > 0 and fan_level < state.min_fan_level:
        return False, f"Requires Fan Lv.{state.min_fan_level} (Viewer is Lv.{fan_level})", fan_level

    # 4. Max length truncate
    if len(clean_text) > state.max_chars:
        clean_text = clean_text[:state.max_chars]
    
    # 5. Banned words check
    lower_text = clean_text.lower()
    for word in state.banned_words:
        if word and word.lower() in lower_text:
            return False, f"Blacklisted word: {word}", fan_level
            
    # 6. Cooldown check
    last = state.user_last_seen.get(user_id, 0)
    if (now - last) < state.cooldown:
        remaining = int(state.cooldown - (now - last))
        return False, f"Cooldown ({remaining}s)", fan_level
        
    state.user_last_seen[user_id] = now
    return True, clean_text, fan_level

def get_voice_id_from_name(voice_name: str) -> Optional[str]:
    if not voice_name:
        return None
    vn = voice_name.lower().strip()
    if vn.startswith("store:"):
        return vn.split(":")[1].strip()
    for vid, meta in PIPER_VOICE_CATALOG.items():
        if vid in vn or meta["name"].lower() in vn:
            return vid
    return None

async def handle_new_tts_item(user: str, raw_text: str, display_text: str, fan_level: int = 0):
    # Ensure raw_text synthesized by any engine has all emojis stripped completely
    raw_text = strip_emojis(raw_text)
    voice_name = state.native_voice_name or ""
    v_id = get_voice_id_from_name(voice_name)

    if v_id and v_id in state.installed_voices:
        loop = asyncio.get_event_loop()
        b64 = await loop.run_in_executor(None, synthesize_piper, v_id, raw_text)
        if b64:
            await broadcast({
                "type": "tts_audio",
                "user": user,
                "display": display_text,
                "audio_b64": b64
            })
            return

    item = {
        "id": str(uuid.uuid4()),
        "user": user,
        "fan_level": fan_level,
        "text": raw_text,
        "display": display_text,
        "engine": "instant",
        "voice": state.voice,
        "time": time.strftime("%H:%M:%S")
    }
    await broadcast({
        "type": "tts_instant",
        "item": item
    })

async def tiktok_runner(username: str):
    clean_user = username.lstrip("@").strip()
    state.username = clean_user
    save_config(state.export_config())
    
    state.status = "connecting"
    state.status_msg = f"Connecting to @{clean_user}..."
    await broadcast({"type": "status", "status": state.status, "message": state.status_msg})

    try:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import ConnectEvent, CommentEvent, GiftEvent, DisconnectEvent, SubNotifyEvent

        client = TikTokLiveClient(unique_id=clean_user)
        # Disable TikTokLive's synchronous teardown to prevent RuntimeError: This event loop is already running
        client._clean_tasks = lambda: None
        state.client = client

        is_live = await client.is_live()
        if not is_live:
            state.status = "offline"
            state.status_msg = f"@{clean_user} is currently offline. Start streaming or try another username."
            await broadcast({"type": "status", "status": state.status, "message": state.status_msg})
            return

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            state.status = "connected"
            state.status_msg = f"🟢 Connected to @{clean_user} live room!"
            await broadcast({"type": "status", "status": state.status, "message": state.status_msg})

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            allowed, result, fan_level = check_filters(event, event.comment)
                
            log_item = {
                "type": "comment",
                "user": event.user.nickname,
                "fan_level": fan_level,
                "text": event.comment,
                "allowed": allowed,
                "reason": result if not allowed else "",
                "time": time.strftime("%H:%M:%S")
            }
            await broadcast({"type": "chat_log", "data": log_item})

            if allowed:
                clean_name = clean_speech_username(event.user.nickname)
                speech_comment = strip_emojis(result)
                if clean_name:
                    speech_text = f"{clean_name} says: {speech_comment}"
                else:
                    speech_text = speech_comment
                await handle_new_tts_item(event.user.nickname, speech_text, event.comment, fan_level=fan_level)

        @client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            if event.gift.streakable and event.streaking:
                return  # Skip rapid intermediate streak numbers
                
            coins = getattr(event.gift, 'diamond_count', 0) * event.repeat_count
            allowed = state.gift_tts_enabled and (coins >= state.gift_min_coins)
            reason = "" if allowed else ("Gift TTS disabled" if not state.gift_tts_enabled else f"Under {state.gift_min_coins} coins")

            log_item = {
                "type": "gift",
                "user": event.user.nickname,
                "text": f"Sent {event.repeat_count}x {event.gift.name} ({coins} coins)",
                "allowed": allowed,
                "reason": reason,
                "time": time.strftime("%H:%M:%S")
            }
            await broadcast({"type": "chat_log", "data": log_item})

            if state.gift_sound_enabled:
                await broadcast({"type": "gift_chime"})

            if allowed:
                clean_name = clean_speech_username(event.user.nickname)
                if clean_name:
                    speech_text = f"Thank you {clean_name} for sending {event.repeat_count} {event.gift.name}!"
                else:
                    speech_text = f"Thank you for sending {event.repeat_count} {event.gift.name}!"
                await handle_new_tts_item(event.user.nickname, speech_text, f"Sent {event.repeat_count}x {event.gift.name}")

        @client.on(SubNotifyEvent)
        async def on_sub(event: SubNotifyEvent):
            user_name = getattr(event.user, 'nickname', 'Subscriber')
            months = getattr(event, 'sub_month', 1)
            text = f"Subscribed for {months} month{'s' if months > 1 else ''}!"
            log_item = {
                "type": "sub",
                "user": user_name,
                "text": text,
                "allowed": state.fan_announcements_enabled,
                "reason": "" if state.fan_announcements_enabled else "Announcements disabled",
                "time": time.strftime("%H:%M:%S")
            }
            await broadcast({"type": "chat_log", "data": log_item})

            if state.fan_announcements_enabled:
                if state.gift_sound_enabled:
                    await broadcast({"type": "gift_chime"})
                clean_name = clean_speech_username(user_name)
                if clean_name:
                    speech = f"Welcome {clean_name} to the subscriber club!" if months <= 1 else f"Thank you {clean_name} for resubscribing for {months} months!"
                else:
                    speech = f"Welcome to the subscriber club!" if months <= 1 else f"Thank you for resubscribing for {months} months!"
                await handle_new_tts_item(user_name, speech, text, fan_level=1)

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            state.status = "disconnected"
            state.status_msg = "Disconnected from livestream."
            await broadcast({"type": "status", "status": state.status, "message": state.status_msg})

        # Start non-blocking connection task
        task = await client.start(process_connect_events=True)
        await task

    except asyncio.CancelledError:
        if state.client and state.client.connected:
            try:
                await state.client.disconnect()
            except Exception:
                pass
        state.status = "disconnected"
        state.status_msg = "Disconnected."
        await broadcast({"type": "status", "status": state.status, "message": state.status_msg})
    except Exception as e:
        err_msg = str(e)
        if "UserNotFoundError" in type(e).__name__:
            err_msg = f"@{clean_user} does not exist or has never gone live."
        elif "UserOfflineError" in type(e).__name__:
            err_msg = f"@{clean_user} is currently offline."
        state.status = "error"
        state.status_msg = f"Error: {err_msg}"
        await broadcast({"type": "status", "status": state.status, "message": state.status_msg})
        await broadcast({"type": "status", "status": state.status, "message": state.status_msg})

async def cloud_tts_worker():
    while True:
        item = await state.tts_queue.get()
        try:
            state.current_speaking = item
            await broadcast({
                "type": "speaking_start",
                "item": item,
                "queue_size": state.tts_queue.qsize()
            })

            import edge_tts
            comm = edge_tts.Communicate(text=item["text"], voice=item.get("voice", state.voice))
            audio_buffer = bytearray()
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    audio_buffer.extend(chunk["data"])

            b64_audio = base64.b64encode(bytes(audio_buffer)).decode("utf-8")

            await broadcast({
                "type": "tts_audio",
                "id": item["id"],
                "user": item["user"],
                "text": item["text"],
                "display": item.get("display", item["text"]),
                "audio_b64": b64_audio,
                "queue_size": state.tts_queue.qsize()
            })
        except Exception:
            pass
        finally:
            state.tts_queue.task_done()

@app.on_event("startup")
async def startup():
    asyncio.create_task(cloud_tts_worker())

@app.get("/api/version")
async def api_version():
    return {
        "current_version": CURRENT_VERSION,
        "repo": GITHUB_REPO,
        "active_port": active_port
    }

def _parse_version(v: str):
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split(".") if x.isdigit())
    except Exception:
        return (0, 0, 0)

@app.get("/api/check-update")
async def api_check_update():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"User-Agent": "TikTokLiveTTS-App"})
            if resp.status_code == 200:
                data = resp.json()
                raw_tag = data.get("tag_name", "").strip()
                latest_tag = raw_tag.lstrip("v")
                has_update = bool(latest_tag) and _parse_version(latest_tag) > _parse_version(CURRENT_VERSION)
                return {
                    "has_update": has_update,
                    "current_version": CURRENT_VERSION,
                    "latest_version": latest_tag or CURRENT_VERSION,
                    "release_url": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
                    "release_notes": data.get("body", "")
                }
    except Exception:
        pass
    return {
        "has_update": False,
        "current_version": CURRENT_VERSION,
        "latest_version": CURRENT_VERSION,
        "release_url": f"https://github.com/{GITHUB_REPO}/releases",
        "release_notes": ""
    }

@app.post("/api/install-update")
async def api_install_update():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"User-Agent": "TikTokLiveTTS-App"})
            if resp.status_code != 200:
                return {"status": "error", "message": f"GitHub returned HTTP {resp.status_code}"}
            data = resp.json()
            assets = data.get("assets", [])
            latest_tag = data.get("tag_name", "").lstrip("v")
            setup_download_url = None
            zip_download_url = None
            for asset in assets:
                aname = asset.get("name", "")
                if aname == "TikTokLiveTTS-Setup.exe":
                    setup_download_url = asset.get("browser_download_url")
                elif aname == "TikTokLiveTTS-Windows.zip":
                    zip_download_url = asset.get("browser_download_url")

            # Route 1: Modern Single-File Setup Installer
            if setup_download_url:
                setup_dest = os.path.join(tempfile.gettempdir(), f"TikTokLiveTTS-Setup-{latest_tag}.exe")
                await broadcast({"type": "update_progress", "status": "Downloading update installer (15%)...", "percent": 15})

                async with client.stream("GET", setup_download_url, follow_redirects=True) as stream:
                    total_bytes = int(stream.headers.get("content-length", 0))
                    downloaded = 0
                    with open(setup_dest, "wb") as f:
                        async for chunk in stream.aiter_bytes():
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_bytes > 0:
                                pct = int((downloaded / total_bytes) * 80) + 15
                                await broadcast({"type": "update_progress", "status": f"Downloading installer ({pct}%)...", "percent": pct})

                await broadcast({"type": "update_progress", "status": "Launching installer...", "percent": 100})

                CREATE_NEW_PROCESS_GROUP = 0x00000200
                # Inno Setup /SILENT displays the small installation progress window and restarts cleanly
                subprocess.Popen(
                    [setup_dest, "/SILENT", "/CLOSEAPPLICATIONS"],
                    creationflags=CREATE_NEW_PROCESS_GROUP,
                    close_fds=True
                )

                def do_exit_installer():
                    time.sleep(0.6)
                    os._exit(0)

                threading.Thread(target=do_exit_installer, daemon=True).start()
                return {"status": "ok", "message": "Launching installer..."}

            # Route 2: Portable ZIP fallback
            if not zip_download_url:
                return {"status": "error", "message": "No installer or update package found in release"}

            download_url = zip_download_url

            temp_dir = os.path.join(tempfile.gettempdir(), "tiktok_tts_update")
            os.makedirs(temp_dir, exist_ok=True)
            zip_dest = os.path.join(temp_dir, "update.zip")

            await broadcast({"type": "update_progress", "status": "Downloading update package (15%)...", "percent": 15})

            async with client.stream("GET", download_url, follow_redirects=True) as stream:
                total_bytes = int(stream.headers.get("content-length", 0))
                downloaded = 0
                with open(zip_dest, "wb") as f:
                    async for chunk in stream.aiter_bytes():
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_bytes > 0:
                            pct = int((downloaded / total_bytes) * 75) + 15
                            await broadcast({"type": "update_progress", "status": f"Downloading ({pct}%)...", "percent": pct})

            await broadcast({"type": "update_progress", "status": "Extracting update files...", "percent": 92})
            extract_dir = os.path.join(temp_dir, "extracted")
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
            os.makedirs(extract_dir, exist_ok=True)

            with zipfile.ZipFile(zip_dest, "r") as z:
                z.extractall(extract_dir)

            source_folder = extract_dir
            for root, dirs, files in os.walk(extract_dir):
                if "TikTokLiveTTS.exe" in files:
                    source_folder = root
                    break

            target_dir = BASE_DIR
            target_exe = os.path.join(target_dir, "TikTokLiveTTS.exe")
            current_pid = os.getpid()

            # Priority 1: Modern Antigravity/Discord style GUI updater box (updater.exe)
            updater_exe = os.path.join(source_folder, "updater.exe")
            if not os.path.exists(updater_exe):
                updater_exe = os.path.join(target_dir, "updater.exe")

            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            CREATE_NO_WINDOW = 0x08000000

            if os.path.exists(updater_exe):
                await broadcast({"type": "update_progress", "status": "Launching updater dialog...", "percent": 100})
                cmd = [
                    updater_exe,
                    "--pid", str(current_pid),
                    "--source", source_folder,
                    "--target", target_dir,
                    "--exe", target_exe,
                    "--version", f"v{latest_tag}"
                ]
                subprocess.Popen(
                    cmd,
                    creationflags=CREATE_NEW_PROCESS_GROUP,
                    close_fds=True
                )
            else:
                # Priority 2: 100% Silent VBScript launcher (never opens any black terminal / cmd window)
                vbs_path = os.path.join(temp_dir, "silent_updater.vbs")
                bat_path = os.path.join(temp_dir, "apply_update.bat")
                with open(bat_path, "w", encoding="utf-8") as bf:
                    bf.write(f"""@echo off
set "OLD_PID={current_pid}"
taskkill /F /T /PID %OLD_PID% >nul 2>&1
ping 127.0.0.1 -n 3 >nul
robocopy "{source_folder}" "{target_dir}" /E /IS /IT /R:2 /W:1 /nfl /ndl /njh /njs >nul
start "" "{target_exe}"
exit
""")
                with open(vbs_path, "w", encoding="utf-8") as vf:
                    # Parameter 0 hides console window completely (vbHide)
                    vf.write(f'CreateObject("Wscript.Shell").Run chr(34) & "{bat_path}" & chr(34), 0, False\n')

                subprocess.Popen(
                    ["wscript.exe", "//B", "//Nologo", vbs_path],
                    creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                    close_fds=True
                )

            def do_exit():
                time.sleep(0.8)
                os._exit(0)

            threading.Thread(target=do_exit, daemon=True).start()
            return {"status": "ok", "message": "Update downloaded, launching installer..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/connect")
async def api_connect(req: ConnectRequest):
    if state.client and state.client.connected:
        try:
            await state.client.disconnect()
        except Exception:
            pass
    if state.task and not state.task.done():
        state.task.cancel()
        try:
            await state.task
        except asyncio.CancelledError:
            pass

    state.task = asyncio.create_task(tiktok_runner(req.username))
    return {"status": "ok", "message": f"Connecting to @{req.username}..."}

@app.post("/api/disconnect")
async def api_disconnect():
    if state.client and state.client.connected:
        try:
            await state.client.disconnect()
        except Exception:
            pass
    if state.task and not state.task.done():
        state.task.cancel()
        try:
            await state.task
        except asyncio.CancelledError:
            pass
    state.status = "disconnected"
    state.status_msg = "Disconnected"
    await broadcast({"type": "status", "status": state.status, "message": state.status_msg})
    return {"status": "ok", "message": "Disconnected"}

@app.post("/api/speak")
async def api_speak(req: SpeakRequest):
    speech_text = req.text
    voice_name = state.native_voice_name or ""
    v_id = get_voice_id_from_name(voice_name)

    if v_id and v_id in state.installed_voices:
        loop = asyncio.get_event_loop()
        b64 = await loop.run_in_executor(None, synthesize_piper, v_id, speech_text)
        if b64:
            await broadcast({
                "type": "tts_audio",
                "user": "Test User",
                "display": req.text,
                "audio_b64": b64
            })
            return {
                "status": "ok",
                "is_piper": True,
                "voice_id": v_id,
                "audio_b64": b64,
                "text": req.text
            }

    await handle_new_tts_item("Test User", speech_text, req.text)
    return {
        "status": "ok",
        "is_piper": False,
        "voice": voice_name,
        "text": req.text
    }

@app.post("/api/clear-queue")
async def api_clear_queue():
    while not state.tts_queue.empty():
        try:
            state.tts_queue.get_nowait()
            state.tts_queue.task_done()
        except asyncio.QueueEmpty:
            break
    await broadcast({"type": "queue_size", "size": 0})
    return {"status": "ok", "message": "Queue cleared"}

@app.post("/api/settings")
async def api_settings(req: SettingsRequest):
    if req.engine is not None:
        state.engine = req.engine
    if req.voice is not None:
        state.voice = req.voice
    if req.native_voice_name is not None:
        state.native_voice_name = req.native_voice_name
    if req.audio_device_id is not None:
        state.audio_device_id = req.audio_device_id
    if req.installed_voices is not None:
        state.installed_voices = req.installed_voices
    if req.volume is not None:
        state.volume = req.volume
    if req.cooldown is not None:
        state.cooldown = req.cooldown
    if req.max_chars is not None:
        state.max_chars = req.max_chars
    if req.banned_words is not None:
        state.banned_words_raw = req.banned_words
        state.banned_words = [w.strip() for w in req.banned_words.split(",") if w.strip()]
    if req.role_filter is not None:
        state.role_filter = req.role_filter
    if req.min_fan_level is not None:
        state.min_fan_level = req.min_fan_level
    if req.fan_announcements_enabled is not None:
        state.fan_announcements_enabled = req.fan_announcements_enabled
    if req.gift_tts_enabled is not None:
        state.gift_tts_enabled = req.gift_tts_enabled
    if req.gift_sound_enabled is not None:
        state.gift_sound_enabled = req.gift_sound_enabled
    if req.gift_min_coins is not None:
        state.gift_min_coins = req.gift_min_coins
    if req.spam_auto_mute is not None:
        state.spam_auto_mute = req.spam_auto_mute
    if req.command_prefix is not None:
        state.command_prefix = req.command_prefix
    if req.starred_voices is not None:
        state.starred_voices = req.starred_voices

    save_config(state.export_config())

    return {
        "status": "ok",
        "config": state.export_config()
    }

class VoiceActionRequest(BaseModel):
    voice_id: str

@app.post("/api/install-voice")
async def api_install_voice(req: VoiceActionRequest):
    v_id = req.voice_id
    if v_id not in PIPER_VOICE_CATALOG:
        return {"status": "error", "message": f"Unknown voice {v_id}"}

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, ensure_piper_engine)
    success = await loop.run_in_executor(None, download_piper_voice, v_id)
    if not success:
        return {"status": "error", "message": f"Failed to download voice files for {v_id}"}

    if v_id not in state.installed_voices:
        state.installed_voices.append(v_id)

    state.native_voice_name = f"store:{v_id}"
    save_config(state.export_config())
    return {
        "status": "ok",
        "voice_id": v_id,
        "installed_voices": state.installed_voices,
        "active_voice": state.native_voice_name
    }

@app.post("/api/uninstall-voice")
async def api_uninstall_voice(req: VoiceActionRequest):
    v_id = req.voice_id
    if v_id in state.installed_voices:
        state.installed_voices.remove(v_id)

    target_dir = os.path.join(VOICES_DIR, v_id)
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
        except Exception as e:
            print(f"Error removing {target_dir}: {e}")

    if state.native_voice_name in [f"store:{v_id}", v_id]:
        state.native_voice_name = ""

    save_config(state.export_config())
    return {
        "status": "ok",
        "voice_id": v_id,
        "installed_voices": state.installed_voices,
        "active_voice": state.native_voice_name
    }

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.websockets.add(ws)
    await ws.send_json({
        "type": "init",
        "version": CURRENT_VERSION,
        "active_port": active_port,
        "status": state.status,
        "message": state.status_msg,
        "config": state.export_config(),
        "queue_size": state.tts_queue.qsize()
    })
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif data.get("action") == "skip":
                await broadcast({"type": "client_skip"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        state.websockets.discard(ws)

HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TTS Live Studio</title>
  <style>
    :root {
      --bg-canvas: #000000;
      --bg-surface: #09090b;
      --bg-elevated: #111114;
      --bg-hover: #18181c;
      --border-subtle: rgba(255, 255, 255, 0.075);
      --border-strong: rgba(255, 255, 255, 0.14);
      --accent: #38bdf8;
      --accent-soft: rgba(56, 189, 248, 0.12);
      --live: #10b981;
      --live-soft: rgba(16, 185, 129, 0.12);
      --amber: #f59e0b;
      --rose: #f43f5e;
      --text-primary: #fafafa;
      --text-secondary: #a1a1aa;
      --text-muted: #71717a;
      --radius-sm: 8px;
      --radius-md: 10px;
      --radius-lg: 14px;
      --radius-full: 9999px;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Inter, system-ui, sans-serif;
      --font-mono: "JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      height: 100%;
      background: var(--bg-canvas);
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 13px;
      line-height: 1.45;
      user-select: none;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
    }
    body {
      display: flex;
      flex-direction: column;
    }

    /* Custom Dark Scrollbar */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #27272a; border-radius: 999px; }
    ::-webkit-scrollbar-thumb:hover { background: #3f3f46; }

    /* Unified Studio Topbar */
    header {
      height: 56px;
      flex-shrink: 0;
      background: #000000;
      border-bottom: 1px solid var(--border-subtle);
      padding: 0 20px;
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      gap: 16px;
      z-index: 50;
    }
    .brand-group {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .brand-icon-box {
      width: 30px;
      height: 30px;
      border-radius: 8px;
      background: linear-gradient(180deg, #16161a 0%, #09090b 100%);
      border: 1px solid rgba(56, 189, 248, 0.35);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--accent);
      box-shadow: 0 0 18px rgba(56, 189, 248, 0.16);
      flex-shrink: 0;
    }
    .brand-title {
      font-size: 14px;
      font-weight: 600;
      letter-spacing: -0.02em;
      color: #ffffff;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .version-pill {
      font-family: var(--font-mono);
      font-size: 10.5px;
      font-weight: 500;
      padding: 2px 7px;
      border-radius: var(--radius-full);
      background: rgba(255, 255, 255, 0.05);
      color: var(--text-secondary);
      border: 1px solid var(--border-subtle);
    }

    /* Center Pill Navigation */
    .nav-bar {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      padding: 3px;
      background: #09090b;
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-full);
    }
    .nav-tab {
      padding: 6px 14px;
      background: transparent;
      border: none;
      border-radius: var(--radius-full);
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 140ms ease;
      white-space: nowrap;
    }
    .nav-tab svg {
      width: 13.5px;
      height: 13.5px;
      opacity: 0.75;
    }
    .nav-tab:hover {
      color: #ffffff;
      background: rgba(255, 255, 255, 0.04);
    }
    .nav-tab.active {
      color: #000000;
      background: #ffffff;
      font-weight: 600;
      box-shadow: 0 1px 6px rgba(255, 255, 255, 0.18);
    }
    .nav-tab.active svg {
      opacity: 1;
    }
    .nav-count {
      font-family: var(--font-mono);
      font-size: 10px;
      padding: 0 5px;
      border-radius: var(--radius-full);
      background: rgba(255, 255, 255, 0.1);
      color: inherit;
    }
    .nav-tab.active .nav-count {
      background: rgba(0, 0, 0, 0.12);
      color: #000000;
    }

    /* Right Telemetry Strip */
    .telemetry-strip {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
    }
    .telemetry-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 11px;
      border-radius: var(--radius-full);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 500;
      background: #09090b;
      border: 1px solid var(--border-subtle);
      color: var(--text-secondary);
    }
    .telemetry-badge.latency {
      color: var(--accent);
      background: rgba(56, 189, 248, 0.07);
      border-color: rgba(56, 189, 248, 0.22);
    }
    .telemetry-badge.connected {
      background: var(--live-soft);
      color: #34d399;
      border-color: rgba(16, 185, 129, 0.32);
    }
    .telemetry-badge.offline, .telemetry-badge.disconnected {
      background: #09090b;
      color: var(--text-muted);
      border-color: var(--border-subtle);
    }
    .telemetry-badge.connecting {
      background: rgba(245, 158, 11, 0.12);
      color: #fbbf24;
      border-color: rgba(245, 158, 11, 0.32);
    }
    .status-dot {
      width: 6.5px;
      height: 6.5px;
      border-radius: 50%;
      background: currentColor;
    }
    .status-dot.pulse {
      box-shadow: 0 0 8px currentColor;
      animation: pulseStatus 2s infinite;
    }
    @keyframes pulseStatus {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }

    .update-pill {
      display: none;
      align-items: center;
      gap: 6px;
      padding: 5px 11px;
      border-radius: var(--radius-full);
      font-size: 11px;
      font-weight: 600;
      background: rgba(56, 189, 248, 0.12);
      color: var(--accent);
      border: 1px solid rgba(56, 189, 248, 0.35);
      cursor: pointer;
    }
    .update-pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }

    /* Workspace Tabs */
    .tab-content {
      display: none;
      flex: 1;
      min-height: 0;
      padding: 16px 20px;
      width: 100%;
      overflow-y: auto;
    }
    .tab-content.active {
      display: flex;
      flex-direction: column;
      animation: tabFadeIn 180ms ease-out;
    }
    @keyframes tabFadeIn {
      from { opacity: 0; transform: translateY(3px); }
      to { opacity: 1; transform: none; }
    }

    /* Tab 1: 3-Column Broadcast Console (Viewport-Fitted) */
    .console-grid {
      display: grid;
      grid-template-columns: 336px 352px minmax(0, 1fr);
      gap: 14px;
      flex: 1;
      min-height: 0;
    }
    .console-col {
      display: flex;
      flex-direction: column;
      gap: 12px;
      min-height: 0;
      overflow-y: auto;
      padding-right: 2px;
    }
    .console-col-feed {
      display: flex;
      flex-direction: column;
      gap: 12px;
      min-height: 0;
      overflow: hidden;
    }

    /* Studio Surface Cards */
    .card {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 15px 16px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.035);
      flex-shrink: 0;
    }
    .card-fill {
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }
    .card-title {
      font-size: 12px;
      font-weight: 600;
      letter-spacing: -0.01em;
      color: #ffffff;
      margin-bottom: 11px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .card-tag {
      font-family: var(--font-mono);
      font-size: 10.5px;
      font-weight: 500;
      color: var(--text-muted);
    }
    .card-tag.live {
      color: #34d399;
    }

    label {
      display: block;
      font-size: 11.5px;
      font-weight: 500;
      color: var(--text-secondary);
      margin-bottom: 5px;
    }
    .helper-text {
      font-size: 11px;
      color: var(--text-muted);
      margin-top: 5px;
      line-height: 1.35;
    }
    .helper-text-success {
      color: #34d399;
    }

    /* Inputs & Selects */
    input[type="text"], input[type="number"], select {
      width: 100%;
      background: #000000;
      border: 1px solid rgba(255, 255, 255, 0.09);
      border-radius: var(--radius-sm);
      padding: 8px 11px;
      color: #ffffff;
      font-family: var(--font-sans);
      font-size: 12.5px;
      outline: none;
      transition: border-color 140ms ease, box-shadow 140ms ease;
    }
    select {
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23a1a1aa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 10px center;
      padding-right: 30px;
    }
    input[type="text"]:focus, input[type="number"]:focus, select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.16);
    }

    .input-prefix-box {
      display: flex;
      align-items: center;
      background: #000000;
      border: 1px solid rgba(255, 255, 255, 0.09);
      border-radius: var(--radius-sm);
      overflow: hidden;
      transition: border-color 140ms ease, box-shadow 140ms ease;
    }
    .input-prefix-box:focus-within {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.16);
    }
    .input-prefix-label {
      padding: 8px 11px;
      background: #0d0d10;
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-weight: 600;
      font-size: 12.5px;
      border-right: 1px solid rgba(255, 255, 255, 0.08);
    }
    .input-prefix-box input {
      border: none !important;
      box-shadow: none !important;
      background: transparent !important;
    }

    /* Custom Dark Range Slider */
    input[type="range"] {
      -webkit-appearance: none;
      appearance: none;
      width: 100%;
      height: 5px;
      background: #1c1c21;
      border-radius: 999px;
      outline: none;
      cursor: pointer;
    }
    input[type="range"]::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 15px;
      height: 15px;
      border-radius: 50%;
      background: #ffffff;
      border: 2px solid var(--accent);
      box-shadow: 0 1px 6px rgba(0, 0, 0, 0.6);
      cursor: pointer;
      transition: transform 120ms ease;
    }
    input[type="range"]::-webkit-slider-thumb:hover {
      transform: scale(1.12);
    }

    /* Buttons */
    .btn-row {
      display: flex;
      gap: 8px;
      margin-top: 10px;
    }
    button {
      padding: 8px 14px;
      border-radius: var(--radius-sm);
      border: 1px solid transparent;
      font-family: var(--font-sans);
      font-weight: 600;
      font-size: 12px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: all 130ms ease;
    }
    button:active:not(:disabled) {
      transform: scale(0.98);
    }
    .btn-primary {
      background: #ffffff;
      color: #000000;
      border-color: #ffffff;
    }
    .btn-primary:hover:not(:disabled) {
      background: #e4e4e7;
    }
    .btn-live {
      background: var(--live);
      color: #000000;
      font-weight: 600;
    }
    .btn-live:hover:not(:disabled) {
      background: #34d399;
    }
    .btn-secondary {
      background: var(--bg-elevated);
      color: var(--text-primary);
      border-color: rgba(255, 255, 255, 0.08);
    }
    .btn-secondary:hover:not(:disabled) {
      background: var(--bg-hover);
      border-color: rgba(255, 255, 255, 0.16);
    }
    .btn-danger {
      background: rgba(244, 63, 94, 0.1);
      color: #fda4af;
      border-color: rgba(244, 63, 94, 0.22);
    }
    .btn-danger:hover:not(:disabled) {
      background: rgba(244, 63, 94, 0.18);
      color: #ffffff;
    }

    /* Segmented Audience Role Selector */
    .role-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 4px;
      padding: 3px;
      background: #000000;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: var(--radius-md);
      margin-bottom: 10px;
    }
    .role-btn {
      padding: 6px 6px;
      border-radius: 7px;
      background: transparent;
      border: none;
      color: var(--text-secondary);
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      transition: all 120ms ease;
    }
    .role-btn:hover {
      color: #ffffff;
    }
    .role-btn.active {
      background: var(--accent);
      color: #000000;
      font-weight: 600;
    }

    /* Hardware Switches */
    .toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 5px 0;
      gap: 10px;
    }
    .toggle-row + .toggle-row {
      border-top: 1px solid rgba(255, 255, 255, 0.04);
    }
    .toggle-row label {
      margin-bottom: 0;
      cursor: pointer;
      font-size: 12px;
      color: #e4e4e7;
    }
    .switch {
      position: relative;
      display: inline-block;
      width: 36px;
      height: 20px;
      flex-shrink: 0;
    }
    .switch input { opacity: 0; width: 0; height: 0; }
    .slider {
      position: absolute;
      cursor: pointer;
      inset: 0;
      background-color: #18181b;
      border: 1px solid rgba(255, 255, 255, 0.14);
      transition: 0.18s ease;
      border-radius: 999px;
    }
    .slider:before {
      position: absolute;
      content: "";
      height: 14px;
      width: 14px;
      left: 2px;
      bottom: 2px;
      background-color: #71717a;
      transition: 0.18s ease;
      border-radius: 50%;
    }
    .switch input:checked + .slider {
      background-color: rgba(56, 189, 248, 0.2);
      border-color: var(--accent);
    }
    .switch input:checked + .slider:before {
      transform: translateX(16px);
      background-color: var(--accent);
    }

    /* Soundboard Grid & Filter Chips */
    .preset-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 6px;
      margin-bottom: 10px;
    }
    .sound-pad {
      background: #000000;
      border: 1px solid rgba(255, 255, 255, 0.075);
      color: #d4d4d8;
      font-size: 11.5px;
      font-weight: 500;
      padding: 7px 10px;
      border-radius: var(--radius-sm);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 7px;
      transition: all 120ms ease;
      text-align: left;
    }
    .sound-pad:hover {
      background: var(--bg-elevated);
      border-color: rgba(56, 189, 248, 0.35);
      color: #ffffff;
    }
    .sound-pad-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent);
      opacity: 0.7;
      flex-shrink: 0;
    }

    .chip {
      background: #0d0d10;
      border: 1px solid var(--border-subtle);
      color: var(--text-secondary);
      font-size: 11px;
      font-weight: 500;
      padding: 5px 11px;
      border-radius: var(--radius-full);
      cursor: pointer;
      transition: all 120ms ease;
      white-space: nowrap;
    }
    .chip:hover {
      color: #ffffff;
      border-color: rgba(255, 255, 255, 0.16);
    }
    .chip.active {
      background: #ffffff;
      color: #000000;
      font-weight: 600;
      border-color: #ffffff;
    }

    /* Equalizer Wave */
    .equalizer-wave {
      display: inline-flex;
      align-items: flex-end;
      gap: 2.5px;
      height: 14px;
    }
    .eq-bar {
      width: 2.5px;
      background: var(--accent);
      border-radius: 999px;
      height: 3px;
      transition: height 140ms ease;
    }
    .eq-active .eq-bar {
      animation: eqBounce 0.65s ease-in-out infinite alternate;
    }
    .eq-active .eq-bar:nth-child(2) { animation-delay: 0.15s; height: 11px; }
    .eq-active .eq-bar:nth-child(3) { animation-delay: 0.3s; height: 14px; }
    .eq-active .eq-bar:nth-child(4) { animation-delay: 0.18s; height: 8px; }
    .eq-active .eq-bar:nth-child(5) { animation-delay: 0.4s; height: 12px; }
    @keyframes eqBounce {
      0% { height: 3px; }
      100% { height: 14px; }
    }

    /* On-Air Monitor */
    .now-speaking-card {
      background: linear-gradient(180deg, #0d0d11 0%, #09090b 100%);
      border: 1px solid rgba(56, 189, 248, 0.22);
    }
    .speaking-display {
      min-height: 76px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      background: #000000;
      border-radius: var(--radius-md);
      padding: 12px 15px;
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .speaking-user {
      font-family: var(--font-mono);
      font-size: 11.5px;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 3px;
    }
    .speaking-text {
      font-size: 15px;
      font-weight: 500;
      color: #ffffff;
      line-height: 1.4;
      word-break: break-word;
    }
    .speaking-idle {
      color: var(--text-muted);
      font-size: 12.5px;
      font-weight: 400;
    }

    /* Live Stream Activity Log */
    .log-container {
      background: #000000;
      border: 1px solid rgba(255, 255, 255, 0.07);
      border-radius: var(--radius-md);
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 5px;
    }
    .log-empty {
      color: var(--text-muted);
      text-align: center;
      margin: auto;
      font-size: 12px;
      padding: 32px 16px;
    }
    .log-item {
      padding: 8px 11px;
      border-radius: var(--radius-sm);
      background: #09090b;
      border: 1px solid rgba(255, 255, 255, 0.055);
      font-size: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .log-item.gift {
      border-left: 2.5px solid var(--amber);
      background: rgba(245, 158, 11, 0.06);
    }
    .log-item.sub {
      border-left: 2.5px solid #a855f7;
      background: rgba(168, 85, 247, 0.06);
    }
    .log-item.fan {
      border-left: 2.5px solid var(--accent);
      background: rgba(56, 189, 248, 0.06);
    }
    .log-item.blocked {
      opacity: 0.55;
      border-left: 2.5px solid var(--rose);
    }
    .badge-fan {
      display: inline-block;
      background: var(--amber);
      color: #000000;
      font-family: var(--font-mono);
      font-size: 9.5px;
      font-weight: 700;
      padding: 1px 5px;
      border-radius: 4px;
      margin-right: 6px;
    }
    .log-user {
      font-weight: 600;
      color: var(--accent);
      margin-right: 6px;
    }
    .log-text {
      color: #f4f4f5;
    }
    .log-time {
      font-size: 10.5px;
      color: var(--text-muted);
      white-space: nowrap;
      font-family: var(--font-mono);
    }

    /* Voice Store Catalog */
    .store-filter-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 16px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--border-subtle);
    }
    .store-search-box {
      width: 240px;
    }
    .voice-card {
      background: #09090b;
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 16px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: border-color 140ms ease, background-color 140ms ease;
    }
    .voice-card:hover {
      border-color: var(--border-strong);
      background: #0d0d10;
    }
    .voice-card.starred {
      border-color: rgba(56, 189, 248, 0.35);
    }
    .voice-badge-tag {
      font-family: var(--font-mono);
      font-size: 10.5px;
      font-weight: 500;
      padding: 2px 8px;
      border-radius: var(--radius-full);
      background: rgba(255, 255, 255, 0.05);
      color: var(--text-secondary);
      border: 1px solid var(--border-subtle);
    }
    .star-btn {
      background: transparent;
      border: 1px solid var(--border-subtle);
      color: var(--text-secondary);
      font-size: 11px;
      padding: 3px 9px;
      border-radius: var(--radius-full);
      cursor: pointer;
    }
    .star-btn:hover, .star-btn.active {
      border-color: rgba(245, 158, 11, 0.45);
      color: var(--amber);
      background: rgba(245, 158, 11, 0.1);
    }

    /* Modal */
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.82);
      backdrop-filter: blur(10px);
      z-index: 100;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .modal-box {
      background: #09090b;
      border: 1px solid var(--border-strong);
      border-radius: 16px;
      max-width: 480px;
      width: 100%;
      padding: 22px;
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.95);
    }

    .grid-2col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .bg-dots-stage {
      background-color: #050507;
      background-image: radial-gradient(rgba(255, 255, 255, 0.08) 1px, transparent 1px);
      background-size: 18px 18px;
    }
  </style>
</head>
<body>

  <!-- Unified Studio Topbar -->
  <header>
    <div class="brand-group">
      <div class="brand-icon-box" style="padding: 0; overflow: hidden; border: none; background: transparent; box-shadow: none;">
        <svg width="30" height="30" viewBox="0 0 1024 1024" fill="none">
          <rect x="32" y="32" width="960" height="960" rx="230" fill="#0c0c10" stroke="#38bdf8" stroke-opacity="0.45" stroke-width="28"/>
          <rect x="220" y="340" width="52" height="220" rx="26" fill="#38bdf8"/>
          <rect x="752" y="340" width="52" height="220" rx="26" fill="#38bdf8"/>
          <rect x="404" y="206" width="216" height="340" rx="108" fill="#ffffff"/>
          <path d="M336 436 v18 c0 97.2 78.8 176 176 176 s176 -78.8 176 -176 v-18" stroke="#38bdf8" stroke-width="52" stroke-linecap="round"/>
          <path d="M512 630 v140" stroke="#38bdf8" stroke-width="52" stroke-linecap="round"/>
          <path d="M388 774 h248" stroke="#ffffff" stroke-width="52" stroke-linecap="round"/>
          <circle cx="808" cy="216" r="36" fill="#10b981"/>
        </svg>
      </div>
      <div class="brand-title">
        <span>TTS Live Studio</span>
        <span class="version-pill" id="app-version">v1.9.9</span>
      </div>
    </div>

    <!-- Center Segmented Navigation -->
    <nav class="nav-bar">
      <button id="nav-btn-tts" class="nav-tab active" onclick="switchTab('tts')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/></svg>
        <span>Live Console</span>
      </button>
      <button id="nav-btn-overlay" class="nav-tab" onclick="switchTab('overlay')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg>
        <span>Studio Overlay</span>
      </button>
      <button id="nav-btn-store" class="nav-tab" onclick="switchTab('store')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
        <span>Voice Store</span>
        <span class="nav-count">13</span>
      </button>
      <button id="nav-btn-settings" class="nav-tab" onclick="switchTab('settings')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" x2="20" y1="21" y2="21"/><line x1="4" x2="20" y1="14" y2="14"/><line x1="4" x2="20" y1="7" y2="7"/><circle cx="9" cy="14" r="2"/><circle cx="15" cy="7" r="2"/><circle cx="15" cy="21" r="2"/></svg>
        <span>Audio &amp; Settings</span>
      </button>
    </nav>

    <!-- Right Telemetry -->
    <div class="telemetry-strip">
      <button id="update-pill" class="update-pill" onclick="openUpdateModal()">
        <span class="update-pulse"></span>
        <span id="update-pill-text">Update Ready</span>
      </button>
      <div id="latency-badge" class="telemetry-badge latency">
        <span>0ms Local CPU</span>
      </div>
      <div id="status-badge" class="telemetry-badge offline">
        <span class="status-dot"></span>
        <span id="status-text">DISCONNECTED</span>
      </div>
    </div>
  </header>

  <!-- TAB 1: Live Console (3-Column Viewport-Fitted Deck) -->
  <div id="tab-tts" class="tab-content active">
    <div class="console-grid">

      <!-- COLUMN 1: Stream & Voice Channel -->
      <div class="console-col">
        <!-- 1. Stream Connection -->
        <div class="card">
          <div class="card-title">
            <span>Stream Connection</span>
            <span class="card-tag">Read-Only Room</span>
          </div>
          <label for="username-input">TikTok @Username</label>
          <div class="input-prefix-box">
            <span class="input-prefix-label">@</span>
            <input type="text" id="username-input" placeholder="your_tiktok_handle" />
          </div>
          <div class="btn-row">
            <button class="btn-live" style="flex: 2;" onclick="connectStream()">Connect Live</button>
            <button class="btn-secondary" style="flex: 1;" onclick="disconnectStream()">Disconnect</button>
          </div>
          <p id="status-msg" class="helper-text">Enter your public handle to start reading chat.</p>
        </div>

        <!-- 2. Active Speech Voice -->
        <div class="card">
          <div class="card-title">
            <span>Active Speech Voice</span>
            <span class="card-tag live">0ms Neural</span>
          </div>
          <label for="browser-voice-select">Voice Model</label>
          <select id="browser-voice-select" onchange="updateSettings()"></select>

          <div class="btn-row">
            <button class="btn-secondary" style="flex: 1;" id="btn-test-active-voice" onclick="testActiveVoiceSample()">
              <span id="test-voice-icon">▶</span>
              <span id="test-voice-text">Audition Active Voice</span>
              <div id="test-voice-wave" class="equalizer-wave" style="display: none; margin-left: 4px;">
                <div class="eq-bar"></div>
                <div class="eq-bar"></div>
                <div class="eq-bar"></div>
                <div class="eq-bar"></div>
              </div>
            </button>
            <button class="btn-secondary" onclick="switchTab('store')" title="Browse 13 Offline Voices">
              <span>+ Voices</span>
            </button>
          </div>

          <div style="margin-top: 13px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.05);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 7px;">
              <label style="margin-bottom: 0;">Master Speech Volume</label>
              <span id="vol-label" style="font-size: 11.5px; font-weight: 600; color: var(--accent); font-family: var(--font-mono);">100%</span>
            </div>
            <input type="range" id="vol-slider" min="0" max="1" step="0.05" value="1" oninput="changeVolume(this.value)" />
          </div>
        </div>

        <!-- 3. Streamer Soundboard -->
        <div class="card card-fill">
          <div class="card-title">
            <span>Quick Soundboard</span>
            <span class="card-tag">6 Instant Pads</span>
          </div>
          <div class="preset-grid">
            <button type="button" class="sound-pad" onclick="applyPreset('Welcome to the livestream everyone!')">
              <span class="sound-pad-dot"></span><span>Welcome In</span>
            </button>
            <button type="button" class="sound-pad" onclick="applyPreset('Thank you so much for the gifts and support!')">
              <span class="sound-pad-dot"></span><span>Gift Thanks</span>
            </button>
            <button type="button" class="sound-pad" onclick="applyPreset('Let\'s go! Drop some hype in the chat right now!')">
              <span class="sound-pad-dot"></span><span>Hype Chat</span>
            </button>
            <button type="button" class="sound-pad" onclick="applyPreset('Good game everyone! What an intense round!')">
              <span class="sound-pad-dot"></span><span>GG Match</span>
            </button>
            <button type="button" class="sound-pad" onclick="applyPreset('Massive shoutout to our top gifter on the leaderboard!')">
              <span class="sound-pad-dot"></span><span>Top Gifter</span>
            </button>
            <button type="button" class="sound-pad" onclick="applyPreset('We just smashed our stream goal! You guys are incredible!')">
              <span class="sound-pad-dot"></span><span>Goal Hit</span>
            </button>
          </div>
          <div style="margin-top: auto; display: flex; gap: 6px;">
            <input type="text" id="test-text" placeholder="Type custom speech announcement..." onkeydown="if(event.key==='Enter')sendTestSpeech()" />
            <button class="btn-primary" style="flex-shrink: 0;" onclick="sendTestSpeech()">Speak</button>
          </div>
        </div>
      </div>

      <!-- COLUMN 2: Audience Access & Moderation -->
      <div class="console-col">
        <!-- 1. Audience Gate -->
        <div class="card">
          <div class="card-title">
            <span>Audience Access Gate</span>
            <span class="card-tag">Who Can Speak</span>
          </div>
          <div class="role-grid">
            <button type="button" class="role-btn active" id="rb-anyone" onclick="setRole('anyone')">Everyone</button>
            <button type="button" class="role-btn" id="rb-followers" onclick="setRole('followers')">Followers</button>
            <button type="button" class="role-btn" id="rb-fan_club" onclick="setRole('fan_club')">Fan Club</button>
            <button type="button" class="role-btn" id="rb-subs" onclick="setRole('subs')">Subs</button>
          </div>
          <select id="role-filter" onchange="syncRoleFromSelect()" style="display: none;">
            <option value="anyone">Everyone</option>
            <option value="followers">Followers Only</option>
            <option value="fan_club">Fan Club Only</option>
            <option value="subs">Subscribers Only</option>
          </select>

          <div class="grid-2col" style="margin-bottom: 8px;">
            <div>
              <label for="command-prefix">Command Prefix</label>
              <select id="command-prefix" onchange="updateSettings()">
                <option value="">All messages</option>
                <option value="!">! (!hello)</option>
                <option value=".">. (.hello)</option>
                <option value="/">/ (/hello)</option>
              </select>
            </div>
            <div>
              <label for="min-fan-level">Min Fan Level</label>
              <input type="number" id="min-fan-level" min="0" max="50" value="0" onchange="updateSettings()" />
            </div>
          </div>

          <div class="toggle-row">
            <label for="fan-announce-toggle">Announce New Fans &amp; Subs</label>
            <label class="switch">
              <input type="checkbox" id="fan-announce-toggle" checked onchange="updateSettings()" />
              <span class="slider"></span>
            </label>
          </div>
        </div>

        <!-- 2. Gift Callouts -->
        <div class="card">
          <div class="card-title">
            <span>Gift Callouts &amp; Alerts</span>
            <span class="card-tag">Live Events</span>
          </div>
          <div class="toggle-row">
            <label for="gift-tts-toggle">Speak Gift Announcements</label>
            <label class="switch">
              <input type="checkbox" id="gift-tts-toggle" checked onchange="updateSettings()" />
              <span class="slider"></span>
            </label>
          </div>
          <div class="toggle-row">
            <label for="gift-sound-toggle">Play Gift Chime Sound</label>
            <label class="switch">
              <input type="checkbox" id="gift-sound-toggle" checked onchange="updateSettings()" />
              <span class="slider"></span>
            </label>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.04);">
            <label for="gift-min-coins" style="margin-bottom: 0;">Minimum Gift Coins</label>
            <input type="number" id="gift-min-coins" min="1" max="10000" value="1" style="width: 96px; text-align: right;" onchange="updateSettings()" />
          </div>
        </div>

        <!-- 3. Safety & Anti-Spam -->
        <div class="card card-fill">
          <div class="card-title">
            <span>Safety &amp; Anti-Spam</span>
            <span class="card-tag">Auto-Defense</span>
          </div>
          <div class="toggle-row" style="margin-bottom: 8px;">
            <label for="spam-automute-toggle">Auto-Mute Spammers (3 msgs / 10s)</label>
            <label class="switch">
              <input type="checkbox" id="spam-automute-toggle" checked onchange="updateSettings()" />
              <span class="slider"></span>
            </label>
          </div>

          <div class="grid-2col" style="margin-bottom: 10px;">
            <div>
              <label for="cooldown-input">Cooldown (sec)</label>
              <input type="number" id="cooldown-input" value="5" min="1" max="60" onchange="updateSettings()" />
            </div>
            <div>
              <label for="maxlen-input">Max Characters</label>
              <input type="number" id="maxlen-input" value="120" min="20" max="300" onchange="updateSettings()" />
            </div>
          </div>

          <div style="margin-top: auto;">
            <label for="banned-input">Blocked Words (comma separated)</label>
            <input type="text" id="banned-input" placeholder="word1, word2..." onchange="updateSettings()" />
          </div>
        </div>
      </div>

      <!-- COLUMN 3: On-Air Monitor & Live Activity Feed -->
      <div class="console-col-feed">
        <!-- On-Air Monitor -->
        <div class="card now-speaking-card">
          <div class="card-title">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="color: var(--accent); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.06em;">ON AIR MONITOR</span>
              <div id="spk-wave" class="equalizer-wave">
                <div class="eq-bar"></div>
                <div class="eq-bar"></div>
                <div class="eq-bar"></div>
                <div class="eq-bar"></div>
                <div class="eq-bar"></div>
              </div>
            </div>
            <span class="version-pill">Queue: <b id="queue-count" style="color: #fff;">0</b></span>
          </div>
          <div class="speaking-display">
            <div id="spk-user" class="speaking-user" style="display: none;"></div>
            <div id="spk-text" class="speaking-text speaking-idle">No audio currently playing. Waiting for live chat...</div>
          </div>
          <div class="btn-row">
            <button class="btn-danger" style="flex: 1;" onclick="skipAudio()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" x2="19" y1="5" y2="19"/></svg>
              <span>Skip Current</span>
            </button>
            <button class="btn-secondary" style="flex: 1;" onclick="clearQueue()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
              <span>Clear Queue</span>
            </button>
          </div>
        </div>

        <!-- Live Activity Stream -->
        <div class="card card-fill">
          <div class="card-title" style="flex-wrap: wrap; gap: 8px;">
            <span>Live Chat &amp; Gift Feed</span>
            <div style="display: flex; gap: 4px;">
              <button class="chip active" id="flt-all" onclick="filterLog('all')">All</button>
              <button class="chip" id="flt-spoken" onclick="filterLog('spoken')">Spoken</button>
              <button class="chip" id="flt-gifts" onclick="filterLog('gifts')">Gifts</button>
              <button class="chip" id="flt-blocked" onclick="filterLog('blocked')">Filtered</button>
            </div>
          </div>
          <div id="log-list" class="log-container">
            <div class="log-empty">
              Live viewer comments and gift alerts will stream here when connected...
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>

  <!-- TAB 2: TikTok Studio Overlay -->
  <div id="tab-overlay" class="tab-content">
    <div style="display: grid; grid-template-columns: 440px 1fr; gap: 16px; flex: 1; min-height: 0;">
      <div class="card" style="display: flex; flex-direction: column; justify-content: space-between;">
        <div>
          <div class="card-title">
            <span>TikTok Live Studio Browser Source</span>
            <span class="card-tag live">Alpha Transparent</span>
          </div>
          <p style="font-size: 12.5px; color: var(--text-secondary); line-height: 1.55; margin-bottom: 16px;">
            Display floating viewer subtitles, fan level badges, and gift alerts directly over your gameplay or camera in TikTok Live Studio.
          </p>

          <div style="background: #000000; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 14px; margin-bottom: 16px;">
            <div style="font-family: var(--font-mono); font-size: 10.5px; color: var(--accent); margin-bottom: 8px;">SETUP IN 3 STEPS</div>
            <ol style="font-size: 12px; color: #d4d4d8; margin-left: 16px; line-height: 1.85;">
              <li>Click <b>Add Source</b> in TikTok Live Studio.</li>
              <li>Choose <b>Link / Browser Source</b>.</li>
              <li>Paste the URL below and set resolution to <b>850 × 250</b>.</li>
            </ol>
          </div>

          <label for="overlay-url">Local Overlay URL</label>
          <div style="display: flex; gap: 8px; margin-bottom: 14px;">
            <input type="text" id="overlay-url" readonly style="font-family: var(--font-mono); font-size: 12px; color: var(--accent);" />
            <button class="btn-primary" style="flex-shrink: 0;" onclick="copyOverlayUrl()">Copy URL</button>
          </div>
        </div>

        <div class="btn-row">
          <button class="btn-secondary" style="flex: 1;" onclick="testOverlaySubtitle()">Trigger Test Subtitle</button>
          <button class="btn-secondary" style="flex: 1;" onclick="testOverlayGift()">Trigger Test Gift</button>
        </div>
      </div>

      <!-- Live Stage Preview -->
      <div class="card" style="display: flex; flex-direction: column;">
        <div class="card-title">
          <span>Overlay Stage Preview</span>
          <span class="card-tag">Real-time HUD Simulator</span>
        </div>
        <div class="bg-dots-stage" style="border: 1px solid var(--border-subtle); border-radius: var(--radius-md); flex: 1; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; padding: 28px; position: relative; overflow: hidden;">
          <div style="position: absolute; top: 14px; left: 16px; font-family: var(--font-mono); font-size: 10.5px; color: var(--text-muted);">TRANSPARENT ALPHA STAGE · 850 × 250</div>

          <div id="sim-gift" style="display: none; position: absolute; top: 28px; background: linear-gradient(135deg, #f59e0b, #d97706); border: 1px solid #fde68a; border-radius: 12px; padding: 10px 20px; color: #000; font-weight: 700; font-size: 13.5px; box-shadow: 0 12px 30px rgba(245, 158, 11, 0.35);">
            GamerFan99 sent Rose x10
          </div>

          <div id="sim-subtitle" style="display: flex; align-items: center; gap: 14px; background: rgba(9, 9, 11, 0.94); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 14px; padding: 14px 20px; width: 88%; max-width: 640px; box-shadow: 0 20px 50px rgba(0,0,0,0.85);">
            <div class="equalizer-wave eq-active" style="height: 18px;">
              <div class="eq-bar"></div>
              <div class="eq-bar"></div>
              <div class="eq-bar"></div>
              <div class="eq-bar"></div>
            </div>
            <div>
              <div style="font-size: 12px; font-weight: 600; color: var(--accent); display: flex; align-items: center; gap: 6px;">
                <span class="badge-fan" style="margin-right: 0;">LV.7</span>
                <span>jordan_fps</span>
              </div>
              <div id="sim-sub-text" style="font-size: 15px; font-weight: 500; color: #fff; margin-top: 2px;">what voice model is this?? sounds so clean</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 3: Voice Store (13 Neural Offline Voices) -->
  <div id="tab-store" class="tab-content">
    <div class="card" style="flex: 1; display: flex; flex-direction: column; min-height: 0;">
      <div class="store-filter-bar">
        <div style="display: flex; flex-wrap: wrap; gap: 5px;" id="store-cat-buttons">
          <button class="chip active" data-cat="all" onclick="filterStoreCategory('all')">All Voices (13)</button>
          <button class="chip" data-cat="gaming" onclick="filterStoreCategory('gaming')">Gaming &amp; Hype</button>
          <button class="chip" data-cat="deep" onclick="filterStoreCategory('deep')">Deep &amp; Radio</button>
          <button class="chip" data-cat="chill" onclick="filterStoreCategory('chill')">Chill &amp; Story</button>
          <button class="chip" data-cat="warm" onclick="filterStoreCategory('warm')">Warm &amp; Friendly</button>
          <button class="chip" data-cat="accents" onclick="filterStoreCategory('accents')">UK &amp; Accents</button>
          <button class="chip" data-cat="starred" onclick="filterStoreCategory('starred')">Starred</button>
        </div>
        <div class="store-search-box">
          <input type="text" id="store-search-input" placeholder="Search voice or style..." oninput="handleStoreSearch(this.value)" />
        </div>
      </div>

      <div id="voice-store-grid" style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; overflow-y: auto; padding-right: 4px;"></div>
    </div>
  </div>

  <!-- TAB 4: Settings & Audio Hardware Routing -->
  <div id="tab-settings" class="tab-content">
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
      <div class="card">
        <div class="card-title">
          <span>Audio Output &amp; Mixer Routing</span>
          <span class="card-tag">Hardware</span>
        </div>
        <p style="font-size: 12px; color: var(--text-secondary); margin-bottom: 14px; line-height: 1.5;">
          Route speech to your default desktop speakers or a dedicated virtual channel (Voicemeeter, Elgato Wave Link, SteelSeries Sonar, GoXLR).
        </p>
        <label for="audio-device-select">Output Device</label>
        <select id="audio-device-select" style="margin-bottom: 16px;" onchange="changeAudioDevice()"></select>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 7px;">
          <label style="margin-bottom: 0;">Master Speech Volume</label>
          <span id="set-vol-label" style="font-size: 11.5px; font-weight: 600; color: var(--accent); font-family: var(--font-mono);">100%</span>
        </div>
        <input type="range" id="set-vol-slider" min="0" max="1" step="0.05" value="1" style="margin-bottom: 16px;" oninput="changeVolume(this.value)" />

        <div class="btn-row">
          <button class="btn-secondary" onclick="testAudioDevice()">Play Test Chime</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          <span>Software Updates &amp; Runtime</span>
          <span class="card-tag">System</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; padding: 12px; background: #000; border: 1px solid var(--border-subtle); border-radius: var(--radius-md);">
          <div>
            <div style="font-size: 13px; font-weight: 600; color: #fff;">TTS Live Studio</div>
            <div style="font-size: 11.5px; color: var(--text-secondary); margin-top: 2px;">Installed Version: <b id="settings-version" style="color: var(--accent); font-family: var(--font-mono);">v1.9.9</b></div>
          </div>
          <button class="btn-secondary" onclick="checkForUpdates(true)">Check for Update</button>
        </div>
        <div id="settings-update-status" style="font-size: 12px; color: var(--text-secondary); margin-bottom: 16px;">You are running the latest release.</div>

        <div style="border-top: 1px solid var(--border-subtle); padding-top: 14px;">
          <div style="font-family: var(--font-mono); font-size: 10.5px; color: var(--text-muted); margin-bottom: 5px;">LOCAL ENGINE TELEMETRY</div>
          <div style="font-size: 12px; color: var(--text-secondary); line-height: 1.55;">
            Local WebSocket &amp; Overlay Port: <b style="color: #fff; font-family: var(--font-mono);" id="settings-port">28730</b><br/>
            Synthesis Engine: <b style="color: #34d399;">Piper Offline Neural CPU (0ms Cloud Lag)</b>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Update Changelog Modal -->
  <div id="update-modal" class="modal-backdrop">
    <div class="modal-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
        <h3 id="modal-title" style="font-size: 15px; font-weight: 600; color: #fff;">Update Available</h3>
        <button class="chip" onclick="closeUpdateModal()" style="padding: 4px 10px;">✕</button>
      </div>
      <div id="modal-changelog" style="font-size: 12.5px; color: #d4d4d8; line-height: 1.6; max-height: 220px; overflow-y: auto; margin-bottom: 18px;"></div>
      <div style="display: flex; gap: 8px;">
        <button class="btn-primary" style="flex: 2;" id="modal-update-btn" onclick="installUpdate()">Update &amp; Restart</button>
        <button class="btn-secondary" style="flex: 1;" onclick="closeUpdateModal()">Later</button>
      </div>
    </div>
  </div>

  <script>
    const STORE_CATALOG = [
      {
        id: "nova",
        name: "Nova",
        subtitle: "High-Energy Anime Female",
        badge: "Anime / Hype",
        category: "gaming",
        badgeStyle: "",
        desc: "Expressive, cheerful, and fast-paced. Perfect for hype gaming and interactive chat reactions.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/amy/medium/speaker_0.mp3"
      },
      {
        id: "kael",
        name: "Kael",
        subtitle: "Deep FM Radio Announcer",
        badge: "Deep / Radio",
        category: "deep",
        badgeStyle: "",
        desc: "Resonant, bass-heavy broadcast DJ voice. Ideal for chill late-night talk streams and podcasting.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/bryce/medium/speaker_0.mp3"
      },
      {
        id: "arthur",
        name: "Arthur",
        subtitle: "Distinguished British Butler",
        badge: "British / Formal",
        category: "accents",
        badgeStyle: "",
        desc: "Polite, crisp UK English with formal tone. Reads chat comments with butler-like elegance.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_GB/alan/medium/speaker_0.mp3"
      },
      {
        id: "viper",
        name: "Viper",
        subtitle: "Esports Shoutcaster",
        badge: "Gaming / FPS",
        category: "gaming",
        badgeStyle: "",
        desc: "Fast, hype tournament commentator style. Built for high-kill FPS and battle royale streams.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/ryan/medium/speaker_0.mp3"
      },
      {
        id: "luna",
        name: "Luna",
        subtitle: "Calm & Cozy Storyteller",
        badge: "Cozy / ASMR",
        category: "chill",
        badgeStyle: "",
        desc: "Soft, gentle, relaxing voice. Ideal for art streams, cozy farming games, and quiet evening streams.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/kathleen/medium/speaker_0.mp3"
      },
      {
        id: "thor",
        name: "Thor",
        subtitle: "Nordic Warrior / Northern Male",
        badge: "Fantasy / Epic",
        category: "accents",
        badgeStyle: "",
        desc: "Thunderous, roaring, epic character. Turns simple chat messages into battle declarations.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_GB/northern_english_male/medium/speaker_0.mp3"
      },
      {
        id: "danny",
        name: "Danny",
        subtitle: "Gamer / Teen Hype",
        badge: "US / Teen Hype",
        category: "gaming",
        badgeStyle: "",
        desc: "Youthful, energetic US English voice. Awesome for gaming banter, fast-paced stream hype, and jokes.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/danny/low/speaker_0.mp3"
      },
      {
        id: "lessac",
        name: "Lessac",
        subtitle: "Studio Narrator / Pro Audiobook",
        badge: "US / Studio Clear",
        category: "chill",
        badgeStyle: "",
        desc: "Pristine, neutral, studio-grade narration voice. Flawlessly clear pronunciation for reading long questions and viewer tips.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/lessac/medium/speaker_0.mp3"
      },
      {
        id: "joe",
        name: "Joe",
        subtitle: "Chill Streamer / Casual Male",
        badge: "US / Casual Chill",
        category: "chill",
        badgeStyle: "",
        desc: "Laid-back, conversational everyday guy. Feels like a stream co-host chatting on Discord.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/joe/medium/speaker_0.mp3"
      },
      {
        id: "kristin",
        name: "Kristin",
        subtitle: "Warm & Cheerful Female",
        badge: "US / Warm & Friendly",
        category: "warm",
        badgeStyle: "",
        desc: "Friendly, inviting, and upbeat female voice. Great for welcome greetings and donor thank-yous.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/kristin/medium/speaker_0.mp3"
      },
      {
        id: "mike",
        name: "Mike",
        subtitle: "Deep Baritone / Esports Caster",
        badge: "US / Deep Caster",
        category: "deep",
        badgeStyle: "",
        desc: "Deep, authoritative, cinematic male baritone. Gives substantial punch and weight to stream commentary.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_US/mike/medium/speaker_0.mp3"
      },
      {
        id: "alba",
        name: "Alba",
        subtitle: "Scottish Storyteller Female",
        badge: "Scottish / Character",
        category: "accents",
        badgeStyle: "",
        desc: "Distinctive Scottish accent with lyrical warmth and charm. Captivating character voice for roleplay and storytelling.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_GB/alba/medium/speaker_0.mp3"
      },
      {
        id: "cori",
        name: "Cori",
        subtitle: "British Queen's English Female",
        badge: "UK / Royal Eloquent",
        category: "accents",
        badgeStyle: "",
        desc: "Crisp, pristine Received Pronunciation British female. Highly articulate, elegant, and sophisticated.",
        sampleUrl: "https://rhasspy.github.io/piper-samples/samples/en/en_GB/cori/medium/speaker_0.mp3"
      }
    ];

    let currentEngine = "instant";
    let currentVolume = 1.0;
    let savedNativeVoice = "";
    let selectedAudioDevice = "default";
    let audioQueue = [];
    let isPlaying = false;
    let activeAudio = null;
    let previewAudio = null;
    let currentPreviewId = null;
    let browserVoices = [];
    let installedStoreVoices = [];
    let starredVoices = [];
    let latestReleaseNotes = "";
    let latestVersionStr = "";
    let currentStoreCategory = "all";
    let storeSearchQuery = "";
    let currentLogFilter = 'all';

    function setRole(role) {
      const sel = document.getElementById('role-filter');
      if (sel) {
        sel.value = role;
        updateRoleButtons(role);
        updateSettings();
      }
    }
    function updateRoleButtons(role) {
      document.querySelectorAll('.role-btn').forEach(b => b.classList.remove('active'));
      const activeBtn = document.getElementById('rb-' + role);
      if (activeBtn) activeBtn.classList.add('active');
    }
    function syncRoleFromSelect() {
      const sel = document.getElementById('role-filter');
      if (sel) updateRoleButtons(sel.value);
    }

    function switchTab(tabId) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
      const content = document.getElementById('tab-' + tabId);
      const btn = document.getElementById('nav-btn-' + tabId);
      if (content) content.classList.add('active');
      if (btn) btn.classList.add('active');
    }

    function playGiftChime() {
      try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (audioCtx.setSinkId && selectedAudioDevice !== 'default') {
          audioCtx.setSinkId(selectedAudioDevice);
        }
        const now = audioCtx.currentTime;
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(880, now);
        osc.frequency.exponentialRampToValueAtTime(1320, now + 0.12);
        gain.gain.setValueAtTime(currentVolume * 0.4, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(now);
        osc.stop(now + 0.36);
      } catch (e) {}
    }

    let ws = null;
    let wsReconnectTimer = null;

    function initWebSocket() {
      if (ws) {
        try { ws.close(); } catch (e) {}
      }
      ws = new WebSocket(`ws://${location.host}/ws`);
      ws.onopen = () => {
        if (wsReconnectTimer) {
          clearTimeout(wsReconnectTimer);
          wsReconnectTimer = null;
        }
      };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWsMessage(data);
        } catch (e) {}
      };
      ws.onclose = () => {
        if (!wsReconnectTimer) {
          wsReconnectTimer = setTimeout(initWebSocket, 2000);
        }
      };
      ws.onerror = () => {};
    }

    setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: "ping" })); } catch (e) {}
      }
    }, 15000);

    initWebSocket();

    async function checkForUpdates(manual = false) {
      try {
        const res = await fetch('/api/check-update');
        const data = await res.json();
        if (data.has_update) {
          latestReleaseNotes = data.release_notes || "• Performance improvements and bug fixes.";
          latestVersionStr = data.latest_version;
          const pill = document.getElementById('update-pill');
          if (pill) {
            pill.style.display = 'inline-flex';
            document.getElementById('update-pill-text').textContent = `v${data.latest_version} Available`;
          }
          const stEl = document.getElementById('settings-update-status');
          if (stEl) {
            stEl.innerHTML = `<span style="color:#34d399;">Update v${data.latest_version} available.</span> <button class="btn-primary" style="margin-left:8px; padding:4px 10px; font-size:11px;" onclick="openUpdateModal()">Install Update</button>`;
          }
          if (manual) openUpdateModal();
        } else {
          if (manual) alert("TTS Live Studio is up to date (v" + data.current_version + ").");
        }
      } catch (e) {}
    }

    function openUpdateModal() {
      document.getElementById('modal-title').textContent = `What's New in v${latestVersionStr || 'Latest'}`;
      const lines = latestReleaseNotes.split('\n').filter(l => l.trim().length > 0);
      let html = '<ul style="margin-left: 18px;">';
      lines.forEach(line => {
        html += `<li>${line.replace(/^[*-]\s*/, '')}</li>`;
      });
      html += '</ul>';
      document.getElementById('modal-changelog').innerHTML = html;
      document.getElementById('update-modal').style.display = 'flex';
    }

    function closeUpdateModal() {
      document.getElementById('update-modal').style.display = 'none';
    }

    async function installUpdate() {
      const btn = document.getElementById('modal-update-btn');
      btn.disabled = true;
      btn.textContent = "Preparing update...";
      try {
        const res = await fetch('/api/install-update', { method: 'POST' });
        const data = await res.json();
        if (data.status !== 'ok') {
          alert("Update error: " + data.message);
          btn.disabled = false;
          btn.textContent = "Update & Restart";
        }
      } catch (err) {
        alert("Update error: " + err);
        btn.disabled = false;
        btn.textContent = "Update & Restart";
      }
    }

    function populateBrowserVoices() {
      if ('speechSynthesis' in window) {
        browserVoices = window.speechSynthesis.getVoices() || [];
      } else {
        browserVoices = [];
      }
      const select = document.getElementById('browser-voice-select');
      if (!select) return;
      select.innerHTML = '';
      let matchedIndex = -1;

      const starredInstalled = STORE_CATALOG.filter(v => starredVoices.includes(v.id) && installedStoreVoices.includes(v.id));
      if (starredInstalled.length > 0) {
        const starGroup = document.createElement('optgroup');
        starGroup.label = "★ Starred Offline Voices";
        starredInstalled.forEach(v => {
          const opt = document.createElement('option');
          opt.value = "store:" + v.id;
          opt.textContent = `★ ${v.name} — ${v.subtitle}`;
          const isMatch = savedNativeVoice && (
            savedNativeVoice === ("store:" + v.id) ||
            savedNativeVoice === v.id ||
            savedNativeVoice.toLowerCase().includes(v.id) ||
            savedNativeVoice.toLowerCase().includes(v.name.toLowerCase())
          );
          if (isMatch) {
            opt.selected = true;
            matchedIndex = 9999;
          }
          starGroup.appendChild(opt);
        });
        select.appendChild(starGroup);
      }

      const nonStarredInstalled = installedStoreVoices.filter(id => !starredVoices.includes(id));
      if (nonStarredInstalled.length > 0) {
        const instGroup = document.createElement('optgroup');
        instGroup.label = "Installed Offline Voices (0ms)";
        nonStarredInstalled.forEach(vId => {
          const v = STORE_CATALOG.find(c => c.id === vId);
          const opt = document.createElement('option');
          opt.value = "store:" + vId;
          opt.textContent = `${v ? v.name : vId} — ${v ? v.subtitle : '0ms Offline'}`;
          const isMatch = savedNativeVoice && v && (
            savedNativeVoice === ("store:" + vId) ||
            savedNativeVoice === vId ||
            savedNativeVoice.toLowerCase().includes(vId) ||
            savedNativeVoice.toLowerCase().includes(v.name.toLowerCase())
          );
          if (isMatch) {
            opt.selected = true;
            matchedIndex = 9999;
          }
          instGroup.appendChild(opt);
        });
        select.appendChild(instGroup);
      }

      if (browserVoices.length > 0) {
        const osGroup = document.createElement('optgroup');
        osGroup.label = "Windows System Voices";
        browserVoices.forEach((v, i) => {
          const opt = document.createElement('option');
          opt.value = i;
          opt.textContent = `${v.name} (${v.lang})`;
          if (savedNativeVoice && (v.name === savedNativeVoice || savedNativeVoice.includes(v.name))) {
            matchedIndex = i;
            opt.selected = true;
          } else if (!savedNativeVoice && matchedIndex === -1 && (v.default || v.name.includes('Natural') || v.lang.startsWith('en'))) {
            matchedIndex = i;
            opt.selected = true;
          }
          osGroup.appendChild(opt);
        });
        select.appendChild(osGroup);
      }

      if (matchedIndex >= 0 && matchedIndex < 9999 && !select.value.startsWith('store:')) {
        select.value = matchedIndex;
      }
    }

    function filterStoreCategory(cat) {
      currentStoreCategory = cat;
      document.querySelectorAll('#store-cat-buttons .chip').forEach(btn => {
        if (btn.getAttribute('data-cat') === cat) btn.classList.add('active');
        else btn.classList.remove('active');
      });
      renderVoiceStoreGrid();
    }

    function handleStoreSearch(val) {
      storeSearchQuery = (val || '').toLowerCase().trim();
      renderVoiceStoreGrid();
    }

    function renderVoiceStoreGrid() {
      const container = document.getElementById('voice-store-grid');
      if (!container) return;

      let filtered = STORE_CATALOG.filter(v => {
        if (currentStoreCategory === 'starred') {
          if (!starredVoices.includes(v.id)) return false;
        } else if (currentStoreCategory !== 'all') {
          if (v.category !== currentStoreCategory) return false;
        }
        if (storeSearchQuery) {
          const hay = `${v.name} ${v.subtitle} ${v.desc} ${v.badge}`.toLowerCase();
          if (!hay.includes(storeSearchQuery)) return false;
        }
        return true;
      });

      filtered.sort((a, b) => {
        const aStarred = starredVoices.includes(a.id);
        const bStarred = starredVoices.includes(b.id);
        if (aStarred && !bStarred) return -1;
        if (!aStarred && bStarred) return 1;
        return 0;
      });

      if (filtered.length === 0) {
        container.innerHTML = `
          <div style="grid-column: 1 / -1; text-align: center; padding: 48px; color: var(--text-muted);">
            No voices match your search filter.
          </div>
        `;
        return;
      }

      container.innerHTML = filtered.map(v => {
        const isStarred = starredVoices.includes(v.id);
        const isInstalled = installedStoreVoices.includes(v.id);
        const isPlayingThis = (currentPreviewId === v.id);

        let actionHtml = '';
        if (isInstalled) {
          actionHtml = `
            <button class="btn-secondary" style="font-size: 11.5px; flex: 2; cursor: default; background: rgba(16, 185, 129, 0.12); color: #34d399; border-color: rgba(16, 185, 129, 0.28);" disabled>
              ✓ Installed
            </button>
            <button class="btn-danger" style="font-size: 11.5px; flex: 1; padding: 7px 10px;" onclick="uninstallVoiceStore('${v.id}')">
              Remove
            </button>
          `;
        } else {
          actionHtml = `
            <button class="btn-primary" style="font-size: 11.5px; flex: 1;" id="btn-install-${v.id}" onclick="installVoiceStore('${v.id}')">
              Install Voice
            </button>
          `;
        }

        return `
          <div class="voice-card ${isStarred ? 'starred' : ''}">
            <div>
              <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 8px;">
                <div>
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 15px; font-weight: 600; color: #fff; letter-spacing: -0.01em;">${v.name}</span>
                  </div>
                  <div style="font-size: 11.5px; color: var(--accent); margin-top: 1px;">${v.subtitle}</div>
                </div>
                <div style="display: flex; align-items: center; gap: 5px;">
                  <button class="star-btn ${isStarred ? 'active' : ''}" onclick="toggleStarVoice('${v.id}')" title="Pin voice to top">
                    ${isStarred ? '★' : '☆'}
                  </button>
                  <span class="voice-badge-tag">${v.badge}</span>
                </div>
              </div>

              <p style="font-size: 12px; color: var(--text-secondary); margin-bottom: 14px; line-height: 1.5;">
                ${v.desc}
              </p>
            </div>

            <div style="display: flex; gap: 7px;">
              <button class="btn-secondary" style="font-size: 11.5px; flex: 1;" onclick="togglePreviewVoice('${v.id}')">
                <span>${isPlayingThis ? 'Pause' : 'Play Sample'}</span>
                ${isPlayingThis ? `
                  <div class="equalizer-wave eq-active" style="height: 12px;">
                    <div class="eq-bar"></div>
                    <div class="eq-bar"></div>
                    <div class="eq-bar"></div>
                  </div>
                ` : ''}
              </button>
              ${actionHtml}
            </div>
          </div>
        `;
      }).join('');
    }

    function toggleStarVoice(vId) {
      const idx = starredVoices.indexOf(vId);
      if (idx >= 0) starredVoices.splice(idx, 1);
      else starredVoices.push(vId);
      renderVoiceStoreGrid();
      populateBrowserVoices();
      updateSettings();
    }

    function togglePreviewVoice(vId) {
      if (currentPreviewId === vId && previewAudio) {
        previewAudio.pause();
        previewAudio = null;
        currentPreviewId = null;
        renderVoiceStoreGrid();
        return;
      }
      if (previewAudio) {
        previewAudio.pause();
        previewAudio = null;
      }
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      const v = STORE_CATALOG.find(c => c.id === vId);
      if (!v || !v.sampleUrl) return;

      currentPreviewId = vId;
      previewAudio = new Audio(v.sampleUrl);
      previewAudio.volume = currentVolume;
      if (selectedAudioDevice && previewAudio.setSinkId && selectedAudioDevice !== 'default') {
        previewAudio.setSinkId(selectedAudioDevice).catch(() => {});
      }
      previewAudio.onended = () => {
        currentPreviewId = null;
        previewAudio = null;
        renderVoiceStoreGrid();
      };
      previewAudio.onerror = () => {
        currentPreviewId = null;
        previewAudio = null;
        renderVoiceStoreGrid();
      };
      previewAudio.play().catch(() => {
        currentPreviewId = null;
        previewAudio = null;
        renderVoiceStoreGrid();
      });
      renderVoiceStoreGrid();
    }

    async function installVoiceStore(vId) {
      const btn = document.getElementById('btn-install-' + vId);
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Installing...";
      }
      try {
        const res = await fetch('/api/install-voice', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ voice_id: vId })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          if (!installedStoreVoices.includes(vId)) installedStoreVoices.push(vId);
          savedNativeVoice = "store:" + vId;
          renderVoiceStoreGrid();
          populateBrowserVoices();
        } else {
          alert("Failed to install voice: " + (data.message || "Unknown error"));
          renderVoiceStoreGrid();
        }
      } catch (e) {
        alert("Install error: " + e);
        renderVoiceStoreGrid();
      }
    }

    async function uninstallVoiceStore(vId) {
      try {
        const res = await fetch('/api/uninstall-voice', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ voice_id: vId })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          installedStoreVoices = installedStoreVoices.filter(id => id !== vId);
          if (savedNativeVoice === "store:" + vId || savedNativeVoice === vId) {
            savedNativeVoice = "";
          }
          renderVoiceStoreGrid();
          populateBrowserVoices();
        } else {
          alert("Failed to uninstall voice: " + (data.message || "Unknown error"));
        }
      } catch (e) {
        alert("Uninstall error: " + e);
      }
    }

    function b64toBlob(b64Data, contentType) {
      contentType = contentType || 'audio/wav';
      const byteCharacters = atob(b64Data);
      const byteArrays = [];
      for (let offset = 0; offset < byteCharacters.length; offset += 512) {
        const slice = byteCharacters.slice(offset, offset + 512);
        const byteNumbers = new Array(slice.length);
        for (let i = 0; i < slice.length; i++) {
          byteNumbers[i] = slice.charCodeAt(i);
        }
        byteArrays.push(new Uint8Array(byteNumbers));
      }
      return new Blob(byteArrays, { type: contentType });
    }

    function enqueueAudio(task) {
      audioQueue.push(task);
      updateQueue(audioQueue.length + (isPlaying ? 1 : 0));
      if (!isPlaying) {
        processNextInQueue();
      }
    }

    function processNextInQueue() {
      if (audioQueue.length === 0) {
        isPlaying = false;
        updateQueue(0);
        return;
      }
      isPlaying = true;
      const nextTask = audioQueue.shift();
      updateQueue(audioQueue.length + 1);
      if (nextTask.type === 'piper') playPiperAudio(nextTask.data);
      else if (nextTask.type === 'instant') speakInstant(nextTask.data);
    }

    function playPiperAudio(item) {
      const userEl = document.getElementById('spk-user');
      const textEl = document.getElementById('spk-text');
      const waveEl = document.getElementById('spk-wave');
      if (userEl) {
        userEl.style.display = 'block';
        userEl.textContent = '@' + (item.user || 'voice').replace(/^@/, '');
      }
      if (textEl) {
        textEl.className = 'speaking-text';
        textEl.textContent = item.display || item.text;
      }
      if (waveEl) waveEl.classList.add('eq-active');

      try {
        const blob = b64toBlob(item.audio_b64, 'audio/wav');
        const blobUrl = URL.createObjectURL(blob);
        activeAudio = new Audio(blobUrl);
        if (activeAudio.setSinkId && selectedAudioDevice && selectedAudioDevice !== 'default') {
          activeAudio.setSinkId(selectedAudioDevice).catch(() => {});
        }
        activeAudio.volume = currentVolume;
        activeAudio.onended = () => {
          URL.revokeObjectURL(blobUrl);
          finishPlay();
        };
        activeAudio.onerror = () => {
          URL.revokeObjectURL(blobUrl);
          finishPlay();
        };
        activeAudio.play().catch(() => {
          URL.revokeObjectURL(blobUrl);
          finishPlay();
        });
      } catch (err) {
        finishPlay();
      }
    }

    function speakSystemVoice(text, voiceName) {
      if (!('speechSynthesis' in window)) {
        finishPlay();
        return;
      }
      try {
        window.speechSynthesis.cancel();
        if (window.speechSynthesis.resume) window.speechSynthesis.resume();
      } catch (e) {}

      const userEl = document.getElementById('spk-user');
      const textEl = document.getElementById('spk-text');
      const waveEl = document.getElementById('spk-wave');
      if (userEl) {
        userEl.style.display = 'block';
        userEl.textContent = voiceName || 'System Voice';
      }
      if (textEl) {
        textEl.className = 'speaking-text';
        textEl.textContent = text;
      }
      if (waveEl) waveEl.classList.add('eq-active');

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.volume = currentVolume;
      utterance.rate = 1.0;
      utterance.pitch = 1.0;

      const targetName = voiceName || savedNativeVoice;
      let targetVoice = null;
      if (targetName && browserVoices.length > 0) {
        targetVoice = browserVoices.find(v => v.name === targetName || targetName.includes(v.name));
      }
      if (!targetVoice) {
        const selectEl = document.getElementById('browser-voice-select');
        const selectVal = selectEl ? selectEl.value : '';
        const idx = parseInt(selectVal);
        if (!isNaN(idx) && browserVoices[idx]) targetVoice = browserVoices[idx];
      }
      if (targetVoice) utterance.voice = targetVoice;

      const safetyTimer = setTimeout(() => {
        finishPlay();
      }, Math.max(6000, text.length * 150));

      utterance.onend = () => {
        clearTimeout(safetyTimer);
        finishPlay();
      };
      utterance.onerror = () => {
        clearTimeout(safetyTimer);
        finishPlay();
      };

      window.speechSynthesis.speak(utterance);
    }

    function speakInstant(item) {
      speakSystemVoice(item.text, item.voice || savedNativeVoice);
    }

    async function testActiveVoiceSample() {
      const icon = document.getElementById('test-voice-icon');
      const txt = document.getElementById('test-voice-text');
      const wave = document.getElementById('test-voice-wave');
      if (icon) icon.textContent = "•";
      if (txt) txt.textContent = "Speaking Sample...";
      if (wave) { wave.style.display = "inline-flex"; wave.classList.add("eq-active"); }

      const testPhrase = "Hello! This voice is ready for your TikTok livestream.";
      try {
        const res = await fetch('/api/speak', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: testPhrase })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          if (data.is_piper && data.audio_b64) {
            enqueueAudio({
              type: 'piper',
              data: { user: "Voice Preview", display: testPhrase, audio_b64: data.audio_b64 }
            });
          } else {
            enqueueAudio({
              type: 'instant',
              data: { text: testPhrase, voice: data.voice }
            });
          }
        }
      } catch (err) {
      } finally {
        setTimeout(() => {
          if (icon) icon.textContent = "▶";
          if (txt) txt.textContent = "Audition Active Voice";
          if (wave) { wave.style.display = "none"; wave.classList.remove("eq-active"); }
        }, 1800);
      }
    }

    if ('speechSynthesis' in window) {
      speechSynthesis.onvoiceschanged = populateBrowserVoices;
      populateBrowserVoices();
    }

    async function populateAudioDevices() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioOutputs = devices.filter(d => d.kind === 'audiooutput');
        const select = document.getElementById('audio-device-select');
        if (!select) return;
        select.innerHTML = '';
        const defaultOpt = document.createElement('option');
        defaultOpt.value = 'default';
        defaultOpt.textContent = 'Default Audio Output (Windows System Sound)';
        select.appendChild(defaultOpt);
        audioOutputs.forEach(d => {
          if (d.deviceId !== 'default') {
            const opt = document.createElement('option');
            opt.value = d.deviceId;
            opt.textContent = d.label || `Speaker / Headphones (${d.deviceId.slice(0, 6)}...)`;
            if (d.deviceId === selectedAudioDevice) opt.selected = true;
            select.appendChild(opt);
          }
        });
      } catch (e) {}
    }

    function changeAudioDevice() {
      selectedAudioDevice = document.getElementById('audio-device-select').value;
      updateSettings();
    }

    function testAudioDevice() {
      playGiftChime();
    }

    function handleWsMessage(data) {
      if (data.type === 'init') {
        updateStatus(data.status, data.message);
        if (data.version) {
          document.getElementById('app-version').textContent = 'v' + data.version;
          document.getElementById('settings-version').textContent = 'v' + data.version;
        }
        if (data.active_port) {
          document.getElementById('settings-port').textContent = data.active_port;
          document.getElementById('overlay-url').value = `http://${location.hostname}:${data.active_port}/overlay`;
        }
        const cfg = data.config || {};
        if (cfg.username) document.getElementById('username-input').value = cfg.username;
        if (cfg.command_prefix !== undefined && document.getElementById('command-prefix')) {
          document.getElementById('command-prefix').value = cfg.command_prefix;
        }
        if (cfg.starred_voices && Array.isArray(cfg.starred_voices)) starredVoices = cfg.starred_voices;
        if (cfg.installed_voices && Array.isArray(cfg.installed_voices)) installedStoreVoices = cfg.installed_voices;
        if (cfg.native_voice_name) savedNativeVoice = cfg.native_voice_name;
        if (cfg.audio_device_id) selectedAudioDevice = cfg.audio_device_id;
        renderVoiceStoreGrid();
        populateBrowserVoices();
        if (cfg.volume !== undefined) {
          document.getElementById('vol-slider').value = cfg.volume;
          document.getElementById('set-vol-slider').value = cfg.volume;
          changeVolume(cfg.volume);
        }
        if (cfg.cooldown) document.getElementById('cooldown-input').value = cfg.cooldown;
        if (cfg.max_chars) document.getElementById('maxlen-input').value = cfg.max_chars;
        if (cfg.banned_words) document.getElementById('banned-input').value = cfg.banned_words;
        if (cfg.role_filter) {
          document.getElementById('role-filter').value = cfg.role_filter;
          updateRoleButtons(cfg.role_filter);
        }
        if (cfg.min_fan_level !== undefined) document.getElementById('min-fan-level').value = cfg.min_fan_level;
        if (cfg.fan_announcements_enabled !== undefined) document.getElementById('fan-announce-toggle').checked = cfg.fan_announcements_enabled;
        if (cfg.gift_tts_enabled !== undefined) document.getElementById('gift-tts-toggle').checked = cfg.gift_tts_enabled;
        if (cfg.gift_sound_enabled !== undefined) document.getElementById('gift-sound-toggle').checked = cfg.gift_sound_enabled;
        if (cfg.gift_min_coins !== undefined) document.getElementById('gift-min-coins').value = cfg.gift_min_coins;
        if (cfg.spam_auto_mute !== undefined) document.getElementById('spam-automute-toggle').checked = cfg.spam_auto_mute;

        updateQueue(data.queue_size || 0);
        checkForUpdates();
        populateAudioDevices();
      } else if (data.type === 'status') {
        updateStatus(data.status, data.message);
      } else if (data.type === 'queue_size') {
        updateQueue(data.size);
      } else if (data.type === 'chat_log') {
        addLogItem(data.data);
      } else if (data.type === 'gift_chime') {
        playGiftChime();
      } else if (data.type === 'tts_instant') {
        enqueueAudio({ type: 'instant', data: data.item });
      } else if (data.type === 'tts_audio') {
        enqueueAudio({ type: 'piper', data: data });
      } else if (data.type === 'client_skip') {
        skipAudio();
      } else if (data.type === 'update_progress') {
        const btn = document.getElementById('modal-update-btn');
        if (btn) btn.textContent = data.status;
      }
    }

    function finishPlay() {
      activeAudio = null;
      const userEl = document.getElementById('spk-user');
      const textEl = document.getElementById('spk-text');
      const waveEl = document.getElementById('spk-wave');
      if (userEl) userEl.style.display = 'none';
      if (textEl) {
        textEl.className = 'speaking-text speaking-idle';
        textEl.textContent = 'No audio currently playing. Waiting for live chat...';
      }
      if (waveEl) waveEl.classList.remove('eq-active');

      if (audioQueue.length > 0) {
        setTimeout(processNextInQueue, 150);
      } else {
        isPlaying = false;
        updateQueue(0);
      }
    }

    function skipAudio() {
      if (window.speechSynthesis) {
        try { window.speechSynthesis.cancel(); } catch (e) {}
      }
      if (activeAudio) {
        try { activeAudio.pause(); } catch (e) {}
        activeAudio = null;
      }
      finishPlay();
    }

    function updateStatus(status, msg) {
      const badge = document.getElementById('status-badge');
      const text = document.getElementById('status-text');
      const dot = badge ? badge.querySelector('.status-dot') : null;
      if (badge && text) {
        badge.className = 'telemetry-badge ' + status;
        text.textContent = status.toUpperCase();
        if (dot) {
          if (status === 'connected') dot.className = 'status-dot pulse';
          else dot.className = 'status-dot';
        }
      }
      const msgEl = document.getElementById('status-msg');
      if (msgEl) msgEl.textContent = msg || '';
    }

    function updateQueue(count) {
      const el = document.getElementById('queue-count');
      if (el) el.textContent = count;
    }

    function addLogItem(item) {
      const list = document.getElementById('log-list');
      if (!list) return;
      if (list.children.length === 1 && list.children[0].classList.contains('log-empty')) {
        list.innerHTML = '';
      }
      const div = document.createElement('div');
      let extraClass = '';
      if (item.type === 'gift') extraClass = 'gift';
      else if (item.type === 'sub') extraClass = 'sub';
      else if (item.type === 'fan') extraClass = 'fan';
      if (item.allowed === false) extraClass += ' blocked';
      div.className = 'log-item ' + extraClass;

      const fanBadge = (item.fan_level && item.fan_level > 0) ? `<span class="badge-fan">LV.${item.fan_level}</span>` : '';

      div.innerHTML = `
        <div style="display: flex; align-items: center; flex-wrap: wrap;">
          ${fanBadge}
          <span class="log-user">${item.user}</span>
          <span class="log-text">${item.text} ${item.reason ? '<span style="color:#fda4af; font-size:11px;">(' + item.reason + ')</span>' : ''}</span>
        </div>
        <span class="log-time">${item.time}</span>
      `;
      if (currentLogFilter === 'spoken' && (item.allowed === false || item.type === 'gift')) div.style.display = 'none';
      if (currentLogFilter === 'gifts' && item.type !== 'gift') div.style.display = 'none';
      if (currentLogFilter === 'blocked' && item.allowed !== false) div.style.display = 'none';
      list.prepend(div);
      if (list.children.length > 100) list.lastChild.remove();
    }

    function changeVolume(val) {
      currentVolume = parseFloat(val);
      const pct = Math.round(currentVolume * 100) + '%';
      const l1 = document.getElementById('vol-label');
      const l2 = document.getElementById('set-vol-label');
      if (l1) l1.textContent = pct;
      if (l2) l2.textContent = pct;
      const s1 = document.getElementById('vol-slider');
      const s2 = document.getElementById('set-vol-slider');
      if (s1) s1.value = currentVolume;
      if (s2) s2.value = currentVolume;
      if (activeAudio) activeAudio.volume = currentVolume;
    }

    function applyPreset(text) {
      const input = document.getElementById('test-text');
      if (input) input.value = text;
      sendTestSpeech();
    }

    async function connectStream() {
      const user = document.getElementById('username-input').value.trim();
      if (!user) return alert("Please enter a TikTok @username!");
      await fetch('/api/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: user })
      });
    }

    async function disconnectStream() {
      await fetch('/api/disconnect', { method: 'POST' });
    }

    async function sendTestSpeech() {
      const input = document.getElementById('test-text');
      const text = input ? input.value.trim() : "";
      if (!text) return;
      try {
        const res = await fetch('/api/speak', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: text })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          if (data.is_piper && data.audio_b64) {
            enqueueAudio({
              type: 'piper',
              data: { user: "Test", display: text, audio_b64: data.audio_b64 }
            });
          } else if (!data.is_piper) {
            enqueueAudio({
              type: 'instant',
              data: { text: text, voice: data.voice }
            });
          }
        }
      } catch (e) {}
      if (input) input.value = '';
    }

    async function clearQueue() {
      audioQueue = [];
      updateQueue(0);
      skipAudio();
      await fetch('/api/clear-queue', { method: 'POST' });
    }

    document.getElementById('browser-voice-select').onchange = () => {
      const idx = document.getElementById('browser-voice-select').value;
      if (browserVoices[idx]) savedNativeVoice = browserVoices[idx].name;
      updateSettings();
    };

    function filterLog(type) {
      currentLogFilter = type;
      ['all', 'spoken', 'gifts', 'blocked'].forEach(t => {
        const btn = document.getElementById('flt-' + t);
        if (btn) {
          if (t === type) btn.classList.add('active');
          else btn.classList.remove('active');
        }
      });
      const items = document.querySelectorAll('.log-item');
      items.forEach(el => {
        if (type === 'all') el.style.display = 'flex';
        else if (type === 'spoken') el.style.display = (!el.classList.contains('blocked') && !el.classList.contains('gift')) ? 'flex' : 'none';
        else if (type === 'gifts') el.style.display = el.classList.contains('gift') ? 'flex' : 'none';
        else if (type === 'blocked') el.style.display = el.classList.contains('blocked') ? 'flex' : 'none';
      });
    }

    function copyOverlayUrl() {
      const url = document.getElementById('overlay-url').value;
      navigator.clipboard.writeText(url);
      alert("TikTok Live Studio Overlay URL copied!\n\nIn TikTok Live Studio: Click 'Add Source' -> 'Link / Browser Source' (Width: 850, Height: 250).");
    }

    function testOverlaySubtitle() {
      const sim = document.getElementById('sim-subtitle');
      const simTxt = document.getElementById('sim-sub-text');
      simTxt.textContent = "Welcome to the livestream! Subtitles working live on TikTok Live Studio!";
      sim.style.opacity = '1';
      fetch('/api/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: "Welcome to the livestream! Subtitles working live on TikTok Live Studio!" })
      });
    }

    function testOverlayGift() {
      const sim = document.getElementById('sim-gift');
      sim.style.display = 'block';
      playGiftChime();
      setTimeout(() => { sim.style.display = 'none'; }, 4000);
    }

    async function updateSettings() {
      const selectEl = document.getElementById('browser-voice-select');
      let selectedVoiceName = savedNativeVoice;
      if (selectEl) {
        const val = selectEl.value;
        if (val.startsWith('store:')) {
          const vId = val.replace('store:', '');
          const v = STORE_CATALOG.find(c => c.id === vId);
          selectedVoiceName = v ? `${v.name} (${v.subtitle})` : vId;
        } else {
          const idx = parseInt(val);
          if (browserVoices[idx]) selectedVoiceName = browserVoices[idx].name;
        }
      }
      savedNativeVoice = selectedVoiceName;

      const prefixEl = document.getElementById('command-prefix');
      const payload = {
        engine: "instant",
        voice: "",
        native_voice_name: savedNativeVoice,
        audio_device_id: selectedAudioDevice,
        installed_voices: installedStoreVoices,
        volume: currentVolume,
        command_prefix: prefixEl ? prefixEl.value : "",
        starred_voices: starredVoices,
        cooldown: parseInt(document.getElementById('cooldown-input').value) || 5,
        max_chars: parseInt(document.getElementById('maxlen-input').value) || 120,
        banned_words: document.getElementById('banned-input').value,
        role_filter: document.getElementById('role-filter').value,
        min_fan_level: parseInt(document.getElementById('min-fan-level').value) || 0,
        fan_announcements_enabled: document.getElementById('fan-announce-toggle').checked,
        gift_tts_enabled: document.getElementById('gift-tts-toggle').checked,
        gift_sound_enabled: document.getElementById('gift-sound-toggle').checked,
        gift_min_coins: parseInt(document.getElementById('gift-min-coins').value) || 1,
        spam_auto_mute: document.getElementById('spam-automute-toggle').checked
      };
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    }

    renderVoiceStoreGrid();
  </script>
</body>
</html>
"""

OVERLAY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>TTS Live Studio Overlay</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: transparent;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Inter, sans-serif;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      align-items: center;
      height: 100vh;
      padding: 24px;
    }
    #subtitle-card {
      opacity: 0;
      transform: translateY(16px) scale(0.97);
      transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
      background: rgba(9, 9, 11, 0.92);
      backdrop-filter: blur(14px);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 16px;
      padding: 15px 22px;
      max-width: 850px;
      width: 90%;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.85);
      color: #fff;
      display: flex;
      align-items: center;
      gap: 16px;
    }
    #subtitle-card.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
    .user-badge-fan {
      background: #f59e0b;
      color: #000;
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 10.5px;
      font-weight: 800;
      padding: 2px 6px;
      border-radius: 5px;
    }
    .user-name {
      font-weight: 700;
      font-size: 14px;
      color: #38bdf8;
      margin-bottom: 2px;
      display: flex;
      align-items: center;
      gap: 7px;
    }
    .speech-text {
      font-size: 19px;
      font-weight: 600;
      color: #ffffff;
      line-height: 1.35;
      word-break: break-word;
    }
    .equalizer {
      display: flex;
      align-items: flex-end;
      gap: 3px;
      height: 20px;
      min-width: 18px;
    }
    .bar {
      width: 3.5px;
      background: #38bdf8;
      border-radius: 999px;
      animation: bounce 0.75s ease-in-out infinite alternate;
    }
    .bar:nth-child(2) { animation-delay: 0.18s; height: 15px; }
    .bar:nth-child(3) { animation-delay: 0.35s; height: 20px; }
    .bar:nth-child(4) { animation-delay: 0.12s; height: 11px; }
    @keyframes bounce {
      0% { height: 4px; }
      100% { height: 20px; }
    }
    #gift-card {
      position: absolute;
      top: 24px;
      opacity: 0;
      transform: translateY(-16px) scale(0.95);
      transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
      background: rgba(9, 9, 11, 0.94);
      border: 1px solid rgba(245, 158, 11, 0.45);
      border-radius: 999px;
      padding: 10px 22px;
      box-shadow: 0 14px 35px rgba(0, 0, 0, 0.8);
      color: #fafafa;
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 600;
      font-size: 15px;
    }
    #gift-card.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
    .gift-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #f59e0b;
      box-shadow: 0 0 10px #f59e0b;
    }
  </style>
</head>
<body>
  <div id="gift-card">
    <span class="gift-dot"></span>
    <span id="gift-text"></span>
  </div>

  <div id="subtitle-card">
    <div class="equalizer">
      <div class="bar"></div>
      <div class="bar"></div>
      <div class="bar"></div>
      <div class="bar"></div>
    </div>
    <div style="flex: 1;">
      <div class="user-name">
        <span id="sub-fan-badge" class="user-badge-fan" style="display: none;"></span>
        <span id="sub-user"></span>
      </div>
      <div class="speech-text" id="sub-text"></div>
    </div>
  </div>

  <script>
    const subCard = document.getElementById('subtitle-card');
    const subUser = document.getElementById('sub-user');
    const subText = document.getElementById('sub-text');
    const subBadge = document.getElementById('sub-fan-badge');
    const giftCard = document.getElementById('gift-card');
    const giftText = document.getElementById('gift-text');
    let hideTimer = null;
    let giftTimer = null;

    function showSubtitle(user, text, fanLevel) {
      clearTimeout(hideTimer);
      subUser.textContent = user;
      subText.textContent = text;
      if (fanLevel && fanLevel > 0) {
        subBadge.textContent = 'LV.' + fanLevel;
        subBadge.style.display = 'inline-block';
      } else {
        subBadge.style.display = 'none';
      }
      subCard.className = 'visible';

      const duration = Math.max(4500, text.length * 90);
      hideTimer = setTimeout(() => {
        subCard.className = '';
      }, duration);
    }

    function showGiftAlert(text) {
      clearTimeout(giftTimer);
      giftText.textContent = text;
      giftCard.className = 'visible';
      giftTimer = setTimeout(() => {
        giftCard.className = '';
      }, 4000);
    }

    let overlayWs = null;
    function connectOverlayWs() {
      if (overlayWs) {
        try { overlayWs.close(); } catch (e) {}
      }
      overlayWs = new WebSocket(`ws://${location.host}/ws`);
      overlayWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'tts_instant') {
            showSubtitle(data.item.user, data.item.display || data.item.text, data.item.fan_level);
          } else if (data.type === 'tts_audio' || data.type === 'speaking_start') {
            showSubtitle(data.user, data.display || data.text, data.fan_level || 0);
          } else if (data.type === 'chat_log' && data.data && data.data.type === 'gift') {
            showGiftAlert(`${data.data.user} ${data.data.text}`);
          } else if (data.type === 'client_skip') {
            subCard.className = '';
          }
        } catch (e) {}
      };
      overlayWs.onclose = () => {
        setTimeout(connectOverlayWs, 2000);
      };
      overlayWs.onerror = () => {};
    }
    connectOverlayWs();
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return HTML_CONTENT

@app.get("/overlay", response_class=HTMLResponse)
async def serve_overlay():
    return OVERLAY_HTML

def find_available_port(preferred=DEFAULT_PORT):
    for p in range(preferred, preferred + 30):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', p))
                return p
        except OSError:
            continue
    return preferred

if __name__ == "__main__":
    active_port = find_available_port(DEFAULT_PORT)

    def run_server():
        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=active_port,
            log_config=None,
            loop="asyncio",
            http="h11",
            ws="websockets"
        )
        server = uvicorn.Server(config)
        server.run()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Fast non-blocking port readiness poll (typically ready in 20-30ms)
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.05)
            if s.connect_ex(('127.0.0.1', active_port)) == 0:
                break
        time.sleep(0.02)

    # Pre-warm TikTokLive and edge_tts in background so Go Live connects with 0 delay
    def _prewarm_background():
        try:
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import ConnectEvent, CommentEvent, GiftEvent, DisconnectEvent, SubNotifyEvent
            import edge_tts
        except Exception:
            pass

    threading.Thread(target=_prewarm_background, daemon=True).start()

    try:
        import webview
        icon_file = os.path.join(BUNDLE_DIR, "icon.ico")
        if not os.path.exists(icon_file):
            icon_file = os.path.join(BASE_DIR, "icon.ico")
        window = webview.create_window(
            title="TTS Live Studio",
            url=f"http://127.0.0.1:{active_port}",
            width=1320,
            height=860,
            min_size=(950, 640),
            background_color='#000000'
        )
        webview.start()
    except Exception:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{active_port}")
        while True:
            time.sleep(1)
