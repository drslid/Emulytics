import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def installer(tmp_path, monkeypatch):
    location = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap-console.py"
    spec = importlib.util.spec_from_file_location("bootstrap_console_test", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "ARCHIVE", tmp_path / "storage" / "install")
    monkeypatch.setattr(module, "ACCESS", module.ARCHIVE / "initial-access.json")
    monkeypatch.setattr(module.sys, "argv", ["bootstrap-console.py"])
    return module


def service(module, initialized=False, pending=False):
    state = {"initialized": initialized, "pending": pending, "password": None, "bootstraps": 0, "lose_response": False}

    def call(action, password=None):
        if action == "bootstrap":
            assert module.ACCESS.exists(), "Deliverable must be durable before DB account creation"
            assert json.loads(module.ACCESS.read_text())["password"] == password
            assert not state["initialized"]
            state.update(initialized=True, pending=True, password=password)
            state["bootstraps"] += 1
            if state["lose_response"]:
                state["lose_response"] = False
                raise RuntimeError("Lost response after database commit")
        return {"initialized": state["initialized"], "pending": state["pending"], "matches": password is not None and password == state["password"]}

    module.backend = call
    return state


def test_installation_delivers_private_unique_password_and_keeps_it_on_restart(installer, capsys):
    state = service(installer)
    installer.main()
    first = installer.ACCESS.read_bytes()
    password = json.loads(first)["password"]
    assert len(password) >= 24
    assert installer.ACCESS.stat().st_mode & 0o777 == 0o600
    assert installer.ARCHIVE.stat().st_mode & 0o777 == 0o700
    installer.main()
    assert installer.ACCESS.read_bytes() == first
    assert state["bootstraps"] == 1
    assert password not in capsys.readouterr().out


def test_committed_account_survives_lost_response_without_replacing_password(installer):
    state = service(installer)
    state["lose_response"] = True
    with pytest.raises(RuntimeError):
        installer.main()
    original = installer.ACCESS.read_bytes()
    installer.main()
    assert installer.ACCESS.read_bytes() == original
    assert state["bootstraps"] == 1


def test_partial_credential_write_is_not_published_and_restart_recovers(installer, monkeypatch):
    state = service(installer)

    def interrupted_dump(item, output, **options):
        output.write('{"schema":')
        raise OSError("Interrupted credential delivery")

    with monkeypatch.context() as patch:
        patch.setattr(installer.json, "dump", interrupted_dump)
        with pytest.raises(OSError):
            installer.main()
    assert not installer.ACCESS.exists()
    assert not list(installer.ARCHIVE.glob(".initial-access-*"))
    assert state["bootstraps"] == 0
    installer.main()
    assert state["bootstraps"] == 1


def test_configured_installation_never_creates_new_credentials(installer):
    state = service(installer, initialized=True)
    installer.main()
    assert not installer.ACCESS.exists()
    assert state["bootstraps"] == 0


def test_missing_pending_password_is_not_silently_rotated(installer):
    state = service(installer, initialized=True, pending=True)
    with pytest.raises(RuntimeError):
        installer.main()
    assert not installer.ACCESS.exists()
    assert state["bootstraps"] == 0


def test_publicly_readable_candidate_is_refused(installer):
    service(installer)
    installer.main()
    installer.ACCESS.chmod(0o644)
    with pytest.raises(RuntimeError):
        installer.main()


def test_installer_refuses_redirected_directory(installer, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    installer.ARCHIVE.parent.mkdir(parents=True)
    installer.ARCHIVE.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError):
        installer.main()
    assert not list(outside.iterdir())
