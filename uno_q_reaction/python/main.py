"""LAN-only LED receiver. Run inside Arduino App Lab on UNO Q."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
from arduino.app_utils import Bridge

BRIDGE_LOCK = threading.Lock()
IDLE_TIMEOUT = 60


def parse_payload(data):
    body = json.loads(data)
    if not isinstance(body, dict):
        raise ValueError('Update the PC game to the latest version')
    state, scores = body.get('state'), body.get('scores')
    if type(state) is not int or not 0 <= state <= 16:
        raise ValueError('Invalid state')
    if (not isinstance(scores, list) or len(scores) != 2
            or any(type(x) is not int or not 0 <= x <= 99 for x in scores)
            or sum(scores) > 99):
        raise ValueError('Invalid scores')
    winner = {7: 0, 8: 1, 13: 0, 14: 1}.get(state)
    if winner is not None and scores[winner] <= scores[1 - winner]:
        raise ValueError('Invalid winner')
    if state in (15, 16) and (scores[0] != scores[1] or scores[0] == 0):
        raise ValueError('Invalid tie')
    return state, scores


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def reply(self, status, body, content_type='text/plain'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Keep-Alive', f'timeout={IDLE_TIMEOUT}')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != '/health':
            self.send_error(404)
            return
        try:
            with BRIDGE_LOCK:
                ready = Bridge.call('duel_version') == 7
        except Exception:
            ready = False
        data = json.dumps({'service': 'uno-q-reaction', 'version': 7,
                           'board_id': socket.gethostname(), 'mcu_ready': ready}).encode()
        self.reply(200, data, 'application/json')

    def do_POST(self):
        if self.path != '/state':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 256:
                raise ValueError('Invalid body length')
            value, scores = parse_payload(self.rfile.read(length))
        except (ValueError, UnicodeError):
            self.send_error(400)
            return
        try:
            with BRIDGE_LOCK:
                result = Bridge.call('show_duel_v7', value, scores[0], scores[1])
            if result != value:
                raise RuntimeError('Unexpected bridge response')
        except Exception as exc:
            print(f'LED bridge failed: {exc}', flush=True)
            self.send_error(503, 'MCU unavailable')
            return
        self.reply(200, b'OK v7')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(IDLE_TIMEOUT)
        return connection, address


if __name__ == '__main__':
    server = Server(('0.0.0.0', 8765), Handler)
    print('Reaction Duel v7 LED receiver listening on port 8765', flush=True)
    server.serve_forever()
