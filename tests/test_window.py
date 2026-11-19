import queue
import tkinter as tk
import unittest
from unittest.mock import patch
from reaction_game import Window


class FakeLink:
    def __init__(self):
        self.results = queue.Queue()
        self.status = 'Test receiver'
        self.sent = []

    def send(self, host, state, scores=(0, 0), token=None):
        self.sent.append((state, list(scores), token))


class FakeSound:
    def __init__(self):
        self.events = []
        self.error = ''
        self.enabled = True

    def play(self, effect):
        if self.enabled:
            self.events.append(effect)

    def stop(self):
        pass

    def close(self):
        pass


class WindowTests(unittest.TestCase):
    def test_practice_cycles_and_shows_led_feedback(self):
        self.w.mode.set('visual')
        self.w.session.set('practice')
        self.w.start()
        self.assertTrue(self.w.game.practice)
        self.w.game.show_go()
        self.now += .2
        self.w.game.press(0)
        self.w.render()
        self.assertEqual(self.w.link.sent[-1][:2], (9, [0, 0]))
        self.assertIn('平均 200 ms', self.w.statistics.cget('text'))
        self.w.tick()
        self.now += .8
        self.w.tick()
        self.assertEqual(self.w.game.state, 'waiting')
        self.now = 41
        self.w.tick()
        self.assertEqual(self.w.game.state, 'practice_done')
        self.assertEqual(self.w.link.sent[-1][:2], (11, [0, 0]))

    def test_custom_key_rejects_duplicate_and_scores(self):
        from types import SimpleNamespace
        from tempfile import TemporaryDirectory
        from pathlib import Path
        self.w.keys = ['a', 'l']
        self.w.mode.set('visual')
        event = lambda key: SimpleNamespace(widget=self.root, keysym=key)
        with TemporaryDirectory() as folder, patch('reaction_game.KEY_SETTINGS', Path(folder) / 'keys.json'):
            from reaction_game import load_keys
            self.w.edit_key(0)
            self.w.key_down(event('l'))
            self.w.key_up(event('l'))
            self.assertEqual(self.w.edit_player, 0)
            self.w.key_down(event('z'))
            self.w.key_up(event('z'))
            self.assertEqual(load_keys(), ['z', 'l'])
        self.w.start()
        self.w.game.show_go()
        self.w.key_down(event('a'))
        self.assertEqual(self.w.game.scores, [0, 0])
        self.w.key_down(event('z'))
        self.assertEqual(self.w.game.scores, [1, 0])

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        with patch('reaction_game.BoardLink', FakeLink), patch('reaction_game.SoundEffects', FakeSound), patch('reaction_game.last_host', return_value=''):
            self.w = Window(self.root)
        self.now = 10.0
        self.w.game.clock = lambda: self.now
        self.w.host.insert(0, '192.168.7.2:8765')

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.after_cancel(job)
        self.root.destroy()

    def ack(self, success=True):
        self.w.link.results.put((self.w.cue_token, success, self.now, self.now - .04))
        self.w.tick()

    def start_cue(self):
        self.w.start()
        self.assertEqual(self.w.game.state, 'arming')
        self.ack()
        self.assertEqual(self.w.game.state, 'waiting')
        self.now = self.w.game.due
        self.w.tick()
        self.assertEqual(self.w.game.state, 'cue')

    def test_confirmed_led_then_score(self):
        self.start_cue()
        waiting_text = self.w.stage.cget('text')
        self.ack()
        self.assertEqual(self.w.game.state, 'go')
        self.assertEqual(self.w.stage.cget('text'), waiting_text)
        self.now += .2
        self.w.game.press(1)
        self.w.render()
        self.assertEqual(self.w.link.sent[-1][:2], (12, [0, 1]))
        self.assertAlmostEqual(self.w.game.reactions[1], 220)
        self.assertIn('220 ms', self.w.times[1].cget('text'))
        self.assertIn('±20 ms', self.w.times[1].cget('text'))

    def test_connection_failure_cannot_score(self):
        self.w.start()
        self.ack(False)
        self.assertEqual(self.w.game.reason, 'connection')
        self.assertEqual(self.w.game.scores, [0, 0])

    def test_uncertain_key_and_stale_ack(self):
        self.start_cue()
        token = self.w.cue_token
        self.w.game.press(0)
        self.assertEqual(self.w.game.reason, 'ambiguous')
        self.w.render()
        self.w.reset()
        self.w.link.results.put((token, True, self.now, self.now))
        self.w.tick()
        self.assertEqual(self.w.game.state, 'ready')
        self.assertEqual(self.w.game.scores, [0, 0])

    def test_offline_and_unresponsive_board(self):
        self.w.mode.set('visual')
        self.w.start()
        self.now = self.w.game.due
        self.w.tick()
        self.assertEqual(self.w.game.state, 'go')
        self.w.reset()
        self.w.mode.set('board')
        self.w.start()
        self.now += 6
        self.w.tick()
        self.assertEqual(self.w.game.reason, 'connection')

    def test_no_go_color_and_champion_message(self):
        self.w.rule.set('green')
        self.w.rounds_entry.delete(0, 'end')
        self.w.rounds_entry.insert(0, '1')
        self.w.start()
        self.ack()
        self.w.game.allow_press = False
        self.now = self.w.game.due
        self.w.tick()
        self.assertEqual(self.w.link.sent[-1][0], 3)
        self.ack()
        self.assertEqual(self.w.game.state, 'hold')
        self.now += .25
        self.w.game.press(1)
        self.w.render()
        self.assertEqual(self.w.link.sent[-1][:2], (7, [1, 0]))
        self.assertEqual(self.w.detail.cget('text'), 'Congratulations! Player 1 WIN')
        self.assertTrue(all(b.cget('state') == 'disabled' for b in self.w.rule_buttons))

    def test_custom_match_counts_all_rounds_and_sends_overall_winner(self):
        self.w.mode.set('visual')
        self.w.rounds_entry.delete(0, 'end')
        self.w.rounds_entry.insert(0, '100')
        self.w.start()
        self.assertEqual(self.w.game.state, 'ready')
        self.assertIn('1 到 99', self.w.info.cget('text'))
        self.w.rounds_entry.delete(0, 'end')
        self.w.rounds_entry.insert(0, '4')
        for index, player in enumerate((0, 0, 0, 1)):
            self.w.start()
            self.w.game.show_go()
            self.w.game.press(player)
            self.w.render()
            if index < 3:
                self.assertEqual(self.w.game.state, 'result')
        self.assertEqual(self.w.game.state, 'match')
        self.assertEqual(self.w.link.sent[-1][:2], (13, [3, 1]))
        self.assertEqual(self.w.detail.cget('text'), 'Congratulations! Player 1 WIN')

    def test_discovery_result_selects_board_and_syncs(self):
        self.w.searching = True
        self.w.discovery_results.put(([{'host': '192.168.1.9:8765', 'board_id': 'test'}], ''))
        with patch('reaction_game.remember') as save:
            self.w.poll_discovery()
            save.assert_called_once_with('192.168.1.9:8765')
        self.assertEqual(self.w.host.get(), '192.168.1.9')
        self.assertEqual(self.w.link.sent[-1][:2], (5, [0, 0]))
        self.assertFalse(self.w.searching)

    def test_sound_does_not_repeat_or_reveal_color(self):
        self.w.mode.set('visual')
        self.w.start()
        self.w.render()
        self.assertEqual(self.w.sounds.events, [])
        self.w.game.allow_press = False
        self.w.game.show_go()
        self.w.render()
        self.assertEqual(self.w.sounds.events, [])
        self.w.game.state = 'go'
        self.w.render()
        self.assertEqual(self.w.sounds.events, [])
        self.w.game.press(0)
        self.w.render()
        self.assertEqual(self.w.sounds.events[-1], 'score')
        count = len(self.w.sounds.events)
        self.w.render()
        self.assertEqual(len(self.w.sounds.events), count)
        self.w.sound_enabled.set(False)
        self.w.toggle_sound()
        self.w.sounds.play('win')
        self.assertEqual(len(self.w.sounds.events), count)
