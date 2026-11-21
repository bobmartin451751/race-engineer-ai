"""UDP listener for F1 24 telemetry."""

from __future__ import annotations

import errno
import logging
import socket
import threading
import time

from . import packets as p
from .state import RaceState

log = logging.getLogger(__name__)


class TelemetryListener:
    def __init__(
        self,
        state: RaceState,
        host: str = "0.0.0.0",
        port: int = 20777,
        on_packet=None,
    ) -> None:
        self.state = state
        self.host = host
        self.port = port
        self.on_packet = on_packet
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.packets_per_second = 0.0
        self.last_error: str | None = None
        self.packet_counts: dict[int, int] = {}
        self.unknown_ids: dict[int, tuple[int, int]] = {}
        self.size_mismatches: dict[int, int] = {}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def coverage_report(self) -> dict:
        counts = {
            p.PACKET_NAMES.get(k, str(k)): v for k, v in sorted(self.packet_counts.items())
        }
        return {
            "counts": counts,
            "unknown_ids": dict(self.unknown_ids),
            "size_mismatches": {
                p.PACKET_NAMES.get(k, str(k)): v for k, v in self.size_mismatches.items()
            },
            "packets_per_second": round(self.packets_per_second, 1),
        }

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
        except OSError as exc:
            self.last_error = f"cannot bind UDP {self.host}:{self.port}: {exc}"
            log.error(self.last_error)
            return
        sock.settimeout(0.5)
        log.info("listening for F1 24 telemetry on udp://%s:%s", self.host, self.port)

        window_start = time.time()
        window_count = 0
        bad_sizes: set[int] = set()

        while not self._stop.is_set():
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                if exc.errno in (errno.EWOULDBLOCK, errno.EINTR):
                    continue
                self.last_error = str(exc)
                log.warning("udp recv failed: %s", exc)
                continue

            parsed = p.parse_packet(data)
            if parsed is None:
                continue
            packet_id, packet, header = parsed
            if packet is None and header.packet_id in p.EXPECTED_SIZES:
                self.size_mismatches[header.packet_id] = len(data)
                if len(data) not in bad_sizes:
                    bad_sizes.add(len(data))
                    log.warning(
                        "packet %s had unexpected size %s (expected %s); "
                        "check the in-game UDP format is 2024",
                        p.PACKET_NAMES.get(packet_id, packet_id),
                        len(data),
                        p.EXPECTED_SIZES[header.packet_id],
                    )
            if packet_id not in p.PACKET_CLASSES:
                count, _ = self.unknown_ids.get(packet_id, (0, 0))
                self.unknown_ids[packet_id] = (count + 1, len(data))
                if count == 0:
                    log.warning(
                        "unrecognised packet id %s (%s bytes) - not in the 2024 spec",
                        packet_id,
                        len(data),
                    )
            else:
                self.packet_counts[packet_id] = self.packet_counts.get(packet_id, 0) + 1
            self.state.apply(packet_id, packet, header)
            window_count += 1
            if self.on_packet:
                try:
                    self.on_packet(packet_id, packet, header)
                except Exception:  # noqa: BLE001 - callback must never kill the listener
                    log.exception("telemetry callback failed")

            now = time.time()
            if now - window_start >= 1.0:
                self.packets_per_second = window_count / (now - window_start)
                window_start, window_count = now, 0

        sock.close()
