import json
import unittest
from unittest.mock import Mock, patch
import discovery


class DiscoveryTests(unittest.TestCase):
    def test_ip_needs_no_port(self):
        self.assertEqual(discovery.normalize_host(' 192.168.7.2 '), '192.168.7.2:8765')
        self.assertEqual(discovery.normalize_host('unoq.local:8765'), 'unoq.local:8765')
        for value in ('', 'http://host', 'host:80', 'user@host', 'host/path'):
            with self.assertRaises(ValueError):
                discovery.normalize_host(value)

    def test_scan_is_local_bounded_and_excludes_self(self):
        hosts = discovery.candidates([('192.168.5.7', 16), ('127.0.0.1', 8), ('8.8.8.8', 24)])
        self.assertEqual(len(hosts), 253)
        self.assertNotIn('192.168.5.7', hosts)
        self.assertTrue(all(h.startswith('192.168.5.') for h in hosts))

    def test_probe_checks_identity_version_and_mcu(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch('discovery.urllib.request.build_opener', return_value=opener):
            for version, ready, service in [(6, True, 'uno-q-reaction'), (7, False, 'uno-q-reaction'), (7, True, 'other')]:
                response.read.return_value = json.dumps({'version': version, 'mcu_ready': ready, 'service': service, 'board_id': 'x'}).encode()
                self.assertIsNone(discovery.probe('192.168.7.2'))
            response.read.return_value = b'{"version":7,"mcu_ready":true,"service":"uno-q-reaction","board_id":"q"}'
            self.assertEqual(discovery.probe('192.168.7.2')['host'], '192.168.7.2:8765')

    def test_prefers_saved_board_and_deduplicates_interfaces(self):
        board = {'host': '192.168.7.2:8765', 'board_id': 'q'}
        with patch('discovery.last_host', return_value=''), patch('discovery.probe', return_value=board), patch('discovery.local_networks') as networks:
            self.assertEqual(discovery.discover('192.168.7.2'), [board])
            networks.assert_not_called()
        def probe(host):
            return {'host': host, 'board_id': 'same-board'} if host in ('a', 'b') else None
        with patch('discovery.last_host', return_value=''), patch('discovery.probe', side_effect=probe), patch('discovery.local_networks', return_value=[]), patch('discovery.candidates', return_value=['a', 'b']):
            self.assertEqual(len(discovery.discover()), 1)
