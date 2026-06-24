from pathlib import Path

from broll_search.config import Config


def test_is_path_under_footage_roots(tmp_path):
    root = tmp_path / "footage"
    nested = root / "2026" / "clip.mov"
    nested.parent.mkdir(parents=True)
    nested.touch()
    outside = tmp_path / "other" / "secret.mov"
    outside.parent.mkdir()
    outside.touch()

    cfg = Config(footage_paths=[str(root)])
    assert cfg.is_path_under_footage_roots(str(nested))
    assert not cfg.is_path_under_footage_roots(str(outside))
    assert not cfg.is_path_under_footage_roots("")


def test_is_path_under_footage_roots_no_roots():
    cfg = Config(footage_paths=[])
    assert cfg.is_path_under_footage_roots("/any/path.mov")
