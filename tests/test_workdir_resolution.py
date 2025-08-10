from pathlib import Path
import shutil

from app.__init__ import create_app


def test_default_workdir(monkeypatch):
    monkeypatch.delenv('WORK_DIR', raising=False)
    app = create_app()
    work = Path(app.config['WORK_DIR'])
    assert work == Path('/tmp/peakpilot')
    assert work.exists()
    shutil.rmtree(work)


def test_relative_workdir(monkeypatch):
    monkeypatch.delenv('WORK_DIR', raising=False)
    monkeypatch.setenv('WORK_DIR', 'relwork')
    app = create_app()
    work = Path(app.config['WORK_DIR'])
    expected = Path(__file__).resolve().parent.parent / 'relwork'
    assert work == expected
    assert work.exists()
    shutil.rmtree(work)
