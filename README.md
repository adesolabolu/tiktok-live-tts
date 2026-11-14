# 🎙️ TikTok Live TTS Studio

A fast, lightweight, standalone Text-to-Speech (TTS) studio for TikTok livestreams. Connects to any live room in real time using just a public `@username` and speaks comments & gifts aloud with **zero audio setup** and **no passwords or API keys required**.

---

## ⚡ Features

* **⚡ Instant Native Mode (<50ms):** Zero-lag speech synthesized directly through your computer's built-in speech engine.
* **☁️ Cloud Neural Mode (HD):** High-fidelity AI neural voices (Ava, Christopher, Sonia, Andrew, Brian, Emma) via Edge-TTS.
* **🔒 Zero Credentials / Zero Login:** No TikTok password, session token, or official developer registration required. Connects to the public Webcast stream.
* **🎧 Zero Audio Configuration:** Plays through standard desktop audio. Automatically picked up by TikTok LIVE Studio, OBS Studio, and Streamlabs.
* **🛡️ Anti-Troll & Safety Guardrails:**
  * Per-user cooldown timer.
  * Maximum character limits per message.
  * Customizable banned-words regex/keyword filter.
  * Instant **"Skip Message"** panic button.
* **🔄 Auto-Update Notification:** Automatically alerts you inside the app when a new release is available on GitHub.

---

## 🚀 Getting Started

### Option 1: Run from Source

1. **Clone the repository:**
   ```bash
   git clone https://github.com/adesolabolu/tiktok-live-tts.git
   cd tiktok-live-tts
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Launch the studio:**
   ```bash
   python app.py
   ```
   Open your browser to `http://127.0.0.1:8080`.

---

### Option 2: Standalone Windows Executable (.exe)

Download the latest pre-compiled build from the [GitHub Releases](https://github.com/adesolabolu/tiktok-live-tts/releases) tab. Extract the `.zip` and double-click `TikTokLiveTTS.exe`.

---

## 🎛️ How Stream Audio Routing Works

Because the app outputs audio through your system's default playback device:

1. **In TikTok LIVE Studio / OBS:** Desktop Audio will capture the speech automatically.
2. **Headphone Recommendation:** Wear headphones so your physical microphone does not pick up the TTS from your room speakers.

---

## 🛠️ Tech Stack

* **Backend:** Python, FastAPI, Uvicorn, WebSockets
* **Livestream Connection:** [TikTokLive](https://github.com/isaackogan/TikTokLive) (Webcast WebSocket Client)
* **Speech Synthesis:** Web Speech API (Instant Native) + [edge-tts](https://github.com/rany2/edge-tts) (Cloud Neural)
* **Frontend:** Modern Vanilla HTML5 / CSS3 / JavaScript

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
