# 🎙️ TikTok Live TTS Studio

A high-performance, standalone Text-to-Speech (TTS) studio engineered specifically for TikTok livestreamers. Connects to any TikTok livestream in real time using just a public `@username` and speaks chat comments, subscriber events, and gift alerts aloud with **zero audio latency** and **no passwords or API keys required**.

---

## ⚡ Key Highlights

* **🚀 1-Click Windows Setup (`TikTokLiveTTS-Setup.exe`):** Single-file Inno Setup installer. Installs cleanly to your PC, creates Desktop & Start Menu shortcuts, and features seamless in-app auto-updating.
* **⚡ Instant Zero-Lag Speech (<30ms):** Native hardware-accelerated speech synthesis directly through your system audio subsystem.
* **🎬 TikTok Live Studio Overlay (`/overlay`):** Dedicated transparent browser overlay HUD for TikTok Live Studio with animated live chat subtitles, fan badges, and gift announcements.
* **🎛️ 4-Tab Streamer Dashboard:**
  * **🎙️ Live TTS & Moderation:** Streamer controls, live chat monitor, manual speech trigger, anti-spam automute, and badge gating.
  * **🎬 TikTok Studio Overlay:** Custom subtitle display HUD, URL copy, and TikTok Live Studio setup guide.
  * **🏪 Voice Store:** Offline neural character voice catalog with interactive Play/Pause audio previews and 1-click installation.
  * **⚙️ Settings & Audio Routing:** Audio device selector (`navigator.mediaDevices`), cooldown timers, and safety filters.
* **🔒 Zero Credentials / Zero Login:** No TikTok password, session token, or official developer registration required.
* **🛡️ Streamer Moderation & Safety:**
  * **Command Prefix Filter:** Optionally require comments to start with a prefix (e.g., `.` or `!tts`) before being spoken, with automatic prefix stripping.
  * **Fan Club Level Gating:** Limit TTS to dedicated fans (e.g., Level 5+).
  * **Gifter Minimum Coins:** Limit gift announcements to gifts meeting coin thresholds.
  * **Anti-Spam Auto-Mute:** Automatically silences users who repeat the same comment repeatedly.
  * **Panic Button:** Instant "Skip Message" and "Clear Queue" controls.
* **🌐 Conflict-Free Port `28730`:** Runs on dedicated high-range port `28730` with an automatic scanner across ports 28730–28760 to guarantee zero collisions with local servers or dev tools.

---

## 📥 Installation

Download the official standalone installer from the [GitHub Releases](https://github.com/adesolabolu/tiktok-live-tts/releases) page:

1. Download **`TikTokLiveTTS-Setup.exe`**.
2. Double-click to install (no administrator rights required).
3. Launch **TikTok Live TTS Studio** directly from your Desktop or Start Menu.

---

## 🎧 How TikTok Live Studio Audio Routing Works

Because TikTok Live TTS Studio plays audio directly through your Windows audio subsystem:

1. **In TikTok Live Studio:** TikTok Live Studio captures your system / desktop audio by default. When the app speaks, your livestream audience hears it automatically.
2. **Dedicated Audio Device Output:** If you use virtual audio cables (Voicemeeter, Elgato Wave Link, GoXLR), go to the **Settings** tab in the app and select your specific playback channel from the **Audio Output Device** dropdown.
3. **Headphones Recommended:** Wear headphones while streaming so your physical microphone does not pick up TTS playback from room speakers.

---

## 🎬 How to Add the Transparent Subtitle Overlay to TikTok Live Studio

1. In the app, switch to the **🎬 TikTok Studio Overlay** tab.
2. Click **"📋 Copy Overlay URL"** (e.g., `http://127.0.0.1:28730/overlay`).
3. In **TikTok Live Studio**:
   - Click **Add Source** ➔ **Link / Browser**.
   - Paste the copied URL into the URL field.
   - Set Dimensions to **1920 × 1080**.
4. The transparent subtitles and gift alerts will now render on top of your stream video with zero background blockout!

---

## 🛠️ Tech Stack

* **Core Backend:** Python, FastAPI, Uvicorn, WebSockets
* **Livestream Connection:** [TikTokLive](https://github.com/isaackogan/TikTokLive) (Webcast WebSocket Client)
* **Desktop UI & Windowing:** [pywebview](https://pywebview.flowrl.com/) + WinForms WebView2 runtime
* **Installer Engine:** [Inno Setup 6](https://jrsoftware.org/isinfo.php)
* **Frontend:** Dark-mode Vanilla HTML5, CSS3, Modern ES6+ WebSockets

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
