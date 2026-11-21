r"""Smoke tests: no game, no models, no microphone required.

Run:  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
"""

import ctypes
import unittest

import numpy as np

from app import simulator
from app.brain import tools
from app.telemetry import packets as p
from app.telemetry.state import RaceState
from app.voice import endpoint


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

    def test_every_packet_type_roundtrips(self):
        builders = [
            simulator._session_packet(0, 0),
            simulator._lap_packet(0, 0, 1, 0.5),
            simulator._telemetry_packet(0, 0, 0.5),
            simulator._status_packet(0, 0, 70, 10, 17, 1, None, 1),
            simulator._damage_packet(0, 0, 10),
            simulator._setup_packet(0, 0),
            simulator._participants(0, 0),
            simulator._session_history_packet(0, 0, 0, 3),
            simulator._tyre_sets_packet(0, 0, 0),
            simulator._motion_packet(0, 0, 0.5),
            simulator._motion_ex_packet(0, 0, 0.5),
            simulator._final_classification_packet(0, 0),
            simulator._lobby_packet(0, 0),
            simulator._event_packet(0, 0, "OVTK"),
        ]
        for data in builders:
            pid, packet, header = p.parse_packet(data)
            self.assertIsNotNone(packet, f"packet {pid} failed to parse")
            self.assertEqual(len(data), p.EXPECTED_SIZES[pid])

    def test_all_cars_tracked(self):
        state = RaceState()
        for data in (
            simulator._session_packet(0, 0),
            simulator._participants(0, 0),
            simulator._lap_packet(0, 0, 3, 0.5),
            simulator._status_packet(0, 0, 70, 12, 17, 2, 4, 3),
        ):
            pid, packet, header = p.parse_packet(data)
            state.apply(pid, packet, header)
        grid = state.grid()
        self.assertEqual(len(grid), 22)
        self.assertEqual(grid[0]["pos"], 1)
        self.assertEqual(grid[0]["driver"], "Leclerc")
        self.assertEqual(grid[3]["pos"], 4)
        self.assertEqual(grid[3]["driver"], "You")
        self.assertTrue(all(row["tyre"] for row in grid))
        rival = state.rival(3)
        self.assertIsNotNone(rival)
        self.assertEqual(rival.name, "Hamilton")
        rival = state.rival("verstappen")
        self.assertEqual(rival.position, 2)


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
        pid, packet, header = p.parse_packet(
            simulator._status_packet(0, 0, fuel, 10, 17, 1, 4, 1)
        )
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
        self.assertIn("kilograms of fuel", tools.quick_answer("how's my fuel?", self.state))
        self.assertIn("mediums", tools.quick_answer("how are my tyres?", self.state).lower())
        self.assertIn("Lap", tools.quick_answer("where am I?", self.state))
        self.assertIn("Pit window", tools.quick_answer("should I box?", self.state))


class EndpointTests(unittest.TestCase):
    def test_detects_over_at_the_end(self):
        for text in (
            "what's my fuel over",
            "how are the tyres, over.",
            "box this lap. Over and out!",
            "over",
        ):
            self.assertTrue(endpoint.ends_with_over(text), text)

    def test_ignores_over_inside_words(self):
        for text in (
            "the car is oversteering",
            "what about the overcut",
            "switch over to hards",
            "which tyre is faster",
            "",
        ):
            self.assertFalse(endpoint.ends_with_over(text), text)

    def test_strips_trigger(self):
        self.assertEqual(endpoint.strip_over("what's my fuel over"), "what's my fuel")
        self.assertEqual(
            endpoint.strip_over("How are the tyres, over and out."), "How are the tyres"
        )
        self.assertEqual(endpoint.strip_over("over"), "")

    def test_custom_trigger_words(self):
        words = ["roger"]
        self.assertTrue(endpoint.ends_with_over("box this lap roger", words))
        self.assertFalse(endpoint.ends_with_over("box this lap over", words))

    def test_silence_tracker_needs_speech_first(self):
        tracker = endpoint.SilenceTracker(sample_rate=16000, silence_s=0.5)
        self.assertFalse(tracker.update(np.zeros(16000, dtype=np.float32)))

    def test_silence_tracker_fires_after_speech(self):
        tracker = endpoint.SilenceTracker(sample_rate=16000, silence_s=0.5)
        speech = np.full(16000, 0.1, dtype=np.float32)
        self.assertFalse(tracker.update(speech))
        self.assertTrue(tracker.update(np.zeros(8000, dtype=np.float32)))

    def test_short_noise_does_not_fire(self):
        tracker = endpoint.SilenceTracker(sample_rate=16000, silence_s=0.5)
        self.assertFalse(tracker.update(np.full(1600, 0.1, dtype=np.float32)))
        self.assertFalse(tracker.update(np.zeros(16000, dtype=np.float32)))


class AdvancedDataTests(unittest.TestCase):
    def _state(self):
        state = RaceState()
        packets = [
            simulator._session_packet(0, 0),
            simulator._participants(0, 0),
            simulator._lap_packet(0, 0, 3, 0.5),
            simulator._status_packet(0, 0, 70, 12, 17, 2, 4, 3),
        ]
        for data in packets:
            pid, packet, header = p.parse_packet(data)
            state.apply(pid, packet, header)
        return state

    def test_pace_summary(self):
        state = self._state()
        state.player.session_laps = [
            {"lap": 1, "time_s": 82.4, "s1_s": 27.1, "s2_s": 28.2, "s3_s": 27.1, "valid": True},
            {"lap": 2, "time_s": 82.1, "s1_s": 26.9, "s2_s": 28.0, "s3_s": 27.2, "valid": True},
            {"lap": 3, "time_s": 82.3, "s1_s": 27.0, "s2_s": 28.1, "s3_s": 27.2, "valid": True},
        ]
        pace = state.pace_summary()
        self.assertAlmostEqual(pace["best_lap_s"], 82.1)
        self.assertAlmostEqual(pace["delta_to_best_s"], 0.2)
        self.assertAlmostEqual(pace["sector_deltas_s"]["s1"], 0.1)
        self.assertAlmostEqual(pace["rolling_pace_3_s"], 82.2667, places=3)
        self.assertIn("best_sectors_s", pace)

    def test_pit_projection(self):
        state = self._state()
        projection = state.pit_projection(pit_loss_s=21.0)
        self.assertGreaterEqual(projection["projected_rejoin_position"], 1)
        self.assertEqual(projection["pit_loss_s"], 21.0)
        self.assertIn("undercut_margin_s", projection)

    def test_car_systems(self):
        state = self._state()
        systems = state.systems()
        self.assertIn("ers_pct", systems)
        self.assertEqual(systems["fuel_mix"], "standard")
        self.assertIn("engine_temp_c", systems)

    def test_tools_use_new_data(self):
        state = self._state()
        state.player.session_laps = [
            {"lap": 1, "time_s": 82.4, "s1_s": 27.1, "s2_s": 28.2, "s3_s": 27.1, "valid": True},
            {"lap": 2, "time_s": 82.1, "s1_s": 26.9, "s2_s": 28.0, "s3_s": 27.2, "valid": True},
        ]
        self.assertIn("Best lap", tools.pace_report(state))
        self.assertIn("ERS", tools.systems_report(state))
        self.assertIn("Pit loss", tools.strategy_report(state))
        self.assertIn("Best lap", tools.quick_answer("how is my pace?", state))


if __name__ == "__main__":
    unittest.main()
