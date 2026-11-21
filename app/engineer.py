"""Top-level orchestrator: telemetry + push-to-talk + LLM + voice."""

from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from . import config as config_mod
from .brain import prompts, tools
from .brain.llm import LLMClient, LLMError, tidy_reply
from .proactive import ProactiveEngine
from .telemetry import packets as p
from .telemetry.listener import TelemetryListener
from .telemetry.state import RaceState
from .voice import audio
from .voice.ptt import PushToTalk
from .voice.stt import Transcriber
from .voice.tts import PiperVoice

log = logging.getLogger(__name__)

ACKS = ["Copy, checking.", "Stand by.", "Understood, one moment.", "Working on it."]


class RaceEngineer:
    def __init__(self, cfg: config_mod.Config, text_only: bool = False) -> None:
        self.cfg = cfg
        self.text_only = text_only
        self.state = RaceState()

        self.listener = TelemetryListener(
            self.state,
            host=cfg.get("telemetry.host", "0.0.0.0"),
            port=int(cfg.get("telemetry.port", 20777)),
        )

        self.recorder = audio.Recorder(
            device=audio.resolve_device(cfg.get("audio.input_device"), "input"),
            sample_rate=int(cfg.get("audio.sample_rate", 16000)),
        )
        self.output_device = audio.resolve_device(cfg.get("audio.output_device"), "output")
        self.max_record_s = float(cfg.get("audio.record_max_seconds", 25))

        self.stt = Transcriber(
            model=cfg.get("stt.model", "small.en"),
            device=cfg.get("stt.device", "cpu"),
            compute_type=cfg.get("stt.compute_type", "int8"),
            language=cfg.get("stt.language", "en"),
            beam_size=int(cfg.get("stt.beam_size", 1)),
        )
        self.voice = PiperVoice(
            piper_exe=cfg.resolve_path(cfg.get("tts.piper_exe")),
            voice_model=cfg.resolve_path(cfg.get("tts.voice_model")),
            speed=float(cfg.get("tts.speed", 1.0)),
            volume=float(cfg.get("tts.volume", 1.0)),
            radio_filter=bool(cfg.get("tts.radio_filter", True)),
        )

        self.local = LLMClient("local", cfg.provider("local"))
        self.smart = None
        try:
            smart_cfg = cfg.provider(cfg.get("brain.smart_provider", "deepseek"))
            if smart_cfg.get("api_key"):
                self.smart = LLMClient(cfg.get("brain.smart_provider", "deepseek"), smart_cfg)
        except KeyError:
            pass

        self.proactive = ProactiveEngine(
            self.state,
            cooldown_s=float(cfg.get("engineer.cooldown_s", 20)),
            enabled=bool(cfg.get("engineer.proactive", True)),
        )

        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="engineer")
        self._capture_lock = threading.Lock()
        self._speak_lock = threading.Lock()
        self._speaking = threading.Event()
        self._running = threading.Event()
        self._ptt_timer: threading.Timer | None = None
        self._threads: list[threading.Thread] = []
        self._last_connected: bool | None = None

    # ------------------------------------------------------------------
    def start(self) -> None:
        if p.LAYOUT_PROBLEMS:
            log.warning("packet layout warnings: %s", "; ".join(p.LAYOUT_PROBLEMS))

        ok, reason = self.voice.available()
        if not ok:
            log.warning("voice output unavailable: %s (run setup.ps1)", reason)

        self.listener.start()
        if self.listener.last_error:
            raise RuntimeError(self.listener.last_error)

        local_ok, local_reason = self.local.health()
        if not local_ok:
            log.warning("local model unavailable (%s); will use %s when possible",
                        local_reason, "DeepSeek" if self.smart else "deterministic replies")
        if self.smart:
            log.info("smart provider ready: %s (%s)",
                     self.smart.name, "key present" if self.smart.api_key else "no key")
        else:
            log.warning("no API key for %s; smart questions will fall back to local",
                        self.cfg.get("brain.smart_provider", "deepseek"))

        self._running.set()
        if not self.text_only:
            self._ptt = PushToTalk(
                key=str(self.cfg.get("audio.ptt_key", "f9")),
                on_start=self.on_ptt_start,
                on_stop=self.on_ptt_stop,
            )
            self._ptt.start()

        self._spawn(self._proactive_loop, "proactive")
        self._spawn(self._warm_up, "warmup")

    def _spawn(self, target, name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _warm_up(self) -> None:
        try:
            started = time.time()
            self.stt.warm_up()
            log.info("speech recognition ready in %.1fs", time.time() - started)
        except Exception as exc:  # noqa: BLE001
            log.error("speech recognition failed to load: %s", exc)

    # ------------------------------------------------------------------
    def on_ptt_start(self) -> None:
        with self._capture_lock:
            if self._speaking.is_set():
                audio.stop_playback()
            if self.recorder.recording:
                return
            try:
                self.recorder.start()
            except Exception as exc:  # noqa: BLE001
                log.error("cannot start recording: %s", exc)
                return
        print("  [listening...]", flush=True)
        self._ptt_timer = threading.Timer(self.max_record_s, self.on_ptt_stop)
        self._ptt_timer.daemon = True
        self._ptt_timer.start()

    def on_ptt_stop(self) -> None:
        with self._capture_lock:
            if self._ptt_timer is not None:
                self._ptt_timer.cancel()
                self._ptt_timer = None
            if not self.recorder.recording:
                return
            samples = self.recorder.stop()
        duration = samples.size / float(self.recorder.sample_rate)
        print(f"  [captured {duration:.1f}s]", flush=True)
        if duration < 0.3:
            print("  (too short, ignored)", flush=True)
            return
        self._executor.submit(self._handle_audio, samples)

    def _handle_audio(self, samples) -> None:
        try:
            text = self.stt.transcribe(samples, self.recorder.sample_rate)
        except Exception as exc:  # noqa: BLE001
            log.error("transcription failed: %s", exc)
            return
        if not text:
            print("  (nothing recognised)", flush=True)
            return
        print(f"You: {text}", flush=True)
        self.respond(text)

    # ------------------------------------------------------------------
    def respond(self, question: str) -> str:
        started = time.time()
        reply = self._think(question)
        reply = tidy_reply(reply) if reply else ""
        if not reply:
            reply = "I didn't get that. Say again."
        self.speak(reply)
        log.info("reply in %.1fs: %s", time.time() - started, reply)
        return reply

    def _think(self, question: str) -> str:
        if not self.state.connected:
            return (
                "I have no telemetry. Check the game's UDP telemetry settings: "
                "port two zero seven seven seven, format twenty twenty four."
            )

        client, escalate = self._pick_client(question)
        messages = prompts.build_messages(self.state, question)
        runner = lambda name, args: tools.execute_tool(name, args, self.state)  # noqa: E731

        if escalate and self.smart is not None:
            self.speak(random.choice(ACKS))
            try:
                reply = self.smart.chat(messages, tools.TOOL_SCHEMAS, runner)
                return self._ensure_answer(reply.text, question)
            except LLMError as exc:
                log.warning("smart provider failed: %s", exc)

        if client is not None:
            deadline = float(
                self.cfg.get(f"brain.providers.{client.name}.first_token_deadline_s", 8.0)
                if client.name == "local"
                else client.timeout_s + 2
            )
            future = self._executor.submit(client.chat, messages, tools.TOOL_SCHEMAS, runner)
            try:
                reply = future.result(timeout=deadline)
                return self._ensure_answer(reply.text, question)
            except FutureTimeout:
                log.warning("%s exceeded %.1fs; using deterministic answer", client.name, deadline)
            except LLMError as exc:
                log.warning("%s failed: %s", client.name, exc)

        fallback = tools.quick_answer(question, self.state)
        if fallback:
            return fallback
        return "I can't reach the model and that one isn't in my telemetry. Ask again in a moment."

    def _pick_client(self, question: str) -> tuple[LLMClient | None, bool]:
        lowered = question.lower()
        words = len(question.split())
        keywords = [str(k).lower() for k in self.cfg.get("brain.escalate_when", [])]
        complex_question = (
            words >= int(self.cfg.get("brain.escalate_min_words", 12))
            or any(k in lowered for k in keywords)
        )
        if complex_question and self.smart is not None:
            return self.smart, True
        if self.local.health()[0]:
            return self.local, False
        if self.smart is not None:
            return self.smart, True
        return None, False

    @staticmethod
    def _ensure_answer(text: str, question: str) -> str:
        text = (text or "").strip()
        if text:
            return text
        return ""

    # ------------------------------------------------------------------
    def speak(self, text: str) -> None:
        if not text:
            return
        if self.text_only:
            print(f"Engineer: {text}", flush=True)
            return
        ok, reason = self.voice.available()
        if not ok:
            print(f"Engineer (text only): {text}", flush=True)
            log.warning("cannot speak: %s", reason)
            return
        with self._speak_lock:
            self._speaking.set()
            try:
                samples, rate = self.voice.synthesize(text)
                audio.play(samples, rate, self.output_device)
            except Exception as exc:  # noqa: BLE001
                print(f"Engineer (text only): {text}", flush=True)
                log.error("speech playback failed: %s", exc)
            finally:
                self._speaking.clear()

    # ------------------------------------------------------------------
    def _proactive_loop(self) -> None:
        while self._running.is_set():
            time.sleep(1.0)
            snapshot = self.state.snapshot()
            if snapshot["connected"] != self._last_connected:
                self._last_connected = snapshot["connected"]
                if snapshot["connected"]:
                    print(
                        f"  [telemetry connected] {snapshot['track']}, "
                        f"lap {snapshot['lap']}",
                        flush=True,
                    )
                else:
                    print("  [telemetry lost - check F1 24 UDP settings]", flush=True)
            if self.recorder.recording or self._speaking.is_set():
                continue
            message = self.proactive.poll()
            if message:
                print(f"Engineer (proactive): {message}", flush=True)
                self.speak(message)

    # ------------------------------------------------------------------
    def run(self, initial_question: str | None = None) -> None:
        self.start()
        print()
        print("Race engineer online.")
        print("  hold %s and speak" % str(self.cfg.get("audio.ptt_key", "f9")).upper())
        print("  type a question and press Enter to ask by text")
        print("  'status' for a snapshot, 'q' to quit")
        print()
        if initial_question:
            deadline = time.time() + 3.0
            while time.time() < deadline and not self.state.connected:
                time.sleep(0.1)
            self.respond(initial_question)
            self.shutdown()
            return
        try:
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                text = line.strip()
                if text.lower() in ("q", "quit", "exit"):
                    break
                if text.lower() == "status":
                    import json

                    print(json.dumps(self.state.snapshot(), indent=2, default=str))
                    continue
                if not text:
                    continue
                print("You:", text, flush=True)
                self.respond(text)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._running.clear()
        try:
            audio.stop_playback()
        except Exception:  # noqa: BLE001
            pass
        self.listener.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
        print("Engineer offline.")
