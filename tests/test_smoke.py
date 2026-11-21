r"""Smoke tests: no game, no models, no microphone required.

Run:  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
"""

import ctypes
import unittest

from app import simulator
from app.brain import tools
from app.telemetry import packets as p
from app.telemetry.state import RaceState


class LayoutTests(unittest.TestCase):
    def test_packet_sizes(self):
        self.assertEqual(p.LAYOUT_PROBLEMS, [])

    def test_header_is_29_bytes(self):
        self.assertEqual(ctypes.sizeof(p.PacketHeader), 29)


class ParseTests(unittest.TestCase):
    def test_session_packet_roundtrip(self):
        data = simulator._session_packet(1, 2.0)
        self.assertEqual(len(data), 753)
        packet_id, packet, header = p.parse_packet(data)
        self.assertEqual(packet_id, p.SESSION)
        self.assertEqual(header.packet_format, 2024)
        self.assertEqual(packet.data.track_id, 10)
        self.assertEqual(packet.data.total_laps, 12)
        self.assertEqual(packet.data.pit_stop_window_ideal_lap, 5)

    def test_truncated_packet_is_ignored(self):
        data = simulator._session_packet(1, 2.0)[:100]
        packet_id, packet, header = p.parse_packet(data)
        self.assertEqual(packet_id, p.SESSION)
        self.assertIsNone(packet)

    def test_short_datagram(self):
        self.assertIsNone(p.parse_packet(b"\x00\x01"))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = RaceState()
        self.state.apply(p.SESSION, p.parse_packet(simulator._session_packet(0, 0))[1],
                         p.parse_packet(simulator._session_packet(0, 0))[2])
        self._lap(1, 0)
        self._status(70.0)

    def _lap(self, lap, last_ms):
        data = simulator._lap_packet(0, 0, lap, 0.5)
        pid, packet, header = p.parse_packet(data)
        packet.lap_data[0].last_lap_time_in_ms = last_ms
        self.state.apply(pid, packet, header)

    def _status(self, fuel):
        pid, packet, header = p.parse_packet(simulator._status_packet(0, 0, fuel, 10, 17, 1))
        self.state.apply(pid, packet, header)

    def test_session_fields(self):
        snap = self.state.snapshot()
        self.assertEqual(snap["track"], "Monza")
        self.assertEqual(snap["total_laps"], 12)
        self.assertEqual(snap["session"], "race")

    def test_fuel_per_lap_from_lap_delta(self):
        # 70 kg at the start of lap 1, 67.4 kg at the start of lap 2
        self._status(67.4)
        self._lap(2, 82400)
        self._status(64.8)
        self._lap(3, 83000)
        self.assertAlmostEqual(self.state.fuel_per_lap_kg, 2.6, places=1)
        self.assertIsNotNone(self.state.fuel_surplus_laps())

    def test_quick_answers_use_telemetry(self):
        self.assertIn("Fuel in tank", tools.quick_answer("how's my fuel?", self.state))
        self.assertIn("tyres", tools.quick_answer("how are my tyres?", self.state).lower())
        self.assertIn("Lap", tools.quick_answer("where am I?", self.state))


if __name__ == "__main__":
    unittest.main()
