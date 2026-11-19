from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import Mock, patch
from sound_effects import SoundEffects, NOTES, write_effect


class SoundTests(unittest.TestCase):
    def test_effects_are_valid_short_wav_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, notes in NOTES.items():
                path = Path(directory) / f'{name}.wav'
                write_effect(path, notes)
                with wave.open(str(path)) as audio:
                    self.assertEqual(audio.getnchannels(), 1)
                    self.assertEqual(audio.getsampwidth(), 2)
                    self.assertTrue(0 < audio.getnframes() / audio.getframerate() < 2)

    def test_mute_and_nonblocking_playback(self):
        mock = Mock(SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4)
        with patch.dict('sys.modules', {'winsound': mock}):
            sound = SoundEffects()
            sound.play('cue')
            self.assertEqual(mock.PlaySound.call_args.args[1], 7)
            mock.PlaySound.reset_mock()
            sound.enabled = False
            sound.play('win')
            mock.PlaySound.assert_not_called()
            folder = sound.folder.name
            sound.close()
            self.assertFalse(Path(folder).exists())
