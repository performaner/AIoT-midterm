"""Original synthesized WAV effects; nonblocking Windows playback."""
import math
from pathlib import Path
import struct
import tempfile
import wave

NOTES = {
    'start': [(440, .06), (660, .08)],
    'cue': [(880, .07)],  # Identical for GO and NO-GO: never reveals the answer.
    'score': [(660, .08), (880, .12)],
    'fault': [(180, .12), (140, .15)],
    'safe': [(520, .06), (620, .08)],
    'win': [(523, .12), (659, .12), (784, .12), (1047, .3)],
}


def write_effect(path, notes):
    rate = 22050
    data = bytearray()
    for frequency, seconds in notes:
        count = int(rate * seconds)
        for i in range(count):
            envelope = min(1, i / 120, (count - 1 - i) / 180)
            value = int(7000 * envelope * math.sin(2 * math.pi * frequency * i / rate))
            data.extend(struct.pack('<h', value))
        data.extend(b'\0\0' * int(rate * .025))
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        audio.writeframes(data)


class SoundEffects:
    def __init__(self):
        self.folder = tempfile.TemporaryDirectory(prefix='reaction-effects-')
        self.error = ''
        self.enabled = True
        for name, notes in NOTES.items():
            write_effect(Path(self.folder.name) / f'{name}.wav', notes)

    def play(self, name):
        if not self.enabled:
            return
        try:
            import winsound
            winsound.PlaySound(str(Path(self.folder.name) / f'{name}.wav'),
                              winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            self.error = ''
        except (ImportError, RuntimeError, OSError) as exc:
            self.error = f'音效不可用，遊戲繼續：{exc}'

    def stop(self):
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except (ImportError, RuntimeError, OSError):
            pass

    def close(self):
        self.stop()
        self.folder.cleanup()
