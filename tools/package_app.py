"""Build the importable App Lab ZIP from reviewed source files."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FILES = ('app.yaml', 'python/main.py', 'sketch/sketch.ino', 'sketch/sketch.yaml')


def build():
    destination = ROOT / 'dist' / 'uno_q_reaction.zip'
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / 'uno_q_reaction' / name, name)
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert '  - 8765' in archive.read('app.yaml').decode()
    return destination


if __name__ == '__main__':
    print(build())
