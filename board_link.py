"""Nonblocking LAN connection to the UNO Q LED companion."""
import json
import queue
import threading
import http.client
import time
from discovery import normalize_host


def reuse_seconds(response):
    # Original v6 receivers close after two idle seconds without a header.
    for field in str(response.getheader('Keep-Alive', '')).split(','):
        key, _, value = field.strip().partition('=')
        if key.lower() == 'timeout' and value.isascii() and value.isdecimal() and len(value) <= 5:
            return max(0, min(60, int(value)) - 1)
    return 1


class BoardLink:
    """Network work never blocks the game clock or keyboard."""
    def __init__(self):
        self.jobs = queue.Queue(maxsize=1)
        self.results = queue.Queue()
        self.status = 'UNO Q：未連線（可離線遊玩）'
        threading.Thread(target=self.worker, daemon=True).start()

    def send(self, host, state, scores=(0, 0), token=None):
        if not host.strip():
            self.status = 'UNO Q：未連線（可離線遊玩）'
            return
        try:
            discarded = self.jobs.get_nowait()
            if discarded[3] is not None:
                now = time.perf_counter()
                self.results.put((discarded[3], False, now, now))
        except queue.Empty:
            pass
        self.jobs.put_nowait((host.strip(), state, list(scores), token))

    def worker(self):
        connection = None
        connected_host = None
        reuse_until = 0
        while True:
            host, state, scores, token = self.jobs.get()
            success = False
            sent = time.perf_counter()
            try:
                host = normalize_host(host)
                if host != connected_host or time.perf_counter() >= reuse_until:
                    if connection:
                        connection.close()
                    address, port = host.rsplit(':', 1)
                    connection = http.client.HTTPConnection(address, int(port), timeout=1.2)
                    connected_host = host
                data = json.dumps({'state': state, 'scores': scores}).encode()
                sent = time.perf_counter()
                connection.request('POST', '/state', body=data,
                                   headers={'Content-Type': 'application/json'})
                response = connection.getresponse()
                body = response.read()
                if response.status == 503:
                    raise ValueError('已連到 UNO Q，但 MCU 尚未確認燈號，請查看 App Lab 日誌')
                if response.status != 200 or body != b'OK v7':
                    raise ValueError(f'UNO Q 回覆 HTTP {response.status}，請確認 App Lab 正在執行 Reaction Duel v7')
                reuse_until = sent + reuse_seconds(response)
                self.status = 'UNO Q：燈號連動正常'
                success = True
            except Exception as exc:
                if connection:
                    connection.close()
                connection = None
                connected_host = None
                self.status = f'UNO Q：連線失敗，遊戲繼續（{exc}）'
            if token is not None:
                self.results.put((token, success, time.perf_counter(), sent))

