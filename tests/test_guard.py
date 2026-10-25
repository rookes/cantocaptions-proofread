"""The tripwire: ccp refuses to run once its own files change during a session."""
import pytest

from ccp import cli, guard, paths


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "src" / "ccp").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "src" / "ccp" / "reference.py").write_text("x = 1\n", encoding="utf-8")
    (root / "config" / "paths.local.toml").write_text("[setup]\n", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(paths, "ROOT", root)
    monkeypatch.setattr(paths, "cache_dir", lambda: cache)
    return root


def test_a_change_after_setup_is_caught(repo):
    assert guard.record() == []
    assert guard._diff(guard.fingerprint(), guard.fingerprint()) == []
    (repo / "src" / "ccp" / "reference.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "config" / "paths.local.toml").write_text("[setup]\ncompleted = true\n", encoding="utf-8")
    assert guard._diff(__import__("json").loads((paths.cache_dir() / "code_fingerprint.json").read_text()),
                       guard.fingerprint()) == ["src/ccp/reference.py"]     # ccp's own writes are not watched
    assert guard.record() == ["src/ccp/reference.py"]                       # the next setup reports it


def test_ccp_refuses_to_run_while_its_code_differs(repo, monkeypatch):
    monkeypatch.setattr(guard, "changed", lambda: ["src/ccp/reference.py"])
    with pytest.raises(SystemExit, match="src/ccp/reference.py"):
        cli.main(["glossaries"])
