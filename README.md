# race-engineer-ai

A voice race engineer for **EA SPORTS F1 24** on PC. Hold a key, ask a question,
and an engineer answers over team radio with your real telemetry in front of it.

- **Hears you** — tap-to-talk (F9 by default) + Whisper speech recognition, offline
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
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models   # ~5.7 GB download
#    -SkipModel = llama.cpp only, -SkipLlama = model only

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

Then **tap F9**, speak, and say **"over"** — it stops and answers. A pause also
sends, and typing a question and pressing Enter works without the mic.

Set `audio.ptt_mode: hold` in `config.yaml` if you prefer push-to-talk.

## Commands

| Command | What it does |
|---|---|
| `.\run.cmd` | Run the engineer (voice in, voice out) |
| `.\run.cmd --text-only` | Run without mic or speech output (type questions) |
| `.\run.cmd --ask "how's my fuel?"` | One question, then exit |
| `.\run.cmd --telemetry` | Print live telemetry, no voice — use this to confirm F1 24 is sending |
| `.\run.cmd --coverage` | Per-packet reception counts, unknown packet ids and size mismatches |
| `.\run.cmd --tyres` | Dump raw compound codes, wear, damage, temps and both corner orders |
| `.\run.cmd --overlay` | Run only the overlay window (the engineer launches it automatically) |
| `.\run-overlay.cmd` | Same as `--overlay`, detached with no console |
| `.\run.cmd --check` | Check packages, models, API key, audio devices |
| `.\run.cmd --devices` | List audio device names and indices |
| `.\run.cmd --test-tts` | Speak a test radio call |
| `python -m app.simulator --duration 120` | Fake telemetry so you can test without the game |

## Telemetry coverage

All 15 packet types in the F1 24 (2024 format) specification are decoded and
size-checked at import, and all 22 cars are tracked:

| Packet | Used for |
|---|---|
| Motion, Motion Ex | g-forces, suspension, ride heights |
| Session | track, weather, forecast, pit window, flags |
| Lap Data | position, laps, gaps, sectors, pit status — all cars |
| Event | overtakes, penalties, safety car, flags |
| Participants | driver names, teams, AI/human |
| Car Setups | wings, suspension, pressures, brake bias, fuel load |
| Car Telemetry | speed, gear, throttle, brake, DRS, temps — all cars |
| Car Status | fuel, ERS, compound, tyre age, fuel mix — all cars |
| Final Classification | results, points, race time, stints |
| Lobby Info | lobby players and ready state |
| Car Damage | tyre wear, damage, engine component wear — all cars |
| Session History | per-lap times, sector times, tyre stints |
| Tyre Sets | remaining sets, wear, expected life, lap delta |
| Time Trial | personal best and rival delta in time trial |

If the game ever sends an id or size the spec does not define, `--coverage`
reports it instead of dropping it silently.

## Overlay

The engineer starts an always-on-top panel automatically:

```
LAP 7/12    P4    +0.8
287 km/h   GEAR 7   DRS
FUEL 61.2 kg   +1.8 laps
MEDIUM 12 laps   wear 42%   life ~8
[wear bar]
ERS 62%   OVERTAKE   MIX STANDARD
[ERS bar]
GAP ▲ 0.8   BEHIND 0.9
1:22.4   1:22.1   1:22.6
PIT WINDOW  L5-7
GREEN
```

- **Drag** it anywhere with the left mouse button.
- **F10** shows and hides it.
- **Esc** closes it.
- It works over **borderless or windowed** F1 24. Exclusive fullscreen hides any
  overlay — switch the game to borderless.
- Tune position, size and transparency under `overlay:` in `config.yaml`.
- If it says "waiting for engineer data", `run.cmd` is not running.

## How it works

```
F1 24 ──UDP 20777──► telemetry parser ──► live race state
                                              │
F9 (tap) ──► mic ──► Whisper ──► question ───┤
                                              ▼
                                   engineer brain
                          local Qwen 7B  ◄──►  DeepSeek
                          + tools: fuel, tyres, gaps, pit window
                                              │
                                              ▼
                            Piper TTS ──► radio filter ──► headset
```

- **Telemetry** (`app/telemetry`) decodes all 15 packet types directly from the
  UDP socket and keeps full state for all 22 cars. Read-only, no memory access,
  no injection — the same approach as SimHub and MoTeC.
