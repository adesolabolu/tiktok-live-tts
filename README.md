# 🎙️ TikTok Live TTS Studio

A high-performance, standalone Text-to-Speech (TTS) studio engineered specifically for TikTok livestreamers. Connects to any TikTok livestream in real time using just a public `@username` and speaks chat comments, subscriber events, and gift alerts aloud with **zero audio latency** and **no passwords or API keys required**.

---

## ⚡ Key Highlights (v1.9.2)

* **🔇 Clean Message TTS & Anti-Glitch Audio Queue (v1.9.2 Fix):**
  * **Removed Fan Club Spoken Level Announcements:** Eliminates the glitch where the TTS blurted out "Congratulations for joining the fan club at level X!" before reading chat messages. Only clean comment text is spoken aloud.
  * **Sequential Audio Playback Queue:** New queue pipeline plays comments smoothly one after another with natural pacing, preventing rapid chat messages from clipping, cutting each other off, or stuttering.
* **🛡️ Enhanced Audience & Fan Club Permissions (v1.9.1):**
  * Fully adapted to TikTokLive v3 protobuf structures (`UserIdentity` and `BadgeStruct`).
  * **Followers Only:** Correctly recognizes room followers, moderators, anchors, and mutual followers via anchor identity flags and follow status.
  * **Subscribers Only:** Seamlessly detects active subscribers and super fans.
  * **Fan Club Members & Level Thresholds:** Reliably extracts active room Fan Club badges (`LV. 1` through `LV. 30+`) from real-time webcast badge data.
* **🚀 1-Click Windows Setup (`TikTokLiveTTS-Setup.exe`):** Single-file Inno Setup installer. Installs cleanly to your PC, creates Desktop & Start Menu shortcuts, and features seamless in-app auto-updating.
* **🎨 Broadcast Studio UI Redesign:** Sleek obsidian dark-mode interface built to professional hardware studio standards. Features Emil Kowalski motion curves, tactile `:active` button compressions (`scale(0.97)`), real-time animated audio VU meter equalizers, hardware-styled toggle switches, and categorized activity feeds.
* **⚡ Instant Zero-Lag Speech (<30ms):** 100% offline neural voice engine running locally on your computer with zero cloud latency or buffering.
* **🏪 13 High-Fidelity Offline Neural Voices:**
  * **Nova:** High-Energy Anime Female (Hype / Gaming)
  * **Kael:** Deep FM Radio Announcer (Deep / Radio)
  * **Arthur:** Distinguished British Butler (British / Formal)
  * **Viper:** Esports Shoutcaster (FPS / Gaming)
  * **Luna:** Calm & Cozy Storyteller (Cozy / ASMR)
  * **Thor:** Nordic Warrior (Fantasy / Epic)
  * **Danny:** Gamer / Teen Hype (US / Banter)
  * **Lessac:** Studio Narrator / Pro Audiobook (US / Studio Clear)
  * **Joe:** Chill Streamer / Casual Male (US / Conversational)
  * **Kristin:** Warm & Cheerful Female (US / Friendly)
  * **Mike:** Deep Baritone / Esports Caster (US / Deep Authority)
  * **Alba:** Scottish Storyteller (Scottish / Character)
  * **Cori:** British Queen's English (UK / Eloquent Royal)
* **⭐ Voice Store Features:**
  * **Authentic Streaming Previews:** Play / Pause sample audio before downloading.
  * **Live Animated Equalizer:** Active sound wave bars visualize playback in real time.
  * **Category Filter Pills & Live Search:** Instantly filter by Gaming, Deep, Chill, Warm, Accents, or search by name.
  * **⭐ Pin to Top:** Star favorite voices to pin them to the top of the store and your stream dropdown.
  * **1-Click Install & Uninstall:** Download models for 0ms CPU synthesis, or uninstall anytime to reclaim disk space.
