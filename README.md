# race-engineer-ai

A voice race engineer for **EA SPORTS F1 24** on PC. Hold a key, ask a question,
and an engineer answers over team radio with your real telemetry in front of it.

- **Hears you** — push-to-talk (F9 by default) + Whisper speech recognition, offline
- **Knows the race** — reads F1 24 UDP telemetry: fuel, tyres, gaps, flags, weather, pit window
- **Thinks** — local Qwen2.5-7B for instant replies, DeepSeek for real strategy questions
- **Talks** — Piper voice through a radio filter, straight into your headset
- **Speaks up** — proactive calls on tyre wear, fuel shortfall, pit window, safety car, rain

## Requirements

- Windows 10/11, Python 3.11+
- F1 24 on PC (consoles cannot send telemetry to a local app)
- A headset with a microphone
- NVIDIA GPU with ~3 GB free VRAM for the 7B model (a CPU-only setup still works, slower)
- A DeepSeek API key for the smart brain (optional; the app runs local-only without it)

## Quick start

```powershell
# 1. Install Python deps, Piper voice, and (with -Models) llama.cpp + the 7B model
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models   # ~5 GB download

# 2. DeepSeek key for smart answers
setx DEEPSEEK_API_KEY "sk-your-key"
#    (open a new terminal afterwards so the variable is visible)

# 3. Verify everything
.\run.cmd --check
.\run.cmd --devices

# 4. In F1 24: Options > Settings > Telemetry Settings
#    UDP Telemetry: On
#    UDP Broadcast Mode: Off
#    UDP IP Address: 127.0.0.1
#    UDP Port: 20777
#    UDP Send Rate: 60Hz
#    UDP Format: 2024

# 5. Start the local model, leave it running
.\start-llm.cmd

# 6. Start the engineer
.\run.cmd
```

Then hold **F9**, speak, release. Typing a question and pressing Enter does the
same thing without the mic.

## Commands

| Command | What it does |
|---|---|
| `.\run.cmd` | Run the engineer (voice in, voice out) |
| `.\run.cmd --text-only` | Run without mic or speech output (type questions) |
| `.\run.cmd --ask "how's my fuel?"` | One question, then exit |
| `.\run.cmd --telemetry` | Print live telemetry, no voice — use this to confirm F1 24 is sending |
| `.\run.cmd --check` | Check packages, models, API key, audio devices |
| `.\run.cmd --devices` | List audio device names and indices |
| `.\run.cmd --test-tts` | Speak a test radio call |
| `python -m app.simulator --duration 120` | Fake telemetry so you can test without the game |

## How it works

```
F1 24 ──UDP 20777──► telemetry parser ──► live race state
                                              │
F9 (hold) ──► mic ──► Whisper ──► question ───┤
                                              ▼
                                   engineer brain
                          local Qwen 7B  ◄──►  DeepSeek
                          + tools: fuel, tyres, gaps, pit window
                                              │
                                              ▼
                            Piper TTS ──► radio filter ──► headset
```

- **Telemetry** (`app/telemetry`) decodes the 2024 packet format directly from the
  UDP socket. Read-only, no memory access, no injection — the same approach as
  SimHub and MoTeC.
- **Tools** (`app/brain/tools.py`) answer fuel/tyre/gap questions from real
  numbers, so the model never invents a figure.
- **Routing**: short factual questions go to the local 7B model; questions with
  "why / should / strategy / undercut..." or 12+ words go to DeepSeek. If the
  local model stalls past `first_token_deadline_s`, the engineer speaks a
  deterministic telemetry answer instead of leaving you in silence.
- **Proactive rules** (`app/proactive.py`) run independently of questions and
  respect a cooldown so they never talk over you.

## Tuning

**VRAM / FPS.** F1 24 and a 7B model share the GPU. `start-llm.cmd` offloads 24
layers by default; if the game stutters, run `.\start-llm.cmd 16`; if you have
headroom, `.\start-llm.cmd 32`. `--ngl 0` runs the model on CPU.

**Voice.** Pick another Piper voice from
[rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) and point
`tts.voice_model` at it. `tts.radio_filter: false` gives clean studio audio.

**Keybind.** `audio.ptt_key` accepts `f1`…`f12`, `space`, `caps_lock`, `ctrl`,
`alt`, `shift`, `insert`, `delete`, `home`, `end`, `pause`, letters and digits.
Map a wheel button to that key in your wheel software.

**Audio routing.** Set `audio.input_device` / `audio.output_device` to a name
substring or index from `--devices`. Route the engineer to the headset and keep
game audio where you want it.

**Speech recognition.** `stt.model: small.en` is the sweet spot. `base.en` is
faster and lighter; `medium.en` is more accurate. STT defaults to CPU so it does
not compete with the game for VRAM.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "I have no telemetry" | `.\run.cmd --telemetry` while driving. Check UDP format is **2024**, IP `127.0.0.1`, port `20777`, and that Windows Firewall allows F1 24 |
| Everything is offline / no reply | Start `.\start-llm.cmd`; check `.\run.cmd --check` |
| Smart answers never happen | `DEEPSEEK_API_KEY` is missing or set after the terminal opened |
| Mic never records | Windows Settings > Privacy > Microphone; check the default input in `--devices` |
| No voice output | `.\run.cmd --test-tts`; confirm `models/piper/piper.exe` and the `.onnx` exist |
| Whisper CUDA errors | Keep `stt.device: cpu` (default). CUDA needs cuBLAS and cuDNN 9 on PATH |
| Game stutters with the model running | `.\start-llm.cmd 16` or lower |
| Replies too long / waffly | Lower `brain.providers.*.max_tokens`, or set `escalate_min_words` higher |

## Notes

- This is a third-party companion app. It only reads UDP telemetry, which EA
  documents for external apps. It does not touch game memory or modify the game.
- DeepSeek costs roughly one or two cents for a full race of heavy questioning.
- The local model, Whisper and Piper all run offline; only escalated questions
  use the network.
