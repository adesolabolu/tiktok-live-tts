import sys
import os

# PyInstaller --windowed / --noconsole fix:
# When running with no console on Windows, sys.stdout and sys.stderr are None,
# which causes uvicorn logging to crash with AttributeError: 'NoneType' object has no attribute 'isatty'.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import asyncio
import base64
import time
import uuid
import threading
import webbrowser
import httpx
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import edge_tts
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, GiftEvent, DisconnectEvent

CURRENT_VERSION = "1.0.1"
GITHUB_REPO = "adesolabolu/tiktok-live-tts"

app = FastAPI(title="TikTok Live TTS Studio", version=CURRENT_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AppState:
    def __init__(self):
        self.username: Optional[str] = None
        self.client: Optional[TikTokLiveClient] = None
        self.task: Optional[asyncio.Task] = None
        self.status: str = "disconnected"
        self.status_msg: str = "Ready to connect"
        self.engine: str = "instant"  # "instant" (0ms native) or "cloud" (Edge-TTS)
        self.voice: str = "en-US-AvaNeural"
        self.volume: float = 1.0
        self.cooldown: int = 5
        self.max_chars: int = 120
        self.banned_words: list[str] = []
        self.tts_queue: asyncio.Queue = asyncio.Queue()
        self.user_last_seen: dict[str, float] = {}
        self.websockets: set[WebSocket] = set()
        self.current_speaking: Optional[dict] = None
        self.latest_release_info: Optional[dict] = None

state = AppState()

class ConnectRequest(BaseModel):
    username: str

class SpeakRequest(BaseModel):
    text: str
    engine: Optional[str] = None
    voice: Optional[str] = None

class SettingsRequest(BaseModel):
    engine: Optional[str] = None
    voice: Optional[str] = None
    volume: Optional[float] = None
    cooldown: Optional[int] = None
    max_chars: Optional[int] = None
    banned_words: Optional[str] = None

async def broadcast(data: dict):
    dead = set()
    for ws in list(state.websockets):
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    state.websockets.difference_update(dead)

def check_filters(user_id: str, text: str) -> tuple[bool, str]:
    clean_text = text.strip()
    if len(clean_text) > state.max_chars:
        clean_text = clean_text[:state.max_chars]
    
    lower_text = clean_text.lower()
    for word in state.banned_words:
        if word and word.lower() in lower_text:
            return False, f"Contains blacklisted word: {word}"
            
    now = time.time()
    last = state.user_last_seen.get(user_id, 0)
    if (now - last) < state.cooldown:
        remaining = int(state.cooldown - (now - last))
        return False, f"Cooldown active ({remaining}s left)"
        
    state.user_last_seen[user_id] = now
    return True, clean_text

async def handle_new_tts_item(user: str, raw_text: str, display_text: str):
    item = {
        "id": str(uuid.uuid4()),
        "user": user,
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
    state.status = "connecting"
    state.status_msg = f"Connecting to @{clean_user}..."
    await broadcast({"type": "status", "status": state.status, "message": state.status_msg})

    try:
        client = TikTokLiveClient(unique_id=clean_user)
        state.client = client

        is_live = await client.is_live()
        if not is_live:
            state.status = "offline"
            state.status_msg = f"@{clean_user} is currently offline. Start livestreaming or check the username."
            await broadcast({"type": "status", "status": state.status, "message": state.status_msg})
            return

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            state.status = "connected"
            state.status_msg = f"🟢 Connected to @{clean_user} live room!"
            await broadcast({"type": "status", "status": state.status, "message": state.status_msg})

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            allowed, result = check_filters(event.user.unique_id, event.comment)
            log_item = {
                "type": "comment",
                "user": event.user.nickname,
                "text": event.comment,
                "allowed": allowed,
                "reason": result if not allowed else "",
                "time": time.strftime("%H:%M:%S")
            }
            await broadcast({"type": "chat_log", "data": log_item})

            if allowed:
                speech_text = f"{event.user.nickname} says: {result}"
                await handle_new_tts_item(event.user.nickname, speech_text, event.comment)

        @client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            if event.gift.streakable and event.streaking:
                return
            log_item = {
                "type": "gift",
                "user": event.user.nickname,
                "text": f"Sent {event.repeat_count}x {event.gift.name}",
                "allowed": True,
                "reason": "",
                "time": time.strftime("%H:%M:%S")
            }
            await broadcast({"type": "chat_log", "data": log_item})

            speech_text = f"Thank you {event.user.nickname} for sending {event.repeat_count} {event.gift.name}!"
            await handle_new_tts_item(event.user.nickname, speech_text, f"Sent {event.repeat_count}x {event.gift.name}")

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
        except Exception as e:
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
        "repo": GITHUB_REPO
    }

@app.get("/api/check-update")
async def api_check_update():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, headers={"User-Agent": "TikTokLiveTTS-App"})
            if resp.status_code == 200:
                data = resp.json()
                latest_tag = data.get("tag_name", "").lstrip("v")
                has_update = latest_tag and latest_tag > CURRENT_VERSION
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
        "release_url": f"https://github.com/{GITHUB_REPO}/releases"
    }

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
    if req.engine:
        state.engine = req.engine
    if req.voice:
        state.voice = req.voice
    if req.volume is not None:
        state.volume = req.volume
    if req.cooldown is not None:
        state.cooldown = req.cooldown
    if req.max_chars is not None:
        state.max_chars = req.max_chars
    if req.banned_words is not None:
        state.banned_words = [w.strip() for w in req.banned_words.split(",") if w.strip()]
    return {
        "status": "ok",
        "engine": state.engine,
        "voice": state.voice,
        "volume": state.volume,
        "cooldown": state.cooldown,
        "max_chars": state.max_chars,
        "banned_words": state.banned_words
    }

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.websockets.add(ws)
    await ws.send_json({
        "type": "init",
        "version": CURRENT_VERSION,
        "status": state.status,
        "message": state.status_msg,
        "username": state.username,
        "engine": state.engine,
        "voice": state.voice,
        "volume": state.volume,
        "cooldown": state.cooldown,
        "max_chars": state.max_chars,
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
      padding: 16px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .logo-group { display: flex; align-items: center; gap: 12px; }
    .logo-icon { font-size: 26px; }
    .logo-title { font-size: 20px; font-weight: 700; color: #fff; letter-spacing: -0.5px; }
    .version-tag { font-size: 11px; padding: 2px 8px; border-radius: 6px; background: #1e293b; color: #94a3b8; font-weight: 600; margin-left: 6px; }
    .header-badges { display: flex; gap: 10px; align-items: center; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 600;
      background: #1e293b;
      color: var(--text-muted);
    }
    .badge.connected { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge.offline { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
    .badge.connecting { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge.latency { background: rgba(6, 182, 212, 0.15); color: #38bdf8; border: 1px solid rgba(6, 182, 212, 0.3); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }

    #update-banner {
      display: none;
      background: linear-gradient(90deg, #1e3a8a, #0284c7);
      color: #fff;
      padding: 10px 24px;
      font-size: 13px;
      font-weight: 600;
      text-align: center;
      justify-content: center;
      align-items: center;
      gap: 12px;
    }
    #update-banner a {
      color: #38bdf8;
      background: rgba(255, 255, 255, 0.15);
      padding: 4px 12px;
      border-radius: 6px;
      text-decoration: none;
      font-weight: 700;
    }

    .main-container {
      display: grid;
      grid-template-columns: 400px 1fr;
      gap: 24px;
      padding: 24px 28px;
      flex: 1;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px;
      margin-bottom: 20px;
    }
    .card-title {
      font-size: 15px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--accent-cyan);
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    label { display: block; font-size: 13px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px; }
    input[type="text"], input[type="number"], select {
      width: 100%;
      background: #090d16;
      border: 1px solid #2d3748;
      border-radius: 8px;
      padding: 10px 14px;
      color: #fff;
      font-size: 14px;
      outline: none;
      transition: border 0.2s;
    }
    input[type="text"]:focus, select:focus { border-color: var(--accent-primary); }
    .btn-row { display: flex; gap: 10px; margin-top: 12px; }
    button {
      flex: 1;
      padding: 10px 16px;
      border-radius: 8px;
      border: none;
      font-weight: 600;
      font-size: 14px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-primary { background: var(--accent-primary); color: #000; }
    .btn-primary:hover { background: #059669; }
    .btn-danger { background: var(--accent-danger); color: #fff; }
    .btn-danger:hover { background: #dc2626; }
    .btn-secondary { background: #1e293b; color: #fff; }
    .btn-secondary:hover { background: #334155; }

    .engine-toggle {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      background: #090d16;
      padding: 4px;
      border-radius: 10px;
      border: 1px solid #2d3748;
      margin-bottom: 16px;
    }
    .engine-option {
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      text-align: center;
      cursor: pointer;
      color: var(--text-muted);
      transition: all 0.2s;
    }
    .engine-option.active {
      background: var(--accent-primary);
      color: #000;
      box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
    }

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
      border-radius: 10px;
      padding: 14px 18px;
      margin-bottom: 12px;
    }
    .speaking-user { font-size: 14px; font-weight: 700; color: #38bdf8; margin-bottom: 4px; }
    .speaking-text { font-size: 18px; font-weight: 500; color: #fff; line-height: 1.4; }
    .speaking-idle { color: var(--text-muted); font-style: italic; font-size: 14px; }

    .log-container {
      background: #090d16;
      border: 1px solid #1e293b;
      border-radius: 10px;
      height: 480px;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .log-item {
      padding: 8px 12px;
      border-radius: 6px;
      background: #111827;
      font-size: 13px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .log-item.gift { border-left: 3px solid #f59e0b; background: rgba(245, 158, 11, 0.08); }
    .log-item.blocked { opacity: 0.5; border-left: 3px solid var(--accent-danger); }
    .log-user { font-weight: 600; color: #38bdf8; margin-right: 8px; }
    .log-text { color: #f1f5f9; }
    .log-time { font-size: 11px; color: #64748b; margin-left: 12px; white-space: nowrap; }

    #audio-unlock-banner {
      background: #f59e0b;
      color: #000;
      font-weight: 600;
      padding: 10px;
      text-align: center;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <div id="update-banner">
    <span id="update-text">🚀 A new version of TikTok Live TTS is available!</span>
    <a id="update-link" href="#" target="_blank">Download Update</a>
  </div>

  <div id="audio-unlock-banner" onclick="unlockAudio()">
    🔊 Audio is muted by browser policy. Click anywhere here to ENABLE live speech!
  </div>

  <header>
    <div class="logo-group">
      <span class="logo-icon">🎙️</span>
      <span class="logo-title">TikTok Live TTS Studio</span>
      <span class="version-tag" id="app-version">v1.0.1</span>
    </div>
    <div class="header-badges">
      <div id="latency-badge" class="badge latency">
        <span>⚡ Real-Time Mode (&lt;50ms)</span>
      </div>
      <div id="status-badge" class="badge">
        <span class="dot"></span>
        <span id="status-text">Disconnected</span>
      </div>
    </div>
  </header>

  <div class="main-container">
    <div>
      <div class="card">
        <div class="card-title">Stream Connection</div>
        <label>TikTok @Username</label>
        <input type="text" id="username-input" placeholder="e.g. your_username" />
        <div class="btn-row">
          <button class="btn-primary" onclick="connectStream()">Connect</button>
          <button class="btn-secondary" onclick="disconnectStream()">Disconnect</button>
        </div>
        <p id="status-msg" style="font-size: 12px; color: var(--text-muted); margin-top: 10px;"></p>
      </div>

      <div class="card">
        <div class="card-title">Voice Engine Mode</div>
        <div class="engine-toggle">
          <div id="opt-instant" class="engine-option active" onclick="setEngine('instant')">
            ⚡ Instant Native (&lt;50ms)
          </div>
          <div id="opt-cloud" class="engine-option" onclick="setEngine('cloud')">
            ☁️ Cloud Neural (HD)
          </div>
        </div>

        <div id="instant-voice-block">
          <label>Native Browser/OS Voice</label>
          <select id="browser-voice-select"></select>
          <p style="font-size: 11px; color: #34d399; margin-top: 6px;">Zero network delay. Speaks instantly the millisecond chat sends a comment.</p>
        </div>

        <div id="cloud-voice-block" style="display: none;">
          <label>Microsoft Cloud Neural Voice</label>
          <select id="cloud-voice-select" onchange="updateSettings()">
            <option value="en-US-AvaNeural">Ava (US Female - Natural/Friendly)</option>
            <option value="en-US-ChristopherNeural">Christopher (US Male - Energetic/Hype)</option>
            <option value="en-GB-SoniaNeural">Sonia (British Female - Clean/Crisp)</option>
            <option value="en-US-AndrewNeural">Andrew (US Male - Warm/Casual)</option>
            <option value="en-US-BrianNeural">Brian (US Male - Deep/Radio)</option>
            <option value="en-US-EmmaNeural">Emma (US Female - Cheerful)</option>
          </select>
          <p style="font-size: 11px; color: #f59e0b; margin-top: 6px;">High fidelity, but requires ~3-5s network buffering per sentence.</p>
        </div>

        <div style="margin-top: 14px;">
          <label>Volume: <span id="vol-label">100%</span></label>
          <input type="range" id="vol-slider" min="0" max="1" step="0.05" value="1" style="width: 100%;" oninput="changeVolume(this.value)" />
        </div>
      </div>

      <div class="card">
        <div class="card-title">Safety & Anti-Troll</div>
        <label>Per-User Cooldown (seconds)</label>
        <input type="number" id="cooldown-input" value="5" min="1" max="60" onchange="updateSettings()" style="margin-bottom: 12px;" />

        <label>Max Text Length (characters)</label>
        <input type="number" id="maxlen-input" value="120" min="20" max="300" onchange="updateSettings()" style="margin-bottom: 12px;" />

        <label>Banned Words (comma separated)</label>
        <input type="text" id="banned-input" placeholder="badword1, troll2" onchange="updateSettings()" />
      </div>

      <div class="card">
        <div class="card-title">Test Audio Sandbox</div>
        <input type="text" id="test-text" placeholder="Type a phrase to test live speech..." />
        <button class="btn-primary" style="margin-top: 10px; width: 100%;" onclick="sendTestSpeech()">Speak Test Message</button>
      </div>
    </div>

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
        <div class="card-title">Live Chat & Gift Activity</div>
        <div id="log-list" class="log-container">
          <div style="color: #64748b; text-align: center; margin-top: 40px;">Live comments and gifts will stream here when connected...</div>
        </div>
      </div>
    </div>
  </div>

  <script>
    let currentEngine = "instant";
    let currentVolume = 1.0;
    let audioQueue = [];
    let isPlaying = false;
    let activeAudio = null;
    let browserVoices = [];

    const ws = new WebSocket(`ws://${location.host}/ws`);

    async function checkForUpdates() {
      try {
        const res = await fetch('/api/check-update');
        const data = await res.json();
        if (data.has_update) {
          const banner = document.getElementById('update-banner');
          banner.style.display = 'flex';
          document.getElementById('update-text').textContent = `🚀 Update available: v${data.latest_version} (Current: v${data.current_version})`;
          document.getElementById('update-link').href = data.release_url;
        }
      } catch (e) {}
    }

    function populateBrowserVoices() {
      browserVoices = window.speechSynthesis.getVoices();
      const select = document.getElementById('browser-voice-select');
      select.innerHTML = '';
      browserVoices.forEach((v, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = `${v.name} (${v.lang})`;
        if (v.default || v.name.includes('Natural') || v.lang.startsWith('en')) {
          if (!select.value) opt.selected = true;
        }
        select.appendChild(opt);
      });
    }

    if ('speechSynthesis' in window) {
      speechSynthesis.onvoiceschanged = populateBrowserVoices;
      populateBrowserVoices();
    }

    function unlockAudio() {
      document.getElementById('audio-unlock-banner').style.display = 'none';
      if ('speechSynthesis' in window) {
        const u = new SpeechSynthesisUtterance('');
        speechSynthesis.speak(u);
      }
      const silent = new Audio("data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA");
      silent.play().catch(() => {});
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
        if (data.version) document.getElementById('app-version').textContent = 'v' + data.version;
        if (data.username) document.getElementById('username-input').value = data.username;
        if (data.engine) setEngine(data.engine);
        if (data.cooldown) document.getElementById('cooldown-input').value = data.cooldown;
        if (data.max_chars) document.getElementById('maxlen-input').value = data.max_chars;
        updateQueue(data.queue_size || 0);
        checkForUpdates();
      } else if (data.type === 'status') {
        updateStatus(data.status, data.message);
      } else if (data.type === 'queue_size') {
        updateQueue(data.size);
      } else if (data.type === 'chat_log') {
        addLogItem(data.data);
      } else if (data.type === 'tts_instant') {
        speakInstant(data.item);
      } else if (data.type === 'tts_audio') {
        audioQueue.push(data);
        updateQueue(data.queue_size || audioQueue.length);
        playNextCloud();
      } else if (data.type === 'client_skip') {
        skipAudio();
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
      activeAudio.volume = currentVolume;
      activeAudio.onended = finishPlay;
      activeAudio.onerror = finishPlay;

      activeAudio.play().catch(e => {
        console.warn("Autoplay block:", e);
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
      div.className = 'log-item ' + (item.type === 'gift' ? 'gift' : '') + (item.allowed === false ? ' blocked' : '');
      div.innerHTML = `
        <div>
          <span class="log-user">${item.user}</span>
          <span class="log-text">${item.text} ${item.reason ? '<span style="color:#f87171;">(' + item.reason + ')</span>' : ''}</span>
        </div>
        <span class="log-time">${item.time}</span>
      `;
      list.prepend(div);
      if (list.children.length > 100) list.lastChild.remove();
    }

    function changeVolume(val) {
      currentVolume = parseFloat(val);
      document.getElementById('vol-label').textContent = Math.round(currentVolume * 100) + '%';
      if (activeAudio) activeAudio.volume = currentVolume;
    }

    async function connectStream() {
      unlockAudio();
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
      unlockAudio();
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

    async function updateSettings() {
      const payload = {
        engine: currentEngine,
        voice: document.getElementById('cloud-voice-select').value,
        cooldown: parseInt(document.getElementById('cooldown-input').value) || 5,
        max_chars: parseInt(document.getElementById('maxlen-input').value) || 120,
        banned_words: document.getElementById('banned-input').value
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

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return HTML_CONTENT

if __name__ == "__main__":
    def launch_browser():
        time.sleep(1.2)
        webbrowser.open("http://127.0.0.1:8080")

    threading.Thread(target=launch_browser, daemon=True).start()
    import uvicorn
    # log_config=None prevents uvicorn from crashing when sys.stdout is redirected/None in windowed mode
    uvicorn.run(app, host="127.0.0.1", port=8080, log_config=None)
