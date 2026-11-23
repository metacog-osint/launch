"""Feed contract revision 2.1: subjects, event times, change flags and the anomaly's signal."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))

from tic_doctrine import __version__ as KIT  # noqa: E402
from launch import feed  # noqa: E402

NOW = "2026-11-23T12:00:00Z"
RING = [[0, 0], [1, 0], [1, 1], [0, 0]]


def tfr(issued="2026-11-23T00:00:00Z", windows=None):
    return {"id": "6/8694", "facility": "ZLC", "state": "ID", "description": "Boise", "created": "x", "rings": [RING],
            "detail": {"issued_utc": issued, "areas": [],
                       "windows": [{"start": "2026-11-25T10:00:00Z", "end": "2026-11-25T12:00:00Z"},
                                   {"start": "2026-11-24T10:00:00Z", "end": "2026-11-24T12:00:00Z"}]
                       if windows is None else windows}}


def match():
    return {"launch": "abc", "launch_name": "R | M", "net": "2026-11-25T00:18:00Z", "area": "A6094/26 ZXXX",
            "window": ["2026-11-25T00:08:00Z", "2026-11-25T00:48:00Z"], "level": "time and place", "azimuth": 106.2,
            "distance_nm": 506, "place_basis": "azimuth band", "inclination_est": 43.5, "grouped_with": None}


class Items(unittest.TestCase):
    def test_new_tfr_has_signal_and_window(self):
        p = feed._tfr_item(tfr(), NOW, NOW)["properties"]
        self.assertEqual(p["tier"], "anomaly")
        self.assertEqual(p["signal"], {"name": "hours_since_faa_issued", "value": 12.0, "unit": "hours", "tail": "low"})
        self.assertEqual((p["event_start"], p["event_end"]), ("2026-11-24T10:00:00Z", "2026-11-25T12:00:00Z"))
        self.assertEqual((p["last_change"], p["last_change_at"]), ("new", "2026-11-23T00:00:00Z"))

    def test_old_tfr_is_routine_with_no_signal(self):
        p = feed._tfr_item(tfr(issued="2026-11-01T00:00:00Z"), NOW, NOW)["properties"]
        self.assertEqual((p["tier"], p["last_change_at"]), ("routine", "2026-11-01T00:00:00Z"))
        self.assertNotIn("signal", p)

    def test_tfr_without_windows_uses_issue_time(self):
        p = feed._tfr_item(tfr(windows=[]), NOW, NOW)["properties"]
        self.assertEqual(p["event_start"], "2026-11-23T00:00:00Z")
        self.assertNotIn("event_end", p)

    def test_match_subject_has_no_space_and_id_is_unchanged(self):
        p = feed._match_item(match(), {"ring": RING, "source": "faa-nms"}, NOW, NOW)["properties"]
        self.assertEqual(p["id"], "launch:match:abc:A6094/26 ZXXX")
        self.assertEqual(p["subject_id"], "launch:match:abc:A6094/26-ZXXX")
        self.assertEqual((p["event_start"], p["event_end"], p["last_change"]),
                         ("2026-11-25T00:08:00Z", "2026-11-25T00:48:00Z", "none"))

    def test_header(self):
        doc = feed.build_feed({"generated_at": NOW})
        self.assertEqual((doc["contract_rev"], doc["kit"]), ("2.1", KIT))


if __name__ == "__main__":
    unittest.main()
