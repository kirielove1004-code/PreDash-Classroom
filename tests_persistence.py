import unittest

from predash.persistence import capture, normalize, restore


class PersistenceTests(unittest.TestCase):
    def test_only_user_workspace_fields_are_saved(self):
        session = {
            "watch_codes": ["005930"], "watch_names": {"005930": "삼성전자"},
            "industry_note_005930": {"sector": "메모리", "path": "근거"},
            "classroom_credentials": {"secret": "never-save"}, "snapshot": {"value": 1},
        }
        saved = capture(session)
        self.assertNotIn("classroom_credentials", saved)
        self.assertNotIn("snapshot", saved)
        self.assertEqual(saved["industry_notes"]["005930"]["sector"], "메모리")

    def test_restore_round_trip(self):
        session = {}
        restored = restore(session, normalize({"watch_codes": ["000660"], "watch_names": {"000660": "SK하이닉스"}}))
        self.assertEqual(session["watch_codes"], ["000660"])
        self.assertEqual(restored["watch_names"]["000660"], "SK하이닉스")


if __name__ == "__main__":
    unittest.main()