- **Tools** (`app/brain/tools.py`) answer fuel/tyre/gap questions from real
  numbers, so the model never invents a figure.
- **Routing**: factual questions (fuel, tyres, gaps, pit window, position, last
  lap) are answered directly from telemetry in under 0.1 s — no model, so the
  numbers cannot be wrong. Questions with "why / should / strategy / undercut…"
  or 12+ words go to DeepSeek, or to the local 7B model when no key is set. If
  the local model stalls past `first_token_deadline_s`, the engineer speaks a
  deterministic telemetry answer instead of leaving you in silence.
- **Speed**: measured on the reference machine — 0.0 s for factual answers,
  1–2 s for local model replies (compact telemetry brief, not the full JSON).
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

**Talking.** `audio.ptt_mode: tap` (default) records from one key press until you
say "over", pause for `end_on_silence_s`, or tap again. Set `hold` for classic
push-to-talk. `audio.over_words` changes the trigger words. If "over" is missed,
the silence fallback still sends the question.

**Strategy.** `strategy.pit_loss_s` is the time lost in the pit lane at this
track; it drives the rejoin position and undercut projections. `traffic_window_s`
controls how close a car must be to count as pit-exit traffic.

**Overlay.** `overlay.scale`, `overlay.opacity`, `overlay.x`, `overlay.y` and
`overlay.toggle_key`. Set `overlay.enabled: false` to skip it entirely.

**Audio routing.** Set `audio.input_device` / `audio.output_device` to a name
substring or index from `--devices`. Route the engineer to the headset and keep
game audio where you want it.

**Speech recognition.** `stt.model: small.en` is the sweet spot. `base.en` is
faster and lighter; `medium.en` is more accurate. STT defaults to CPU so it does
not compete with the game for VRAM.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "No Windows llama.cpp build found" | Fixed in the current `setup.ps1`: it scans llama.cpp's prerelease build tags, because the `latest` tag (`v1.0.0`) ships no binaries. If GitHub rate-limits the API, rerun later or use the Vulkan build manually |
| Model download 404 | The Qwen GGUF is published as two split files (`…-00001-of-00002.gguf`). Download both halves; llama.cpp joins them automatically and `start-llm.cmd` picks the first |
| "I have no telemetry" | `.\run.cmd --telemetry` while driving. Check UDP format is **2024**, IP `127.0.0.1`, port `20777`, and that Windows Firewall allows F1 24 |
| Everything is offline / no reply | Start `.\start-llm.cmd`; check `.\run.cmd --check` |
| Smart answers never happen | `DEEPSEEK_API_KEY` is missing or set after the terminal opened |
| "deepseek API key was rejected" | The key is invalid or expired — create a new one at platform.deepseek.com, `setx DEEPSEEK_API_KEY "..."`, reopen the terminal. The engineer falls back to the local model for that session |
| Mic never records | Windows Settings > Privacy > Microphone; check the default input in `--devices` |
| Doesn't stop on "over" | Say it clearly at the end of the sentence; if it still misses, the 1.2 s silence fallback sends anyway. Try `stt.spotter_model: base.en` |
| No voice output | `.\run.cmd --test-tts`; confirm `models/piper/piper.exe` and the `.onnx` exist |
| Whisper CUDA errors | Keep `stt.device: cpu` (default). CUDA needs cuBLAS and cuDNN 9 on PATH |
| Game stutters with the model running | `.\start-llm.cmd 16` or lower |
| Overlay not visible | F1 24 is in exclusive fullscreen — switch to borderless; or it is hidden, press **F10** |
| Overlay says "waiting for engineer data" | `run.cmd` is not running, or `overlay.enabled` is false |
| Compound looks wrong | Names now come from the visual compound. `.\run.cmd --tyres` prints the raw codes to confirm |
| Corners look swapped | `.\run.cmd --tyres` prints wear/temps in the spec order and the alternative order — compare with the in-game MFD |
| Replies too long / waffly | Lower `brain.providers.*.max_tokens`, or set `escalate_min_words` higher |

## Notes

- This is a third-party companion app. It only reads UDP telemetry, which EA
  documents for external apps. It does not touch game memory or modify the game.
- DeepSeek costs roughly one or two cents for a full race of heavy questioning.
- The local model, Whisper and Piper all run offline; only escalated questions
  use the network.
- Tests: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- Every field the engineer knows is documented in [DATA.md](DATA.md).
