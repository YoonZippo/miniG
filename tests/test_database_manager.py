import os
import tempfile
import unittest

from database.manager import DatabaseManager


class GameResultTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.temp_dir.name, "test.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_records_results_once_and_updates_legacy_stats(self):
        participants = [101, 102, 103]
        winners = [101]

        self.assertTrue(self.db.record_game_result("liar-1", "liar", participants, winners))
        self.assertFalse(self.db.record_game_result("liar-1", "liar", participants, winners))
        self.assertEqual(self.db.get_game_stats(101)["liar"], {
            "plays": 1,
            "wins": 1,
            "draws": 0,
        })
        self.assertEqual(self.db.get_game_stats(102)["liar"], {
            "plays": 1,
            "wins": 0,
            "draws": 0,
        })
        self.assertEqual(self.db.get_user_stats(101), (1, 1, 0, 0))
        self.assertEqual(self.db.get_user_economy(101)["points"], 570)
        self.assertEqual(self.db.get_user_economy(102)["points"], 520)

        with self.db._connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM point_logs WHERE reason LIKE 'GAME_%_liar'"
                ).fetchone()[0],
                3,
            )

    def test_records_draws_and_rejects_nonparticipants(self):
        self.assertTrue(self.db.record_game_result(
            "cheese-1",
            "cheese_thief",
            [201, 202],
            draw_ids=[201, 202],
        ))
        self.assertEqual(self.db.get_game_stats(201)["cheese_thief"], {
            "plays": 1,
            "wins": 0,
            "draws": 1,
        })
        self.assertEqual(self.db.get_user_economy(201)["points"], 520)
        self.assertEqual(self.db.get_user_economy(202)["points"], 520)

        with self.assertRaises(ValueError):
            self.db.record_game_result("bad-game", "cheese_thief", [201], [202])

        self.assertEqual(self.db.get_game_stats(202)["cheese_thief"]["plays"], 1)

    def test_special_winner_receives_special_reward_instead_of_regular_win_reward(self):
        self.assertTrue(self.db.record_game_result(
            "spyfall-1",
            "spyfall",
            [301, 302, 303],
            winner_ids=[301, 302],
            special_winner_ids=[301],
        ))
        self.assertEqual(self.db.get_user_economy(301)["points"], 620)
        self.assertEqual(self.db.get_user_economy(302)["points"], 570)
        self.assertEqual(self.db.get_user_economy(303)["points"], 520)

    def test_non_rewarded_games_do_not_change_gpoints(self):
        self.db.record_game_result("poker-1", "holdem", [401, 402], [401])
        self.assertEqual(self.db.get_user_economy(401)["points"], 500)
        self.assertEqual(self.db.get_user_economy(402)["points"], 500)

    def test_consonant_completion_reward_does_not_add_unplanned_win_bonus(self):
        self.db.record_game_result("consonant-1", "consonant", [501, 502], [501])
        self.assertEqual(self.db.get_user_economy(501)["points"], 520)
        self.assertEqual(self.db.get_user_economy(502)["points"], 520)


if __name__ == "__main__":
    unittest.main()