* **🎬 TikTok Live Studio Overlay (`/overlay`):** Dedicated transparent browser overlay HUD for TikTok Live Studio with animated live chat subtitles, fan badges, and gift announcements.
* **🎛️ 4-Tab Streamer Dashboard:**
  * **🎙️ Live TTS & Moderation:** Streamer controls, live chat monitor, manual speech soundboard with 6 presets, anti-spam automute, fan club gating, and a dedicated **`▶️ Play Sample of Selected Voice`** button.
  * **🎬 TikTok Studio Overlay:** Custom subtitle display HUD, URL copy, and TikTok Live Studio setup guide.
  * **🏪 Voice Store (13 Voices):** Offline neural voice catalog with instant previews, filters, and star management.
  * **⚙️ Settings & Audio Routing:** Audio device routing (`navigator.mediaDevices`), volume control, and software updates.
* **🛡️ Streamer Moderation & Safety:**
  * **Command Prefix Filter:** Optionally require comments to begin with a trigger prefix (`.`, `/`, or `!`) before being spoken aloud, with automatic prefix stripping so only the message is read.
  * **Fan Club Level Gating:** Limit TTS to dedicated fans (e.g., Level 5+).
  * **Gifter Minimum Coins:** Limit gift announcements to gifts meeting coin thresholds.
  * **Anti-Spam Auto-Mute:** Automatically silences users who repeat comments or spam chat.
  * **Panic Button:** Instant "Skip Message" and "Clear Queue" controls.
* **🌐 Conflict-Free Port `28730`:** Runs on dedicated high-range port `28730` with an automatic scanner across ports 28730–28760 to guarantee zero collisions with local servers or dev tools.

---

## 📥 Installation

Download the official standalone installer from the [GitHub Releases](https://github.com/adesolabolu/tiktok-live-tts/releases) page:

> 🛡️ Free code signing provided by the [SignPath Foundation](https://signpath.org).

1. Download **`TikTokLiveTTS-Setup.exe`**.
2. Double-click to install (no administrator rights required).
3. Launch **TikTok Live TTS Studio** directly from your Desktop or Start Menu.

---

## 🎧 How TikTok Live Studio Audio Routing Works

Because TikTok Live TTS Studio plays audio directly through your Windows audio subsystem:

1. **In TikTok Live Studio:** TikTok Live Studio captures your system / desktop audio by default. When the app speaks, your livestream audience hears it automatically.
2. **Dedicated Audio Device Output:** If you use virtual audio cables (Voicemeeter, Elgato Wave Link, GoXLR, SteelSeries Sonar), go to the **Settings** tab in the app and select your specific playback channel from the **Audio Output Device** dropdown.
3. **Headphones Recommended:** Wear headphones while streaming so your physical microphone does not pick up TTS playback from room speakers.

---

## 🎬 How to Add the Transparent Subtitle Overlay to TikTok Live Studio

1. In the app, switch to the **🎬 TikTok Studio Overlay** tab.
2. Click **"📋 Copy Overlay URL"** (e.g., `http://127.0.0.1:28730/overlay`).
3. In **TikTok Live Studio**:
   - Click **Add Source** ➔ **Link / Browser Source**.
   - Paste the copied URL into the URL field.
   - Set Dimensions to **Width: 850**, **Height: 250**.
4. The transparent subtitles and gift alerts will now render on top of your stream video with zero background blockout!

---

## 🛠️ Tech Stack

* **Core Backend:** Python, FastAPI, Uvicorn, WebSockets
* **Local Neural Speech:** Piper TTS (0ms local ONNX inference)
* **Livestream Connection:** [TikTokLive](https://github.com/isaackogan/TikTokLive) (Webcast WebSocket Client)
* **Desktop UI & Windowing:** [pywebview](https://pywebview.flowrl.com/) + WinForms WebView2 runtime
* **Installer Engine:** [Inno Setup 6](https://jrsoftware.org/isinfo.php)
* **Frontend:** Modern Obsidian Dark UI, Hardware Switch Controls, ES6+ WebSockets, CSS3 Motion Curves

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

---

## 🛡️ Code Signing

Free code signing is provided by the [SignPath Foundation](https://signpath.org) to ensure safe, verified, and tamper-proof Windows releases.
