"""Command line entry point.

    python -m app                 run the engineer
    python -m app --check         show setup status
    python -m app --devices       list audio devices
    python -m app --telemetry     print live telemetry only
    python -m app --ask "..."     ask one question and exit
    python -m app --test-tts      speak a test line
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from . import config as config_mod
from .telemetry import packets as p
from .telemetry.listener import TelemetryListener
from .telemetry.state import RaceState


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _print_telemetry(cfg: config_mod.Config, coverage: bool = False) -> int:
    state = RaceState()
    listener = TelemetryListener(
        state,
        host=cfg.get("telemetry.host", "0.0.0.0"),
        port=int(cfg.get("telemetry.port", 20777)),
    )
    listener.start()
    if listener.last_error:
        print(listener.last_error)
        return 1
    print(f"Listening on udp://{cfg.get('telemetry.host')}:{cfg.get('telemetry.port')}")
    print("Start a session in F1 24. Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1.0)
            s = state.snapshot()
            if not s["connected"]:
                print(f"  no packets ({listener.packets_per_second:.0f} pkt/s)"
                      + (f" - {state.format_error}" if state.format_error else ""))
                continue
            if coverage:
                report = listener.coverage_report()
                counts = " ".join(f"{name}={count}" for name, count in report["counts"].items())
                print(f"  {report['packets_per_second']} pkt/s | {counts}")
                if report["unknown_ids"]:
                    print(f"  UNKNOWN ids: {report['unknown_ids']}")
                if report["size_mismatches"]:
                    print(f"  SIZE MISMATCH: {report['size_mismatches']}")
                continue
            print(
                f"  {listener.packets_per_second:4.0f} pkt/s | "
                f"{s['track']:<16} lap {s['lap']:>2}/{s['total_laps']:<2} "
                f"P{s['position']:<2} {s['speed_kph']:>3} kph "
                f"fuel {s['fuel_kg']:>5.1f}kg "
                f"{s['tyre']['compound']:<12} {s['tyre']['age_laps']} laps "
                f"wear {max(s['tyre']['wear_pct'].values()):.0f}%"
            )
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    return 0


def _check(cfg: config_mod.Config) -> int:
    print("race-engineer-ai setup check\n")
    ok = True

    if p.LAYOUT_PROBLEMS:
        ok = False
        print("  [FAIL] packet layouts:", "; ".join(p.LAYOUT_PROBLEMS))
    else:
        print("  [ok]   F1 24 packet layouts verified")

    try:
        import sounddevice  # noqa: F401

        print("  [ok]   sounddevice")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  [FAIL] sounddevice: {exc}")

    try:
        from faster_whisper import WhisperModel  # noqa: F401

        print("  [ok]   faster-whisper")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  [FAIL] faster-whisper: {exc}")

    piper = cfg.resolve_path(cfg.get("tts.piper_exe"))
    voice = cfg.resolve_path(cfg.get("tts.voice_model"))
    if piper.exists() and voice.exists():
        print(f"  [ok]   piper voice ({voice.name})")
    else:
        ok = False
        print(f"  [FAIL] piper: exe={piper.exists()} voice={voice.exists()} (run setup.ps1)")

    llm_dir = config_mod.PROJECT_ROOT / "models" / "llm"
    parts = sorted(llm_dir.glob("qwen2.5-7b-instruct-q4_k_m*.gguf"))
    if parts:
        total_gb = sum(p.stat().st_size for p in parts) / (1024 ** 3)
        print(f"  [ok]   local model: {len(parts)} file(s), {total_gb:.1f} GB")
    else:
        print("  [warn] no local model in models/llm (run: setup.ps1 -Models)")

    server = config_mod.PROJECT_ROOT / "models" / "llama" / "llama-server.exe"
    if server.exists():
        print("  [ok]   llama-server.exe present")
    else:
        print("  [warn] llama-server.exe missing (run: setup.ps1 -Models)")

    from .brain.llm import LLMClient

    local = LLMClient("local", cfg.provider("local"))
    healthy, reason = local.health()
    if healthy:
        print(f"  [ok]   local model at {local.base_url}")
    else:
        print(f"  [warn] local model at {local.base_url}: {reason}")

    name = cfg.get("brain.smart_provider", "deepseek")
    smart_cfg = cfg.provider(name)
    if smart_cfg.get("api_key"):
        print(f"  [ok]   {name} API key present")
    else:
        print(f"  [warn] {name} API key missing (set {smart_cfg.get('api_key_env')})")

    try:
        from .voice.audio import list_devices

        print("\nAudio devices:\n" + list_devices())
    except Exception as exc:  # noqa: BLE001
        print(f"\n  [warn] cannot list audio devices: {exc}")

    print("\nAll good." if ok else "\nSome checks failed; see above.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="race-engineer-ai", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("--devices", action="store_true", help="list audio devices")
    parser.add_argument("--check", action="store_true", help="check models, key, audio")
    parser.add_argument("--telemetry", action="store_true", help="print telemetry only")
    parser.add_argument("--coverage", action="store_true",
                        help="print per-packet reception counts and any unknown packets")
    parser.add_argument("--test-tts", action="store_true", help="speak a test line")
    parser.add_argument("--ask", help="ask one question, print and speak the answer, then exit")
    parser.add_argument("--text-only", action="store_true", help="no mic, no speech output")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    cfg = config_mod.load_config(args.config)

    if args.devices:
        from .voice.audio import list_devices

        print(list_devices())
        return 0

    if args.check:
        return _check(cfg)

    if args.telemetry:
        return _print_telemetry(cfg)

    if args.coverage:
        return _print_telemetry(cfg, coverage=True)

    if args.test_tts:
        from .voice.audio import play, resolve_device
        from .voice.tts import PiperVoice

        voice = PiperVoice(
            cfg.resolve_path(cfg.get("tts.piper_exe")),
            cfg.resolve_path(cfg.get("tts.voice_model")),
            speed=float(cfg.get("tts.speed", 1.0)),
            radio_filter=bool(cfg.get("tts.radio_filter", True)),
        )
        samples, rate = voice.synthesize(
            "Radio check. Engineer is on the line. Box this lap, box box."
        )
        play(samples, rate, resolve_device(cfg.get("audio.output_device"), "output"))
        return 0

    from .engineer import RaceEngineer

    engineer = RaceEngineer(cfg, text_only=args.text_only)
    try:
        engineer.run(initial_question=args.ask)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        engineer.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
