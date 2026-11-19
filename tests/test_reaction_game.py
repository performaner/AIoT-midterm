import unittest
import random
from reaction_game import Duel


class DuelTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.g = Duel(lambda: self.now, random.Random(1))

    def test_wait_and_false_start(self):
        self.g.start()
        self.assertTrue(12 <= self.g.due <= 15)
        self.g.press(0)
        self.assertEqual(self.g.scores, [0, 1])
        self.assertEqual(self.g.reason, 'false_start')
        self.g.press(1)
        self.assertEqual(self.g.scores, [0, 1])

    def test_first_press_wins_second_is_timing_only(self):
        self.g.start()
        self.g.show_go()
        self.now += .25
        self.g.press(1)
        self.now += .05
        self.g.press(0)
        self.assertEqual(self.g.scores, [0, 1])
        self.assertAlmostEqual(self.g.reactions[1], 250)
        self.assertAlmostEqual(self.g.reactions[0], 300)
        self.g.press(0)
        self.assertEqual(self.g.scores, [0, 1])

    def test_match_and_reset(self):
        for _ in range(5):
            self.g.start()
            self.g.show_go()
            self.g.press(0)
        self.assertEqual(self.g.state, 'match')
        self.assertFalse(self.g.start())
        self.g.reset()
        self.assertEqual(self.g.scores, [0, 0])
        self.assertEqual(self.g.round, 0)

    def test_cancel_and_timeout(self):
        self.g.start()
        self.g.cancel()
        self.assertEqual(self.g.round, 0)
        self.assertEqual(self.g.scores, [0, 0])
        self.g.start()
        self.g.show_go()
        self.now += 5
        self.g.press(0)
        self.assertEqual(self.g.reason, 'timeout')
        self.assertEqual(self.g.scores, [0, 0])

    def test_due_time_does_not_start_before_paint(self):
        self.g.start()
        self.now = self.g.due + 1
        self.g.press(0)
        self.assertEqual(self.g.reason, 'false_start')

    def test_color_rules_and_wrong_color(self):
        for rule, go, stop in [('green', 2, 3), ('red', 4, 6)]:
            for allowed in (True, False):
                self.g.reset()
                self.g.start(rule)
                self.g.allow_press = allowed
                self.assertEqual(self.g.cue_code, go if allowed else stop)
                self.g.show_go()
                self.now += .3
                self.g.press(0)
                self.assertEqual(self.g.scores, [1, 0] if allowed else [0, 1])
                self.assertAlmostEqual(self.g.reactions[0], 300)

    def test_successful_hold_and_late_key(self):
        self.g.start('red')
        self.g.allow_press = False
        self.g.show_go()
        self.now += 2
        self.g.press(0)
        self.assertEqual(self.g.reason, 'held')
        self.assertEqual(self.g.scores, [0, 0])
        self.g.press(1)
        self.assertEqual(self.g.scores, [0, 0])

    def test_timing_midpoint_and_network_interval(self):
        self.g.start()
        self.g.state = 'cue'
        self.g.show_go(timestamp=9.98, uncertainty_ms=20)
        self.now = 10.2
        self.g.press(0)
        self.assertAlmostEqual(self.g.reactions[0], 220)
        self.assertEqual(self.g.uncertainty_ms, 20)

    def test_practice_statistics_and_no_scores(self):
        self.g.begin_practice()
        self.g.start('green')
        self.g.press(0)
        self.assertEqual(self.g.stats[0]['false_starts'], 1)
        self.assertEqual(self.g.scores, [0, 0])
        self.g.start('classic')
        self.g.show_go()
        self.now += .2
        self.g.press(1)
        self.assertAlmostEqual(self.g.stats[1]['times'][0], 200)
        self.assertEqual(self.g.scores, [0, 0])
        self.now = 40
        self.g.end_practice()
        self.assertEqual(self.g.state, 'practice_done')
        self.assertEqual(self.g.matches, 0)

    def test_match_win_rate_counts_once(self):
        for _ in range(5):
            self.g.start()
            self.g.show_go()
            self.g.press(0)
        self.assertEqual((self.g.matches, self.g.match_wins), (1, [1, 0]))
        self.g.reset()
        self.assertEqual((self.g.matches, self.g.match_wins), (1, [1, 0]))

    def test_even_match_ends_in_a_tie_and_skips_no_score_round(self):
        self.g.match_rounds = 2
        self.g.start()
        self.g.show_go()
        self.g.timeout()
        self.assertEqual(self.g.round, 0)
        for player in (0, 1):
            self.assertTrue(self.g.start())
            self.g.show_go()
            self.g.press(player)
        self.assertEqual(self.g.state, 'match')
        self.assertEqual(self.g.scores, [1, 1])
        self.assertIsNone(self.g.match_winner)
        self.assertEqual((self.g.matches, self.g.match_wins), (1, [0, 0]))


if __name__ == '__main__':
    unittest.main()
