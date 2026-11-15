import sys
import os
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
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import edge_tts
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, GiftEvent, DisconnectEvent, SuperFanJoinEvent, SubNotifyEvent

CURRENT_VERSION = "1.4.0"
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

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

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
    "spam_auto_mute": True
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

app = FastAPI(title="TikTok Live TTS Studio", version=CURRENT_VERSION)

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
        self.client: Optional[TikTokLiveClient] = None
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
            "spam_auto_mute": self.spam_auto_mute
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

async def broadcast(data: dict):
    dead = set()
    for ws in list(state.websockets):
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    state.websockets.difference_update(dead)

def check_filters(user, text: str) -> tuple[bool, str]:
    now = time.time()
    user_id = getattr(user, 'unique_id', str(getattr(user, 'id', 'user')))
    
    # 1. Spam Auto-Mute Check (3+ messages in 10s = 30s mute)
    if state.spam_auto_mute:
        mute_until = state.user_muted_until.get(user_id, 0)
        if now < mute_until:
            rem = int(mute_until - now)
            return False, f"Auto-muted for spam ({rem}s left)"
            
        history = state.user_msg_history.setdefault(user_id, [])
        history = [t for t in history if (now - t) < 10.0]
        if len(history) >= 3:
            state.user_muted_until[user_id] = now + 30.0
            return False, "Auto-muted 30s (rapid spam)"
        history.append(now)
        state.user_msg_history[user_id] = history

    # 2. Fan Club & Role Filter Check
    fan_level = 0
    if hasattr(user, 'fans_club') and user.fans_club and hasattr(user.fans_club, 'data') and user.fans_club.data:
        fan_level = getattr(user.fans_club.data, 'level', 0)
        
    is_sub = getattr(user, 'is_subscribe', False)
    is_follower = getattr(user, 'is_follower', False)

    if state.role_filter == "followers" and not is_follower:
        return False, "Followers only"
    if state.role_filter == "subs" and not is_sub:
        return False, "Subscribers only"
    if state.role_filter == "fan_club" and fan_level < 1:
        return False, "Fan Club only"
    if state.min_fan_level > 0 and fan_level < state.min_fan_level:
        return False, f"Requires Fan Lv.{state.min_fan_level} (Viewer is Lv.{fan_level})"

    # 3. Max length truncate
    clean_text = text.strip()
    if len(clean_text) > state.max_chars:
        clean_text = clean_text[:state.max_chars]
    
    # 4. Banned words check
    lower_text = clean_text.lower()
    for word in state.banned_words:
        if word and word.lower() in lower_text:
            return False, f"Blacklisted word: {word}"
            
    # 5. Cooldown check
    last = state.user_last_seen.get(user_id, 0)
    if (now - last) < state.cooldown:
        remaining = int(state.cooldown - (now - last))
        return False, f"Cooldown ({remaining}s)"
        
    state.user_last_seen[user_id] = now
    return True, clean_text

async def handle_new_tts_item(user: str, raw_text: str, display_text: str, fan_level: int = 0):
    item = {
        "id": str(uuid.uuid4()),
        "user": user,
        "fan_level": fan_level,
        "text": raw_text,
        "display": display_text,
        "engine": state.engine,
        "voice": state.voice,
        "time": time.strftime("%H:%M:%S")
    }

    if state.engine == "instant":
        await broadcast({
            "type": "tts_instant",
            "item": item
        })
    else:
        await state.tts_queue.put(item)
        await broadcast({"type": "queue_size", "size": state.tts_queue.qsize()})

async def tiktok_runner(username: str):
    clean_user = username.lstrip("@").strip()
    state.username = clean_user
    save_config(state.export_config())
    
    state.status = "connecting"
    state.status_msg = f"Connecting to @{clean_user}..."
    await broadcast({"type": "status", "status": state.status, "message": state.status_msg})

    try:
        client = TikTokLiveClient(unique_id=clean_user)
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
            allowed, result = check_filters(event.user, event.comment)
            fan_level = 0
            if hasattr(event.user, 'fans_club') and event.user.fans_club and hasattr(event.user.fans_club, 'data') and event.user.fans_club.data:
                fan_level = getattr(event.user.fans_club.data, 'level', 0)
                
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
                speech_text = f"{event.user.nickname} says: {result}"
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
                speech_text = f"Thank you {event.user.nickname} for sending {event.repeat_count} {event.gift.name}!"
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
                speech = f"Welcome {user_name} to the subscriber club!" if months <= 1 else f"Thank you {user_name} for resubscribing for {months} months!"
                await handle_new_tts_item(user_name, speech, text, fan_level=1)

        @client.on(SuperFanJoinEvent)
        async def on_superfan_join(event: SuperFanJoinEvent):
            user_name = getattr(event.user, 'nickname', 'Fan') if hasattr(event, 'user') and event.user else 'Fan'
            level = getattr(event, 'fans_level_param', 1) or 1
            text = f"Joined Fan Club (Level {level})!"
            log_item = {
                "type": "fan",
                "user": user_name,
                "fan_level": level,
                "text": text,
                "allowed": state.fan_announcements_enabled,
                "reason": "" if state.fan_announcements_enabled else "Announcements disabled",
                "time": time.strftime("%H:%M:%S")
            }
            await broadcast({"type": "chat_log", "data": log_item})

            if state.fan_announcements_enabled:
                if state.gift_sound_enabled:
                    await broadcast({"type": "gift_chime"})
                speech = f"Congratulations {user_name} for joining the fan club at level {level}!"
                await handle_new_tts_item(user_name, speech, text, fan_level=level)

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            state.status = "disconnected"
            state.status_msg = "Disconnected from livestream."
            await broadcast({"type": "status", "status": state.status, "message": state.status_msg})

        await client.connect()

    except asyncio.CancelledError:
        state.status = "disconnected"
        state.status_msg = "Disconnected."
        await broadcast({"type": "status", "status": state.status, "message": state.status_msg})
    except Exception as e:
        state.status = "error"
        state.status_msg = f"Error: {str(e)}"
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
            download_url = None
            for asset in assets:
                if asset.get("name") == "TikTokLiveTTS-Windows.zip":
                    download_url = asset.get("browser_download_url")
                    break
            if not download_url:
                return {"status": "error", "message": "No Windows executable ZIP found in latest release"}

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

            # Create bulletproof batch updater with PID check and no error spam
            current_pid = os.getpid()
            bat_path = os.path.join(temp_dir, "apply_update.bat")
            with open(bat_path, "w", encoding="utf-8") as bf:
                bf.write(f"""@echo off
setlocal
set "TARGET_DIR={target_dir}"
set "SOURCE_DIR={source_folder}"
set "TARGET_EXE={target_exe}"
set "OLD_PID={current_pid}"

:: Terminate old process tree cleanly
taskkill /F /T /PID %OLD_PID% >nul 2>&1
timeout /t 2 /nobreak >nul

:wait_loop
tasklist /fi "PID eq %OLD_PID%" 2>nul | find "%OLD_PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)

:: Wait for file handles to unlock
timeout /t 2 /nobreak >nul

:: Robocopy with max 2 retries, 1s wait, and quiet logs
robocopy "%SOURCE_DIR%" "%TARGET_DIR%" /E /IS /IT /R:2 /W:1 /nfl /ndl /njh /njs >nul

:: Launch updated app cleanly
start "" "%TARGET_EXE%"
exit
""")

            await broadcast({"type": "update_progress", "status": "Restarting application now...", "percent": 100})

            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(["cmd.exe", "/c", bat_path], creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, close_fds=True)

            def do_exit():
                time.sleep(1.0)
                os._exit(0)

            threading.Thread(target=do_exit, daemon=True).start()
            return {"status": "ok", "message": "Update downloaded, restarting..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/connect")
