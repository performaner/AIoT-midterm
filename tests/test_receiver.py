import json
from pathlib import Path
import runpy
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch


class ReceiverTests(unittest.TestCase):
    def test_cue_after_normal_wait_reuses_live_socket(self):
        self.check_idle_cue(legacy=False)

    def test_cue_after_legacy_receiver_closes_idle_socket(self):
        self.check_idle_cue(legacy=True)

    def check_idle_cue(self, legacy):
        import threading
        import time
        from board_link import BoardLink

        peers = []
        handler_type = self.receiver['Handler']

        class Recorder(handler_type):
            def setup(self):
                super().setup()
                if legacy:
                    self.connection.settimeout(2)

            def send_header(self, key, value):
                if not (legacy and key == 'Keep-Alive'):
                    super().send_header(key, value)

            def do_POST(self):
                peers.append(self.client_address)
                if len(peers) == 2:
                    self.close_connection = True
                super().do_POST()

            def log_message(self, *args):
                pass

        bridge = self.receiver['Bridge']
        with self.receiver['Server'](('127.0.0.1', 0), Recorder) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                address = '127.0.0.1:%d' % server.server_port
                with patch('board_link.normalize_host', return_value=address), patch.object(
                        bridge, 'call', side_effect=lambda method, state, a, b: state):
                    link = BoardLink()
                    for state in (1, 2):
                        if state == 2:
                            time.sleep(2.3)
                        token = object()
                        link.send('127.0.0.1', state, token=token)
                        result = link.results.get(timeout=4)
                        self.assertEqual(result[:2], (token, True), link.status)
                self.assertEqual(len(peers), 2)
                self.assertEqual(peers[0] == peers[1], not legacy)
            finally:
                server.shutdown()
                server_thread.join()

    @classmethod
    def setUpClass(cls):
        module = ModuleType('arduino.app_utils')
        module.Bridge = Mock()
        with patch.dict(sys.modules, {'arduino': ModuleType('arduino'), 'arduino.app_utils': module}):
            cls.receiver = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'uno_q_reaction/python/main.py'))

    def test_score_payload(self):
        parse = self.receiver['parse_payload']
        for a in range(4):
            for b in range(4):
                self.assertEqual(parse(json.dumps({'state': 5, 'scores': [a, b]})), (5, [a, b]))

    def test_health_checks_mcu_version(self):
        import io
        handler_type = self.receiver['Handler']
        handler = handler_type.__new__(handler_type)
        handler.path = '/health'
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        bridge = handler_type.do_GET.__globals__['Bridge']
        for version, expected in [(7, True), (6, False)]:
            handler.wfile = io.BytesIO()
            bridge.call.return_value = version
            handler.do_GET()
            payload = json.loads(handler.wfile.getvalue())
            self.assertEqual(payload['mcu_ready'], expected)
            self.assertEqual(payload['version'], 7)
            bridge.call.assert_called_with('duel_version')

    def test_rejects_invalid_scores_and_old_clients(self):
        for data in [b'0', b'null', b'{}', b'broken', b'{"state":5,"scores":[-1,0]}',
                     b'{"state":5,"scores":[100,0]}', b'{"state":5,"scores":[50,50]}',
                     b'{"state":true,"scores":[0,0]}']:
            with self.assertRaises(ValueError):
                self.receiver['parse_payload'](data)

    def test_new_states_and_winner_validation(self):
        parse = self.receiver['parse_payload']
        for state in (2, 3, 4, 6):
            self.assertEqual(parse(json.dumps({'state': state, 'scores': [1, 2]})), (state, [1, 2]))
        self.assertEqual(parse('{"state":7,"scores":[3,1]}'), (7, [3, 1]))
        self.assertEqual(parse('{"state":8,"scores":[2,3]}'), (8, [2, 3]))
        self.assertEqual(parse('{"state":12,"scores":[1,2]}'), (12, [1, 2]))
        self.assertEqual(parse('{"state":13,"scores":[3,1]}'), (13, [3, 1]))
        self.assertEqual(parse('{"state":7,"scores":[60,39]}'), (7, [60, 39]))
        self.assertEqual(parse('{"state":16,"scores":[49,49]}'), (16, [49, 49]))
        for state, scores in [(7, [1, 3]), (8, [3, 2]), (7, [3, 3]), (13, [1, 3]),
                              (15, [0, 0]), (16, [2, 3]), (17, [1, 1])]:
            with self.assertRaises(ValueError):
                parse(json.dumps({'state': state, 'scores': scores}))

    def test_client_sends_scores_without_blocking(self):
        import threading
        from board_link import BoardLink
        received = []
        done = threading.Event()
        response = Mock(status=200)
        response.read.return_value = b'OK v7'
        connection = Mock()
        connection.getresponse.return_value = response
        def request(method, path, body, headers):
            received.append(json.loads(body))
            done.set()
        connection.request.side_effect = request
        with patch('board_link.http.client.HTTPConnection', return_value=connection):
            link = BoardLink()
            link.send('192.168.7.2:8765', 5, [2, 3])
            self.assertTrue(done.wait(2))
        self.assertEqual(received, [{'state': 5, 'scores': [2, 3]}])

    def test_client_reuses_connection_for_successive_states(self):
        import queue
        from board_link import BoardLink
        response = Mock(status=200)
        response.read.return_value = b'OK v7'
        connection = Mock()
        connection.getresponse.return_value = response
        with patch('board_link.http.client.HTTPConnection', return_value=connection) as factory:
            link = BoardLink()
            for state in (1, 2):
                token = object()
                link.send('192.168.7.2', state, [0, 0], token=token)
                result = link.results.get(timeout=2)
                self.assertIs(result[0], token)
                self.assertTrue(result[1])
            factory.assert_called_once()
            self.assertEqual(connection.request.call_count, 2)