async def api_connect(req: ConnectRequest):
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
    if state.task and not state.task.done():
        state.task.cancel()
    if state.client and state.client.connected:
        try:
            await state.client.disconnect()
        except Exception:
            pass
    state.status = "disconnected"
    state.status_msg = "Disconnected"
    await broadcast({"type": "status", "status": state.status, "message": state.status_msg})
    return {"status": "ok", "message": "Disconnected"}

@app.post("/api/speak")
async def api_speak(req: SpeakRequest):
    speech_text = req.text
    await handle_new_tts_item("Test User", speech_text, req.text)
    return {"status": "ok", "queue_size": state.tts_queue.qsize()}

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

    save_config(state.export_config())

    return {
        "status": "ok",
        "config": state.export_config()
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
            if data.get("action") == "skip":
                await broadcast({"type": "client_skip"})
    except WebSocketDisconnect:
        state.websockets.discard(ws)

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TikTok Live TTS Studio</title>
  <style>
    :root {
      --bg-dark: #0a0e17;
      --card-bg: #131b2e;
      --card-border: #1e293b;
      --accent-primary: #10b981;
      --accent-cyan: #06b6d4;
      --accent-danger: #ef4444;
      --accent-gold: #f59e0b;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg-dark);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: #0f172a;
      border-bottom: 1px solid var(--card-border);
      padding: 12px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .logo-group { display: flex; align-items: center; gap: 12px; }
    .logo-icon { font-size: 24px; }
    .logo-title { font-size: 18px; font-weight: 700; color: #fff; letter-spacing: -0.5px; }
    .version-tag { font-size: 11px; padding: 2px 8px; border-radius: 6px; background: #1e293b; color: #94a3b8; font-weight: 600; margin-left: 4px; }
    .header-badges { display: flex; gap: 10px; align-items: center; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      background: #1e293b;
      color: var(--text-muted);
    }
    .badge.connected { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge.offline { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
    .badge.connecting { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge.latency { background: rgba(6, 182, 212, 0.15); color: #38bdf8; border: 1px solid rgba(6, 182, 212, 0.3); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }

    /* Compact Update Pill in Header */
    .update-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 5px 14px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      background: linear-gradient(90deg, #1e40af, #0284c7);
      color: #fff;
      border: 1px solid #38bdf8;
      cursor: pointer;
      animation: pulseGlow 2.5s infinite;
      transition: transform 0.2s;
    }
    .update-pill:hover { transform: scale(1.04); }
    .update-pulse { width: 8px; height: 8px; border-radius: 50%; background: #38bdf8; }
    @keyframes pulseGlow {
      0%, 100% { box-shadow: 0 0 8px rgba(56, 189, 248, 0.4); }
      50% { box-shadow: 0 0 16px rgba(56, 189, 248, 0.8); }
    }

    /* Tabbed Navigation Bar */
    .nav-bar {
      display: flex;
      gap: 8px;
      padding: 0 28px;
      background: #0f172a;
      border-bottom: 1px solid var(--card-border);
    }
    .nav-tab {
      padding: 12px 18px;
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text-muted);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
    }
    .nav-tab:hover { color: #fff; }
    .nav-tab.active {
      color: var(--accent-cyan);
      border-bottom-color: var(--accent-cyan);
      background: rgba(6, 182, 212, 0.05);
    }
    .tab-content { display: none; padding: 20px 28px; flex: 1; max-width: 1500px; margin: 0 auto; width: 100%; }
    .tab-content.active { display: block; }

    /* Layout Containers */
    .two-col-grid {
      display: grid;
      grid-template-columns: 440px 1fr;
      gap: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 18px;
      margin-bottom: 16px;
    }
    .card-title {
      font-size: 14px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--accent-cyan);
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    label { display: block; font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 5px; }
    input[type="text"], input[type="number"], select {
      width: 100%;
      background: #090d16;
      border: 1px solid #2d3748;
      border-radius: 7px;
      padding: 9px 12px;
      color: #fff;
      font-size: 13px;
      outline: none;
      transition: border 0.2s;
    }
    input[type="text"]:focus, select:focus { border-color: var(--accent-primary); }
    .btn-row { display: flex; gap: 8px; margin-top: 10px; }
    button {
      flex: 1;
      padding: 9px 14px;
      border-radius: 7px;
      border: none;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-primary { background: var(--accent-primary); color: #000; }
    .btn-primary:hover { background: #059669; }
    .btn-danger { background: var(--accent-danger); color: #fff; }
    .btn-danger:hover { background: #dc2626; }
    .btn-secondary { background: #1e293b; color: #fff; }
    .btn-secondary:hover { background: #334155; }

    /* Engine Toggle */
    .engine-toggle {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      background: #090d16;
      padding: 4px;
      border-radius: 8px;
      border: 1px solid #2d3748;
      margin-bottom: 14px;
    }
    .engine-option {
      padding: 7px 10px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      text-align: center;
      cursor: pointer;
      color: var(--text-muted);
      transition: all 0.2s;
    }
    .engine-option.active {
      background: var(--accent-primary);
      color: #000;
      box-shadow: 0 2px 6px rgba(16, 185, 129, 0.3);
    }

    /* Preset Chips */
    .preset-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 10px 0;
    }
    .chip {
      background: #1e293b;
      border: 1px solid #334155;
      color: #f1f5f9;
      font-size: 11px;
      padding: 5px 10px;
      border-radius: 999px;
      cursor: pointer;
      transition: all 0.2s;
      white-space: nowrap;
    }
    .chip:hover {
      background: var(--accent-cyan);
      color: #000;
      border-color: var(--accent-cyan);
    }

    /* Checkbox rows */
    .toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
    }
    .toggle-row label { margin-bottom: 0; cursor: pointer; }
    input[type="checkbox"] {
      width: 18px;
      height: 18px;
      accent-color: var(--accent-primary);
      cursor: pointer;
    }

    /* Speaking Display Card */
    .now-speaking-card {
      background: linear-gradient(135deg, #131b2e 0%, #172554 100%);
      border: 1px solid #1e3a8a;
    }
    .speaking-display {
      min-height: 80px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      background: rgba(0, 0, 0, 0.35);
      border-radius: 9px;
      padding: 12px 16px;
      margin-bottom: 10px;
    }
    .speaking-user { font-size: 13px; font-weight: 700; color: #38bdf8; margin-bottom: 3px; }
    .speaking-text { font-size: 17px; font-weight: 500; color: #fff; line-height: 1.4; }
    .speaking-idle { color: var(--text-muted); font-style: italic; font-size: 13px; }

    /* Live activity log */
    .log-container {
      background: #090d16;
      border: 1px solid #1e293b;
      border-radius: 9px;
      height: 520px;
      overflow-y: auto;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .log-item {
      padding: 7px 11px;
      border-radius: 6px;
      background: #111827;
      font-size: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .log-item.gift { border-left: 3px solid var(--accent-gold); background: rgba(245, 158, 11, 0.08); }
    .log-item.sub { border-left: 3px solid #a855f7; background: rgba(168, 85, 247, 0.08); }
    .log-item.fan { border-left: 3px solid #f59e0b; background: rgba(245, 158, 11, 0.12); }
    .log-item.blocked { opacity: 0.55; border-left: 3px solid var(--accent-danger); }
    .badge-fan {
      display: inline-block;
      background: #f59e0b;
      color: #000;
      font-size: 9px;
      font-weight: 800;
      padding: 1px 5px;
      border-radius: 4px;
      margin-right: 6px;
      vertical-align: middle;
    }
    .log-user { font-weight: 600; color: #38bdf8; margin-right: 6px; }
    .log-text { color: #f1f5f9; }
    .log-time { font-size: 11px; color: #64748b; margin-left: 10px; white-space: nowrap; }

    /* Soundwave Equalizer */
    .equalizer {
      display: flex;
      align-items: flex-end;
      gap: 3px;
      height: 20px;
      min-width: 18px;
    }
    .bar {
      width: 3px;
      background: #38bdf8;
      border-radius: 2px;
      animation: bounce 0.8s ease-in-out infinite alternate;
    }
    .bar:nth-child(2) { animation-delay: 0.2s; height: 14px; background: #06b6d4; }
    .bar:nth-child(3) { animation-delay: 0.4s; height: 20px; background: #10b981; }
    .bar:nth-child(4) { animation-delay: 0.1s; height: 10px; background: #38bdf8; }
    @keyframes bounce { 0% { height: 4px; } 100% { height: 20px; } }

    /* In-App What's New Modal */
    .modal-backdrop {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(6px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 9999;
    }
    .modal-card {
      background: #0f172a;
      border: 1px solid #1e3a8a;
      border-radius: 14px;
      width: 90%;
      max-width: 520px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8), 0 0 25px rgba(56, 189, 248, 0.2);
      overflow: hidden;
      animation: modalPop 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes modalPop {
      0% { opacity: 0; transform: scale(0.95); }
      100% { opacity: 1; transform: scale(1); }
    }
    .modal-header {
      padding: 16px 20px;
      background: #131b2e;
      border-bottom: 1px solid var(--card-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-close {
      background: none; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 4px 8px; border-radius: 6px;
    }
    .modal-close:hover { color: #fff; background: #1e293b; }
    .modal-body {
      padding: 20px;
      font-size: 13px;
      color: #cbd5e1;
      line-height: 1.6;
      max-height: 320px;
      overflow-y: auto;
    }
    .modal-body ul { margin-left: 20px; margin-top: 8px; }
    .modal-body li { margin-bottom: 6px; }
    .modal-footer {
      padding: 14px 20px;
      background: #0b1120;
      border-top: 1px solid var(--card-border);
      display: flex;
      gap: 10px;
      justify-content: flex-end;
    }

    /* Footer Legal Disclaimer */
    footer {
      background: #090d16;
      border-top: 1px solid var(--card-border);
      padding: 10px 28px;
      font-size: 11px;
      color: #64748b;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  </style>
</head>
<body>
  <!-- In-App What's New Modal -->
  <div id="update-modal" class="modal-backdrop" style="display: none;">
    <div class="modal-card">
      <div class="modal-header">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-size: 22px;">🚀</span>
          <div>
            <div id="modal-title" style="font-size: 16px; font-weight: 700; color: #fff;">Update Available</div>
            <div id="modal-subtitle" style="font-size: 12px; color: #94a3b8;">TikTok Live TTS Studio</div>
          </div>
        </div>
        <button class="modal-close" onclick="closeUpdateModal()">✕</button>
      </div>
      <div class="modal-body" id="modal-changelog">
        Loading release details...
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" style="flex: 0 0 100px;" onclick="closeUpdateModal()">Later</button>
        <button id="modal-update-btn" class="btn-primary" onclick="installUpdate()">⚡ Update & Restart Now</button>
      </div>
    </div>
  </div>

  <header>
    <div class="logo-group">
      <span class="logo-icon">🎙️</span>
      <span class="logo-title">TikTok Live TTS Studio</span>
      <span class="version-tag" id="app-version">v1.4.0</span>
    </div>
    <div class="header-badges">
      <button id="update-pill" class="update-pill" style="display: none;" onclick="openUpdateModal()">
        <span class="update-pulse"></span>
        <span id="update-pill-text">v1.4.1 Update Ready</span>
      </button>
      <div id="latency-badge" class="badge latency">
        <span>⚡ Real-Time Mode (&lt;50ms)</span>
      </div>
      <div id="status-badge" class="badge">
        <span class="dot"></span>
        <span id="status-text">Disconnected</span>
      </div>
    </div>
  </header>

  <!-- Tabbed Navigation Bar -->
  <div class="nav-bar">
    <button id="nav-btn-tts" class="nav-tab active" onclick="switchTab('tts')">🎙️ Live TTS & Moderation</button>
    <button id="nav-btn-overlay" class="nav-tab" onclick="switchTab('overlay')">📺 TikTok Studio Overlay</button>
    <button id="nav-btn-store" class="nav-tab" onclick="switchTab('store')">🏪 Voice Store (Offline 0ms)</button>
    <button id="nav-btn-settings" class="nav-tab" onclick="switchTab('settings')">⚙️ Settings & Audio Routing</button>
  </div>

  <!-- TAB 1: Live TTS & Moderation -->
  <div id="tab-tts" class="tab-content active">
    <div class="two-col-grid">
      <!-- Left Column: Controls -->
      <div>
        <!-- 1. Connection Card -->
        <div class="card">
          <div class="card-title">Stream Connection</div>
          <label>TikTok @Username (Auto-Saved)</label>
          <input type="text" id="username-input" placeholder="e.g. your_username" />
          <div class="btn-row">
            <button class="btn-primary" onclick="connectStream()">Connect</button>
            <button class="btn-secondary" onclick="disconnectStream()">Disconnect</button>
          </div>
          <p id="status-msg" style="font-size: 11px; color: var(--text-muted); margin-top: 8px;"></p>
        </div>

        <!-- 2. Voice Engine Card -->
        <div class="card">
          <div class="card-title">Voice & Audio Engine</div>
          <div class="engine-toggle">
            <div id="opt-instant" class="engine-option active" onclick="setEngine('instant')">
              ⚡ Instant Native (&lt;50ms)
            </div>
            <div id="opt-cloud" class="engine-option" onclick="setEngine('cloud')">
              ☁️ Cloud Neural (HD)
            </div>
          </div>

          <div id="instant-voice-block">
            <label>Native Browser / OS Voice</label>
            <select id="browser-voice-select"></select>
            <p style="font-size: 11px; color: #34d399; margin-top: 5px;">⚡ Zero delay (&lt;50ms). Speaks instantaneously when viewer chats.</p>
          </div>

          <div id="cloud-voice-block" style="display: none;">
            <label>Microsoft Cloud Neural Voice (HD)</label>
            <select id="cloud-voice-select" onchange="updateSettings()">
              <optgroup label="Popular Voices (US English)">
                <option value="en-US-JennyNeural">Jenny (US Female - Natural & Expressive)</option>
                <option value="en-US-GuyNeural">Guy (US Male - Clear & Dynamic)</option>
                <option value="en-US-AvaNeural">Ava (US Female - Warm & Friendly)</option>
                <option value="en-US-ChristopherNeural">Christopher (US Male - Energetic / Hype)</option>
                <option value="en-US-AriaNeural">Aria (US Female - Smooth & Clear)</option>
                <option value="en-US-AndrewNeural">Andrew (US Male - Casual Conversation)</option>
                <option value="en-US-BrianNeural">Brian (US Male - Deep Radio Announcer)</option>
                <option value="en-US-EmmaNeural">Emma (US Female - Cheerful & Bright)</option>
              </optgroup>
              <optgroup label="International English">
                <option value="en-GB-SoniaNeural">Sonia (British Female - Crisp)</option>
                <option value="en-GB-RyanNeural">Ryan (British Male - Friendly)</option>
                <option value="en-GB-LibbyNeural">Libby (British Female - Storyteller)</option>
                <option value="en-AU-NatashaNeural">Natasha (Australian Female)</option>
                <option value="en-CA-ClaraNeural">Clara (Canadian Female)</option>
                <option value="en-IN-NeerjaNeural">Neerja (Indian English Female)</option>
              </optgroup>
            </select>
            <p style="font-size: 11px; color: #f59e0b; margin-top: 5px;">High fidelity cloud voice. Requires ~2-3s streaming buffer.</p>
          </div>

          <div style="margin-top: 12px;">
            <label>Volume: <span id="vol-label">100%</span></label>
            <input type="range" id="vol-slider" min="0" max="1" step="0.05" value="1" style="width: 100%;" oninput="changeVolume(this.value)" />
          </div>
        </div>

        <!-- 3. Fan Club & Audience Permissions -->
        <div class="card">
          <div class="card-title">Audience & Fan Club Access</div>
          <label>Who Can Trigger Text-to-Speech?</label>
          <select id="role-filter" onchange="updateSettings()" style="margin-bottom: 12px;">
            <option value="anyone">Everyone (Open to all chat)</option>
            <option value="followers">Followers Only</option>
            <option value="fan_club">Fan Club Members Only (Closes TTS for non-members)</option>
            <option value="subs">Subscribers Only</option>
          </select>

          <label>Minimum Fan Club Level to Speak (0 = Any Level)</label>
          <input type="number" id="min-fan-level" min="0" max="50" value="0" onchange="updateSettings()" style="margin-bottom: 6px;" />
          <p style="font-size: 11px; color: var(--text-muted);">Set to e.g. <b>5</b> to close TTS for viewers below Level 5 or not in the fan club.</p>

          <div class="toggle-row" style="margin-top: 10px;">
            <label for="fan-announce-toggle">Announce New Fans & Subs (TTS + Chime)</label>
            <input type="checkbox" id="fan-announce-toggle" checked onchange="updateSettings()" />
          </div>
        </div>

        <!-- 4. Gift Controls & Milestones -->
        <div class="card">
          <div class="card-title">Gift Callouts & Sound Alerts</div>
          <div class="toggle-row">
            <label for="gift-tts-toggle">Speak Gift Announcements</label>
            <input type="checkbox" id="gift-tts-toggle" checked onchange="updateSettings()" />
          </div>
          <div class="toggle-row">
            <label for="gift-sound-toggle">Play Gift Alert Chime Sound</label>
            <input type="checkbox" id="gift-sound-toggle" checked onchange="updateSettings()" />
          </div>
          <label style="margin-top: 8px;">Minimum Gift Coins for Speech</label>
          <input type="number" id="gift-min-coins" min="1" max="10000" value="1" onchange="updateSettings()" />
          <p style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">Ignore cheap 1-coin spam and only speak bigger gifts.</p>
        </div>

        <!-- 5. Anti-Spam & Moderation -->
        <div class="card">
          <div class="card-title">Safety & Anti-Troll</div>
          <div class="toggle-row">
            <label for="spam-automute-toggle">Auto-Mute Rapid Spammers (3 msgs / 10s)</label>
            <input type="checkbox" id="spam-automute-toggle" checked onchange="updateSettings()" />
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px;">
            <div>
              <label>Cooldown (sec)</label>
              <input type="number" id="cooldown-input" value="5" min="1" max="60" onchange="updateSettings()" />
            </div>
            <div>
              <label>Max Characters</label>
              <input type="number" id="maxlen-input" value="120" min="20" max="300" onchange="updateSettings()" />
            </div>
          </div>

          <label style="margin-top: 10px;">Banned Words (comma separated)</label>
          <input type="text" id="banned-input" placeholder="badword1, troll2" onchange="updateSettings()" />
        </div>

        <!-- 6. Test Audio Sandbox -->
        <div class="card">
          <div class="card-title">Test Audio Sandbox</div>
          <div class="preset-chips">
            <span class="chip" onclick="applyPreset('Welcome to the livestream everyone!')">👋 Welcome</span>
            <span class="chip" onclick="applyPreset('Thank you for the roses and gifts!')">🌹 Thanks for Gift</span>
            <span class="chip" onclick="applyPreset('Let\'s go! Hype in the chat!')">🔥 Hype</span>
            <span class="chip" onclick="applyPreset('GG on that round! Intense match.')">🎮 GG Match</span>
            <span class="chip" onclick="applyPreset('Shoutout to the top gifter on the leaderboard!')">👑 Leaderboard</span>
          </div>
          <input type="text" id="test-text" placeholder="Type or click a preset above..." />
          <button class="btn-primary" style="margin-top: 8px; width: 100%;" onclick="sendTestSpeech()">Speak Test Message</button>
        </div>
      </div>

      <!-- Right Column: Speaking Monitor & Live Chat -->
      <div>
        <div class="card now-speaking-card">
          <div class="card-title">
            <span>Now Speaking</span>
            <span style="font-size: 13px; font-weight: normal; color: #93c5fd;">Queue: <span id="queue-count">0</span> items</span>
          </div>
          <div class="speaking-display">
            <div id="spk-user" class="speaking-user" style="display: none;"></div>
            <div id="spk-text" class="speaking-text speaking-idle">No audio currently playing. Waiting for chat...</div>
          </div>
          <div class="btn-row">
            <button class="btn-danger" onclick="skipAudio()">⏹️ Skip Message</button>
            <button class="btn-secondary" onclick="clearQueue()">🗑️ Clear Queue</button>
          </div>
        </div>

        <div class="card">
          <div class="card-title" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
            <span>Live Chat & Gift Activity</span>
            <div style="display: flex; gap: 5px;">
              <button class="chip" id="flt-all" style="background: var(--accent-cyan); color: #000;" onclick="filterLog('all')">All</button>
              <button class="chip" id="flt-spoken" onclick="filterLog('spoken')">🗣️ Spoken</button>
              <button class="chip" id="flt-gifts" onclick="filterLog('gifts')">🎁 Gifts</button>
              <button class="chip" id="flt-blocked" onclick="filterLog('blocked')">🚫 Filtered</button>
            </div>
          </div>
          <div id="log-list" class="log-container">
            <div style="color: #64748b; text-align: center; margin-top: 40px;">Live comments and gifts will stream here when connected...</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 2: TikTok Studio Overlay -->
  <div id="tab-overlay" class="tab-content">
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
      <div class="card" style="border: 1px solid #0284c7; background: linear-gradient(135deg, #0b1329 0%, #075985 100%);">
        <div class="card-title" style="color: #38bdf8;">
          <span>📺 TikTok Live Studio Setup</span>
        </div>
        <p style="font-size: 13px; color: #e2e8f0; line-height: 1.6; margin-bottom: 14px;">
          Add real-time floating chat subtitles & animated gift celebration alerts directly onto your live broadcast with a transparent background.
        </p>
        <div style="background: rgba(0,0,0,0.4); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
          <div style="font-size: 12px; font-weight: 700; color: #38bdf8; margin-bottom: 6px;">3-STEP SETUP IN TIKTOK LIVE STUDIO:</div>
          <ol style="font-size: 12px; color: #cbd5e1; margin-left: 18px; line-height: 1.7;">
            <li>Click <b>Add Source</b> at the bottom of TikTok Live Studio.</li>
            <li>Select <b>Link / Browser Source</b>.</li>
            <li>Paste your private overlay link below and set <b>Width: 850</b>, <b>Height: 250</b>.</li>
          </ol>
        </div>
        <label>Your Live Transparent Overlay URL</label>
        <div style="display: flex; gap: 8px; margin-bottom: 14px;">
          <input type="text" id="overlay-url" readonly style="background: rgba(0,0,0,0.6); font-family: monospace; font-size: 12px; color: #38bdf8;" />
          <button class="btn-primary" style="flex: 0 0 120px;" onclick="copyOverlayUrl()">📋 Copy URL</button>
        </div>
        <div class="btn-row">
          <button class="btn-secondary" onclick="testOverlaySubtitle()">⚡ Trigger Test Subtitle</button>
          <button class="btn-secondary" onclick="testOverlayGift()">🎁 Trigger Test Gift</button>
        </div>
      </div>

      <!-- Right Column: Simulator -->
      <div class="card">
        <div class="card-title">
          <span>Live Overlay Preview Simulator</span>
          <span style="font-size: 11px; color: var(--text-muted);">Real-time broadcast preview</span>
        </div>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;">
          This preview simulates how subtitles and gift popups appear over your stream video:
        </p>
        <div style="background: #020617; border: 1px dashed #334155; border-radius: 12px; height: 260px; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; padding: 20px; position: relative; overflow: hidden;">
          <div style="position: absolute; top: 12px; left: 14px; font-size: 11px; color: #64748b; font-weight: 600;">[STREAM VIDEO / GAMEPLAY BACKGROUND]</div>
          
          <div id="sim-gift" style="display: none; position: absolute; top: 20px; background: linear-gradient(135deg, #f59e0b, #d97706); border: 2px solid #fde68a; border-radius: 12px; padding: 10px 20px; color: #000; font-weight: 800; font-size: 14px; box-shadow: 0 8px 25px rgba(245, 158, 11, 0.4);">
            🎁 GamerFan99 Sent 10x Roses!
          </div>

          <div id="sim-subtitle" style="display: flex; align-items: center; gap: 14px; background: rgba(15, 23, 42, 0.88); backdrop-filter: blur(8px); border: 1px solid rgba(255, 255, 255, 0.18); border-radius: 14px; padding: 14px 20px; width: 90%; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
            <div class="equalizer" style="height: 18px;">
              <div class="bar"></div>
              <div class="bar"></div>
              <div class="bar"></div>
              <div class="bar"></div>
            </div>
            <div>
              <div style="font-size: 12px; font-weight: 800; color: #38bdf8;">
                <span class="badge-fan">LV.5</span> GamerFan99
              </div>
              <div id="sim-sub-text" style="font-size: 15px; font-weight: 600; color: #fff;">Let's get this win! Amazing stream today!</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 3: Voice Store (Offline 0ms) -->
  <div id="tab-store" class="tab-content">
    <div class="card">
      <div class="card-title">
        <span>🏪 Offline Voice Store</span>
        <span style="font-size: 12px; color: #34d399; font-weight: 600;">⚡ All voices run locally with 0ms lag</span>
      </div>
      <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 18px;">
        Browse and install neural character voices directly onto your computer. Once installed, they speak instantaneously offline with zero network latency.
      </p>

      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px;">
        <!-- Voice 1 -->
        <div class="card" style="margin-bottom: 0; background: #0c1222; border-color: #1e293b;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #fff;">Nova</div>
              <div style="font-size: 11px; color: #38bdf8;">High-Energy Anime Female</div>
            </div>
            <span class="badge" style="background: rgba(236, 72, 153, 0.15); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3);">Anime / Hype</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px; min-height: 36px;">
            Expressive, cheerful, and fast-paced. Perfect for hype gaming and interactive chat reactions.
          </p>
          <div style="display: flex; gap: 8px;">
            <button class="btn-secondary" style="font-size: 11px;" onclick="previewVoiceStore('nova')">▶️ Play Sample</button>
            <button class="btn-primary" style="font-size: 11px;" id="btn-voice-nova" onclick="installVoiceStore('nova', 'Nova (Anime Female)')">⬇️ Install (0ms Offline)</button>
          </div>
        </div>

        <!-- Voice 2 -->
        <div class="card" style="margin-bottom: 0; background: #0c1222; border-color: #1e293b;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #fff;">Kael</div>
              <div style="font-size: 11px; color: #38bdf8;">Deep FM Radio Announcer</div>
            </div>
            <span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3);">Deep / Radio</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px; min-height: 36px;">
            Resonant, bass-heavy broadcast DJ voice. Ideal for chill late-night talk streams and podcasting.
          </p>
          <div style="display: flex; gap: 8px;">
            <button class="btn-secondary" style="font-size: 11px;" onclick="previewVoiceStore('kael')">▶️ Play Sample</button>
            <button class="btn-primary" style="font-size: 11px;" id="btn-voice-kael" onclick="installVoiceStore('kael', 'Kael (Deep Radio)')">⬇️ Install (0ms Offline)</button>
          </div>
        </div>

        <!-- Voice 3 -->
        <div class="card" style="margin-bottom: 0; background: #0c1222; border-color: #1e293b;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #fff;">Arthur</div>
              <div style="font-size: 11px; color: #38bdf8;">Distinguished British Butler</div>
            </div>
            <span class="badge" style="background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3);">British / Formal</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px; min-height: 36px;">
            Polite, crisp UK English with formal tone. Reads chat comments with butler-like elegance.
          </p>
          <div style="display: flex; gap: 8px;">
            <button class="btn-secondary" style="font-size: 11px;" onclick="previewVoiceStore('arthur')">▶️ Play Sample</button>
            <button class="btn-primary" style="font-size: 11px;" id="btn-voice-arthur" onclick="installVoiceStore('arthur', 'Arthur (British Butler)')">⬇️ Install (0ms Offline)</button>
          </div>
        </div>

        <!-- Voice 4 -->
        <div class="card" style="margin-bottom: 0; background: #0c1222; border-color: #1e293b;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #fff;">Viper</div>
              <div style="font-size: 11px; color: #38bdf8;">Esports Shoutcaster</div>
            </div>
            <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);">Gaming / FPS</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px; min-height: 36px;">
            Fast, hype tournament commentator style. Built for high-kill FPS and battle royale streams.
          </p>
          <div style="display: flex; gap: 8px;">
            <button class="btn-secondary" style="font-size: 11px;" onclick="previewVoiceStore('viper')">▶️ Play Sample</button>
            <button class="btn-primary" style="font-size: 11px;" id="btn-voice-viper" onclick="installVoiceStore('viper', 'Viper (Esports Caster)')">⬇️ Install (0ms Offline)</button>
          </div>
        </div>

        <!-- Voice 5 -->
        <div class="card" style="margin-bottom: 0; background: #0c1222; border-color: #1e293b;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #fff;">Luna</div>
              <div style="font-size: 11px; color: #38bdf8;">Calm & Cozy Storyteller</div>
            </div>
            <span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3);">Cozy / ASMR</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px; min-height: 36px;">
            Soft, gentle, relaxing voice. Ideal for art streams, cozy farming games, and quiet evening streams.
          </p>
          <div style="display: flex; gap: 8px;">
            <button class="btn-secondary" style="font-size: 11px;" onclick="previewVoiceStore('luna')">▶️ Play Sample</button>
            <button class="btn-primary" style="font-size: 11px;" id="btn-voice-luna" onclick="installVoiceStore('luna', 'Luna (Cozy Narrator)')">⬇️ Install (0ms Offline)</button>
          </div>
        </div>

        <!-- Voice 6 -->
        <div class="card" style="margin-bottom: 0; background: #0c1222; border-color: #1e293b;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #fff;">Thor</div>
              <div style="font-size: 11px; color: #38bdf8;">Nordic Warrior / Barbarian</div>
            </div>
            <span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3);">Fantasy / Epic</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px; min-height: 36px;">
            Thunderous, roaring, epic fantasy character. Turns simple chat messages into battle declarations.
          </p>
          <div style="display: flex; gap: 8px;">
            <button class="btn-secondary" style="font-size: 11px;" onclick="previewVoiceStore('thor')">▶️ Play Sample</button>
            <button class="btn-primary" style="font-size: 11px;" id="btn-voice-thor" onclick="installVoiceStore('thor', 'Thor (Nordic Warrior)')">⬇️ Install (0ms Offline)</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 4: Settings & Audio Routing -->
  <div id="tab-settings" class="tab-content">
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
      <!-- Audio Routing Card -->
      <div class="card">
        <div class="card-title">Audio Hardware & Output Routing</div>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;">
          Choose which headphones, speaker, or virtual audio channel (e.g. Elgato Wave Link, SteelSeries Sonar, GoXLR) this app sends speech sound to.
        </p>
        <label>Audio Output Device</label>
        <select id="audio-device-select" style="margin-bottom: 14px;" onchange="changeAudioDevice()"></select>

        <label>TTS Speech Volume: <span id="set-vol-label">100%</span></label>
        <input type="range" id="set-vol-slider" min="0" max="1" step="0.05" value="1" style="width: 100%; margin-bottom: 14px;" oninput="changeVolume(this.value)" />

        <div class="btn-row">
          <button class="btn-secondary" onclick="testAudioDevice()">🔊 Play Test Sound</button>
        </div>
      </div>

      <!-- App Updates & System Card -->
      <div class="card">
        <div class="card-title">Software Updates & System</div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
          <div>
            <div style="font-size: 14px; font-weight: 700; color: #fff;">TikTok Live TTS Studio</div>
            <div style="font-size: 12px; color: var(--text-muted);">Current Installed Version: <b id="settings-version">v1.4.0</b></div>
          </div>
          <button class="btn-secondary" style="flex: 0 0 140px;" onclick="checkForUpdates(true)">🔄 Check for Update</button>
        </div>
        <div id="settings-update-status" style="font-size: 12px; color: #38bdf8; margin-bottom: 14px;">App is currently up to date.</div>
        
        <div style="border-top: 1px solid var(--card-border); padding-top: 14px;">
          <div style="font-size: 12px; font-weight: 700; color: #cbd5e1; margin-bottom: 6px;">PORT CONFIGURATION</div>
          <div style="font-size: 12px; color: var(--text-muted);">Active Internal Engine Port: <b style="color: #38bdf8;" id="settings-port">28730</b> (Private conflict-free range)</div>
        </div>
      </div>
    </div>
  </div>

  <footer>
    <span>⚖️ Independent open-source tool. Not affiliated with TikTok or ByteDance. Streamers are responsible for broadcast content.</span>
    <span>TikTok Live TTS Studio</span>
  </footer>

  <script>
    let currentEngine = "instant";
    let currentVolume = 1.0;
    let savedNativeVoice = "";
    let selectedAudioDevice = "default";
    let audioQueue = [];
    let isPlaying = false;
    let activeAudio = null;
    let browserVoices = [];
    let installedStoreVoices = [];
    let latestReleaseNotes = "";
    let latestVersionStr = "";

    function switchTab(tabId) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
      const content = document.getElementById('tab-' + tabId);
      const btn = document.getElementById('nav-btn-' + tabId);
      if (content) content.classList.add('active');
      if (btn) btn.classList.add('active');
    }

    // Synthesized pleasant Web Audio gift chime
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
        osc.frequency.setValueAtTime(880, now);          // A5
        osc.frequency.exponentialRampToValueAtTime(1320, now + 0.12); // E6

        gain.gain.setValueAtTime(currentVolume * 0.4, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);

        osc.connect(gain);
        gain.connect(audioCtx.destination);

        osc.start(now);
        osc.stop(now + 0.36);
      } catch (e) {}
    }

    const ws = new WebSocket(`ws://${location.host}/ws`);

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
            document.getElementById('update-pill-text').textContent = `✨ v${data.latest_version} Available`;
          }
          const stEl = document.getElementById('settings-update-status');
          if (stEl) {
            stEl.innerHTML = `<span style="color:#34d399;">Update v${data.latest_version} available!</span> <button class="btn-primary" style="margin-left:8px; padding:3px 10px; font-size:11px;" onclick="openUpdateModal()">View & Install</button>`;
          }
          if (manual) openUpdateModal();
        } else {
          if (manual) alert("TikTok Live TTS Studio is already up to date (v" + data.current_version + ")!");
        }
      } catch (e) {}
    }

    function openUpdateModal() {
      document.getElementById('modal-title').textContent = `What's New in v${latestVersionStr || 'Latest'}`;
      const lines = latestReleaseNotes.split('\\n').filter(l => l.trim().length > 0);
      let html = '<ul>';
      lines.forEach(line => {
        html += `<li>${line.replace(/^[*-]\\s*/, '')}</li>`;
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
      btn.textContent = "⏳ Preparing update...";
      try {
        const res = await fetch('/api/install-update', { method: 'POST' });
        const data = await res.json();
        if (data.status !== 'ok') {
          alert("Update error: " + data.message);
          btn.disabled = false;
          btn.textContent = "⚡ Update & Restart Now";
        }
      } catch (err) {
        alert("Update error: " + err);
        btn.disabled = false;
        btn.textContent = "⚡ Update & Restart Now";
      }
    }

    function populateBrowserVoices() {
      browserVoices = window.speechSynthesis.getVoices();
      const select = document.getElementById('browser-voice-select');
      select.innerHTML = '';
      let matchedIndex = -1;
      
      // Native voices
      browserVoices.forEach((v, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = `${v.name} (${v.lang})`;
        if (savedNativeVoice && v.name === savedNativeVoice) {
          matchedIndex = i;
        } else if (!savedNativeVoice && matchedIndex === -1 && (v.default || v.name.includes('Natural') || v.lang.startsWith('en'))) {
          matchedIndex = i;
        }
        select.appendChild(opt);
      });

      // Installed Voice Store voices
      if (installedStoreVoices.length > 0) {
        const grp = document.createElement('optgroup');
        grp.label = "Installed from Voice Store";
        installedStoreVoices.forEach(sv => {
          const opt = document.createElement('option');
          opt.value = "store:" + sv;
          opt.textContent = `★ ${sv} (0ms Offline)`;
          if (savedNativeVoice === sv) opt.selected = true;
          grp.appendChild(opt);
        });
        select.appendChild(grp);
      }

      if (matchedIndex >= 0) {
        select.value = matchedIndex;
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
        defaultOpt.textContent = 'Default Audio Output (System Sound)';
        select.appendChild(defaultOpt);
        audioOutputs.forEach(d => {
          if (d.deviceId !== 'default') {
            const opt = document.createElement('option');
            opt.value = d.deviceId;
            opt.textContent = d.label || `Speaker/Headphones (${d.deviceId.slice(0, 6)}...)`;
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

    function setEngine(mode) {
      currentEngine = mode;
      document.getElementById('opt-instant').className = 'engine-option' + (mode === 'instant' ? ' active' : '');
      document.getElementById('opt-cloud').className = 'engine-option' + (mode === 'cloud' ? ' active' : '');
      document.getElementById('instant-voice-block').style.display = (mode === 'instant' ? 'block' : 'none');
      document.getElementById('cloud-voice-block').style.display = (mode === 'cloud' ? 'block' : 'none');
      
      const badge = document.getElementById('latency-badge');
      if (mode === 'instant') {
        badge.innerHTML = '⚡ Instant Mode (&lt;50ms)';
        badge.className = 'badge latency';
      } else {
        badge.innerHTML = '☁️ Cloud Mode (~3s)';
        badge.className = 'badge';
      }
      updateSettings();
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
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
        if (cfg.engine) setEngine(cfg.engine);
        if (cfg.voice) document.getElementById('cloud-voice-select').value = cfg.voice;
        if (cfg.native_voice_name) {
          savedNativeVoice = cfg.native_voice_name;
          populateBrowserVoices();
        }
        if (cfg.audio_device_id) {
          selectedAudioDevice = cfg.audio_device_id;
        }
        if (cfg.installed_voices) {
          installedStoreVoices = cfg.installed_voices;
          installedStoreVoices.forEach(vId => {
            const btn = document.getElementById('btn-voice-' + vId);
            if (btn) {
              btn.textContent = "✓ Installed";
              btn.className = "btn-secondary";
            }
          });
          populateBrowserVoices();
        }
        if (cfg.volume !== undefined) {
          document.getElementById('vol-slider').value = cfg.volume;
          document.getElementById('set-vol-slider').value = cfg.volume;
          changeVolume(cfg.volume);
        }
        if (cfg.cooldown) document.getElementById('cooldown-input').value = cfg.cooldown;
        if (cfg.max_chars) document.getElementById('maxlen-input').value = cfg.max_chars;
        if (cfg.banned_words) document.getElementById('banned-input').value = cfg.banned_words;
        if (cfg.role_filter) document.getElementById('role-filter').value = cfg.role_filter;
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
        speakInstant(data.item);
      } else if (data.type === 'tts_audio') {
        audioQueue.push(data);
        updateQueue(data.queue_size || audioQueue.length);
        playNextCloud();
      } else if (data.type === 'client_skip') {
        skipAudio();
      } else if (data.type === 'update_progress') {
        const btn = document.getElementById('modal-update-btn');
        if (btn) btn.textContent = data.status;
      }
    };

    function speakInstant(item) {
      if (!('speechSynthesis' in window)) return;
      const userEl = document.getElementById('spk-user');
      const textEl = document.getElementById('spk-text');
      userEl.style.display = 'block';
      userEl.textContent = '⚡ ' + item.user;
      textEl.className = 'speaking-text';
      textEl.textContent = item.display || item.text;

      const utterance = new SpeechSynthesisUtterance(item.text);
      utterance.volume = currentVolume;
      const voiceIdx = document.getElementById('browser-voice-select').value;
      if (browserVoices[voiceIdx]) utterance.voice = browserVoices[voiceIdx];

      utterance.onend = finishPlay;
      utterance.onerror = finishPlay;

      speechSynthesis.speak(utterance);
    }

    function playNextCloud() {
      if (isPlaying || audioQueue.length === 0) return;
      isPlaying = true;
      const item = audioQueue.shift();

      const userEl = document.getElementById('spk-user');
      const textEl = document.getElementById('spk-text');
      userEl.style.display = 'block';
      userEl.textContent = '☁️ ' + item.user;
      textEl.className = 'speaking-text';
      textEl.textContent = item.display || item.text;

      activeAudio = new Audio("data:audio/mp3;base64," + item.audio_b64);
      if (activeAudio.setSinkId && selectedAudioDevice !== 'default') {
        activeAudio.setSinkId(selectedAudioDevice);
      }
      activeAudio.volume = currentVolume;
      activeAudio.onended = finishPlay;
      activeAudio.onerror = finishPlay;

      activeAudio.play().catch(e => {
        finishPlay();
      });
    }

    function finishPlay() {
      isPlaying = false;
      activeAudio = null;
      const userEl = document.getElementById('spk-user');
      const textEl = document.getElementById('spk-text');
      userEl.style.display = 'none';
      textEl.className = 'speaking-text speaking-idle';
      textEl.textContent = 'No audio currently playing. Waiting for chat...';
      if (currentEngine === 'cloud') playNextCloud();
    }

    function skipAudio() {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      if (activeAudio) {
        activeAudio.pause();
        activeAudio = null;
      }
      finishPlay();
    }

    function updateStatus(status, msg) {
      const badge = document.getElementById('status-badge');
      const text = document.getElementById('status-text');
      badge.className = 'badge ' + status;
      text.textContent = status.toUpperCase();
      document.getElementById('status-msg').textContent = msg || '';
    }

    function updateQueue(count) {
      document.getElementById('queue-count').textContent = count;
    }

    function addLogItem(item) {
      const list = document.getElementById('log-list');
      if (list.children.length === 1 && list.children[0].textContent.includes('Live comments')) {
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
        <div>
          ${fanBadge}
          <span class="log-user">${item.user}</span>
          <span class="log-text">${item.text} ${item.reason ? '<span style="color:#f87171;">(' + item.reason + ')</span>' : ''}</span>
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
      document.getElementById('vol-label').textContent = Math.round(currentVolume * 100) + '%';
      document.getElementById('set-vol-label').textContent = Math.round(currentVolume * 100) + '%';
      document.getElementById('vol-slider').value = currentVolume;
      document.getElementById('set-vol-slider').value = currentVolume;
      if (activeAudio) activeAudio.volume = currentVolume;
    }

    function applyPreset(text) {
      document.getElementById('test-text').value = text;
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
      const text = document.getElementById('test-text').value.trim();
      if (!text) return;
      await fetch('/api/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text })
      });
      document.getElementById('test-text').value = '';
    }

    async function clearQueue() {
      audioQueue = [];
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      await fetch('/api/clear-queue', { method: 'POST' });
    }

    document.getElementById('browser-voice-select').onchange = () => {
      const idx = document.getElementById('browser-voice-select').value;
      if (browserVoices[idx]) savedNativeVoice = browserVoices[idx].name;
      updateSettings();
    };

    let currentLogFilter = 'all';
    function filterLog(type) {
      currentLogFilter = type;
      ['all', 'spoken', 'gifts', 'blocked'].forEach(t => {
        const btn = document.getElementById('flt-' + t);
        if (btn) {
          if (t === type) {
            btn.style.background = 'var(--accent-cyan)';
            btn.style.color = '#000';
          } else {
            btn.style.background = '#1e293b';
            btn.style.color = '#f1f5f9';
          }
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
      alert("TikTok Live Studio Overlay URL copied to clipboard!\\n\\nIn TikTok Live Studio: Click 'Add Source' ➔ 'Link / Browser Source' (Width: 850, Height: 250).");
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

    function previewVoiceStore(name) {
      const sampleTexts = {
        nova: "Hey chat! Thank you so much for the hype! Let's go!",
        kael: "Welcome in to the late night stream. Sit back, relax, and enjoy the vibe.",
        arthur: "Good evening everyone. It is an absolute pleasure to be reading your comments.",
        viper: "Triple kill! Watch the flank! They cannot stop us right now!",
        luna: "Welcome to our cozy stream today. I hope you're having a calm and wonderful day.",
        thor: "By the thunder gods! We march to victory! Bring on the battle!"
      };
      const text = sampleTexts[name] || "Hello from TikTok Live TTS Studio!";
      if ('speechSynthesis' in window) {
        const u = new SpeechSynthesisUtterance(text);
        u.volume = currentVolume;
        speechSynthesis.speak(u);
      }
    }

    function installVoiceStore(vId, vName) {
      if (!installedStoreVoices.includes(vId)) {
        installedStoreVoices.push(vId);
        const btn = document.getElementById('btn-voice-' + vId);
        if (btn) {
          btn.textContent = "✓ Installed";
          btn.className = "btn-secondary";
        }
        savedNativeVoice = vName;
        populateBrowserVoices();
        updateSettings();
        alert(`Installed '${vName}' successfully!\nIt is now active as an offline 0ms voice.`);
      }
    }

    async function updateSettings() {
      const nativeSelect = document.getElementById('browser-voice-select');
      const selectedNativeVoice = (browserVoices[nativeSelect.value] ? browserVoices[nativeSelect.value].name : savedNativeVoice);
      const payload = {
        engine: currentEngine,
        voice: document.getElementById('cloud-voice-select').value,
        native_voice_name: selectedNativeVoice,
        audio_device_id: selectedAudioDevice,
        installed_voices: installedStoreVoices,
        volume: currentVolume,
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
  </script>
</body>
</html>
"""

OVERLAY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>TikTok Live TTS Overlay</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: transparent;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      align-items: center;
      height: 100vh;
      padding: 24px;
    }
    #subtitle-card {
      opacity: 0;
      transform: translateY(20px) scale(0.96);
      transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
      background: rgba(15, 23, 42, 0.88);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 16px;
      padding: 16px 24px;
      max-width: 850px;
      width: 90%;
      box-shadow: 0 12px 35px rgba(0, 0, 0, 0.6), 0 0 20px rgba(56, 189, 248, 0.15);
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
      font-size: 11px;
      font-weight: 800;
      padding: 2px 7px;
      border-radius: 6px;
      letter-spacing: 0.5px;
    }
    .user-name {
      font-weight: 800;
      font-size: 15px;
      color: #38bdf8;
      text-shadow: 0 2px 4px rgba(0,0,0,0.6);
      margin-bottom: 2px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .speech-text {
      font-size: 20px;
      font-weight: 600;
      color: #ffffff;
      line-height: 1.35;
      text-shadow: 0 2px 6px rgba(0,0,0,0.8);
      word-break: break-word;
    }
    .equalizer {
      display: flex;
      align-items: flex-end;
      gap: 3px;
      height: 22px;
      min-width: 20px;
    }
    .bar {
      width: 4px;
      background: #38bdf8;
      border-radius: 2px;
      animation: bounce 0.8s ease-in-out infinite alternate;
    }
    .bar:nth-child(2) { animation-delay: 0.2s; height: 16px; background: #06b6d4; }
    .bar:nth-child(3) { animation-delay: 0.4s; height: 22px; background: #10b981; }
    .bar:nth-child(4) { animation-delay: 0.1s; height: 12px; background: #38bdf8; }
    @keyframes bounce {
      0% { height: 4px; }
      100% { height: 22px; }
    }
    #gift-card {
      position: absolute;
      top: 24px;
      opacity: 0;
      transform: translateY(-20px) scale(0.9);
      transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
      background: linear-gradient(135deg, rgba(245, 158, 11, 0.95), rgba(217, 119, 6, 0.95));
      border: 2px solid #fde68a;
      border-radius: 14px;
      padding: 12px 24px;
      box-shadow: 0 10px 30px rgba(245, 158, 11, 0.4);
      color: #000;
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 800;
      font-size: 16px;
    }
    #gift-card.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
    .gift-icon { font-size: 26px; }
  </style>
</head>
<body>
  <div id="gift-card">
    <span class="gift-icon">🎁</span>
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
    const ws = new WebSocket(`ws://${location.host}/ws`);
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

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'tts_instant') {
        showSubtitle(data.item.user, data.item.display || data.item.text, data.item.fan_level);
      } else if (data.type === 'speaking_start') {
        showSubtitle(data.item.user, data.item.display || data.item.text, data.item.fan_level);
      } else if (data.type === 'chat_log' && data.data.type === 'gift') {
        showGiftAlert(`${data.data.user} ${data.data.text}`);
      } else if (data.type === 'client_skip') {
        subCard.className = '';
      }
    };
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
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', p)) != 0:
                return p
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

    time.sleep(1.0)

    try:
        import webview
        icon_file = os.path.join(BUNDLE_DIR, "icon.ico")
        if not os.path.exists(icon_file):
            icon_file = os.path.join(BASE_DIR, "icon.ico")
        window = webview.create_window(
            title="TikTok Live TTS Studio",
            url=f"http://127.0.0.1:{active_port}",
            width=1320,
            height=860,
            min_size=(950, 640)
        )
        webview.start()
    except Exception:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{active_port}")
        while True:
            time.sleep(1)
