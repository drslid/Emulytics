"""Exercise release activation without touching a production Docker stack."""

import importlib.util
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest


OLD = "a" * 40
NEW = "b" * 40
REQUEST_ID = "f57e4edd-dc60-4f3b-ae62-d690a82d81a8"
WORKER = {"EMULYTIX_HOST_ID": "original-worker", "ADB_SERVER_SOCKET": "tcp:android-custom:5037"}


@pytest.fixture
def updater(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "scripts/update.py"
    spec = importlib.util.spec_from_file_location("host_update_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.parametrize("fields", [
    {"version": "01.2.3"},
    {"version": "1.2.3-rc.1"},
    {"version": "1.2.3", "command": "echo test"},
    {"version": "1.2.3", "id": "not-a-uuid"},
])
def test_rejects_untrusted_request(updater, monkeypatch, fields):
    monkeypatch.setattr(updater, "read_json", lambda _: {"id": str(uuid4()), **fields})
    with pytest.raises(ValueError):
        updater.requested_update(None)


def test_refuses_unpublished_or_changed_remote_tag(updater, monkeypatch):
    release = {"tag_name": "v0.2.0", "draft": False, "prerelease": False, "target_commitish": NEW}
    reference = {"ref": "refs/tags/v0.2.0", "object": {"type": "commit", "sha": NEW}}
    monkeypatch.setattr(updater, "github_json", lambda endpoint: release if endpoint == "/releases/latest" else reference)
    fetched = []
    monkeypatch.setattr(updater, "command", lambda args, **_: fetched.append(args))
    monkeypatch.setattr(updater, "git", lambda *_: OLD)
    with pytest.raises(updater.UpdateError, match="version_unavailable"):
        updater.published_target("0.1.1")
    assert not fetched
    with pytest.raises(updater.UpdateError, match="invalid_release"):
        updater.published_target("0.2.0")
    assert fetched == [["git", "fetch", "--no-tags", updater.REPOSITORY, "refs/tags/v0.2.0"]]


@pytest.fixture
def installation(updater, monkeypatch):
    config = updater.ROOT / ".env.console"
    config.write_text("EMULYTIX_AUTH_KEY=existing", encoding="utf-8")
    (updater.ROOT / "storage").mkdir()
    (updater.ROOT / "storage" / "existing").write_bytes(b"Android data")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    git_responses = {
        ("rev-parse", "--show-toplevel"): str(updater.ROOT),
        ("status", "--porcelain", "--untracked-files=no"): "",
        ("rev-parse", "HEAD"): OLD,
        ("show", "HEAD:VERSION"): "0.1.0",
        ("rev-parse", "refs/heads/main"): OLD,
        ("ls-tree", "-r", "--name-only", OLD, "--", ".env.console", ".env", ".install.lock", "storage"): "storage/.gitkeep",
        ("ls-tree", "-r", "--name-only", NEW, "--", ".env.console", ".env", ".install.lock", "storage"): "storage/.gitkeep",
    }
    commands = []
    steps = []

    def run(args, **_):
        commands.append(args)
        if args[:2] == ["git", "switch"] and "--detach" in args:
            git_responses[("rev-parse", "HEAD")] = args[-1]
        output = "main" if args[1] == "symbolic-ref" else ""
        return subprocess.CompletedProcess(args, 0, output)

    journal = {}

    def read_journal(path, limit):
        if path not in journal:
            raise FileNotFoundError(path)
        return journal[path].copy()

    monkeypatch.setattr(updater, "git", lambda *args: git_responses[args])
    monkeypatch.setattr(updater, "command", run)
    monkeypatch.setattr(updater, "published_target", lambda _: NEW)
    monkeypatch.setattr(updater, "installation_containers", lambda _, **kwargs: ["local"])
    monkeypatch.setattr(updater, "container_environment", lambda _: {
        "POSTGRES_DB": "emulytix", "POSTGRES_USER": "emulytix_console",
    })
    monkeypatch.setattr(updater, "local_worker", lambda: WORKER.copy())
    monkeypatch.setattr(updater, "deployment_lock", lambda: nullcontext(lambda: None))
    monkeypatch.setattr(updater, "require_local_database", lambda *args: None)
    monkeypatch.setattr(updater, "read_json", read_journal)
    monkeypatch.setattr(updater, "write_document", lambda path, value, mode: journal.update({path: value.copy()}))
    monkeypatch.setattr(updater, "compose", lambda *args, **_: steps.append(args[0]))
    monkeypatch.setattr(updater, "ensure_idle", lambda **options: steps.append("gate" if options.get("verify_gate") else "idle"))
    monkeypatch.setattr(updater, "activate", lambda worker, version: steps.append((worker, version)))
    return config, commands, steps, git_responses, journal


def test_prebuilds_and_checks_active_runs_again_before_restarting(updater, installation):
    config, commands, steps, _, journal = installation
    updater.apply_update("0.2.0", REQUEST_ID)
    assert steps == ["idle", "build", "build", "gate", (WORKER, "0.2.0")]
    assert commands[-1] == ["git", "switch", "--no-overwrite-ignore", "--detach", NEW]
    assert any(command[:3] == ["git", "worktree", "add"] for command in commands[:-1])
    assert next(iter(journal.values()))["original"] == OLD
    assert config.read_text(encoding="utf-8") == "EMULYTIX_AUTH_KEY=existing"
    assert (updater.ROOT / "storage" / "existing").read_bytes() == b"Android data"


def test_restarts_original_branch_after_activation_failure(updater, installation, monkeypatch):
    _, commands, steps, _, _ = installation

    def activate(worker, version):
        steps.append((worker, version))
        if version == "0.2.0":
            raise updater.UpdateError("installation_failed")

    monkeypatch.setattr(updater, "activate", activate)
    with pytest.raises(updater.UpdateError, match="installation_failed"):
        updater.apply_update("0.2.0", REQUEST_ID)
    assert [command for command in commands if command[:2] == ["git", "switch"]] == [
        ["git", "switch", "--no-overwrite-ignore", "--detach", NEW],
        ["git", "switch", "--no-overwrite-ignore", "--detach", OLD],
        ["git", "switch", "--no-overwrite-ignore", "--", "main"],
    ]
    assert [command[-1] for command in commands if command[:3] == ["git", "worktree", "add"]] == [NEW, OLD]
    assert steps[-4:] == [(WORKER, "0.2.0"), "build", "build", (WORKER, "0.1.0")]


def test_downgrade_does_not_contact_release_server_or_docker(updater, installation, monkeypatch):
    _, commands, steps, _, _ = installation
    monkeypatch.setattr(updater, "published_target", lambda _: pytest.fail("unexpected release lookup"))
    with pytest.raises(updater.UpdateError, match="not_newer"):
        updater.apply_update("0.0.9", REQUEST_ID)
    assert not steps
    assert not any(command[0] == "docker" for command in commands)


def test_does_not_overwrite_local_storage(updater, installation):
    _, commands, steps, git_responses, _ = installation
    git_responses[("ls-tree", "-r", "--name-only", NEW, "--", ".env.console", ".env", ".install.lock", "storage")] = (
        "storage/.gitkeep\n.env.console\nstorage/updates/journal.json"
    )
    with pytest.raises(updater.UpdateError, match="invalid_release"):
        updater.apply_update("0.2.0", REQUEST_ID)
    assert not steps
    assert not any(command[:2] == ["git", "switch"] for command in commands)


def test_restores_original_release_if_resumed_activation_fails(updater, installation, monkeypatch):
    _, commands, steps, git_responses, journal = installation
    git_responses[("rev-parse", "HEAD")] = NEW
    journal[updater.ROOT / "storage" / "updates" / "journal.json"] = {
        "request_id": REQUEST_ID, "version": "0.2.0", "original": OLD, "branch": "main", "target": NEW,
        "phase": "activating", "worker": WORKER.copy(), "previous_version": "0.1.0",
    }
    monkeypatch.setattr(updater, "published_target", lambda _: pytest.fail("the durable target is already pinned"))

    def activate(worker, version):
        steps.append((worker, version))
        if version == "0.2.0":
            raise updater.UpdateError("installation_failed")

    monkeypatch.setattr(updater, "activate", activate)
    with pytest.raises(updater.UpdateError, match="installation_failed"):
        updater.apply_update("0.2.0", REQUEST_ID)
    assert ["git", "switch", "--no-overwrite-ignore", "--detach", OLD] in commands
    assert steps == ["gate", (WORKER, "0.2.0"), "build", "build", (WORKER, "0.1.0")]


def test_interrupted_rollback_never_activates_target_again(updater, installation, monkeypatch):
    _, commands, steps, _, journal = installation
    journal[updater.ROOT / "storage" / "updates" / "journal.json"] = {
        "request_id": REQUEST_ID, "version": "0.2.0", "original": OLD, "branch": "main", "target": NEW,
        "phase": "rolling_back", "failure": "installation_failed",
        "worker": WORKER.copy(), "previous_version": "0.1.0",
    }
    monkeypatch.setattr(updater, "published_target", lambda _: pytest.fail("the durable target is already pinned"))
    with pytest.raises(updater.Restored, match="installation_failed"):
        updater.apply_update("0.2.0", REQUEST_ID)
    assert steps == ["gate", "build", "build", (WORKER, "0.1.0")]
    assert not any(command[-1] == NEW for command in commands)


@pytest.mark.parametrize("dsn", [
    "postgresql://emulytix_console:test@other-host:5432/emulytix",
    "postgresql://emulytix_console:test@console-postgres:5433/emulytix",
    "postgresql://emulytix_console:test@console-postgres:5432/other",
    "postgresql://different:test@console-postgres:5432/emulytix",
    "postgresql://emulytix_console:test@console-postgres:5432/emulytix?host=elsewhere",
])
def test_only_accepts_expected_local_postgresql_url(updater, dsn):
    assert not updater.local_database(dsn)
    assert updater.local_database("postgresql://emulytix_console:test@console-postgres:5432/emulytix")


@pytest.mark.skipif(os.name != "posix", reason="The host updater runs on Linux")
def test_retrying_completed_request_does_not_reapply_it(updater, monkeypatch):
    request, status = updater.exchange()
    request_id = str(uuid4())
    payload = json.dumps({"version": "0.2.0", "id": request_id})
    calls = []
    monkeypatch.setattr(updater, "apply_update", lambda version, request_id: calls.append((version, request_id)))
    request.write_text(payload, encoding="utf-8")
    updater.run()
    assert updater.read_json(status)["state"] == "installed"
    assert not request.exists()
    request.write_text(payload, encoding="utf-8")
    updater.run()
    assert calls == [("0.2.0", request_id)]
    assert not request.exists()


@pytest.mark.skipif(os.name != "posix", reason="The host updater runs on Linux")
@pytest.mark.parametrize("replacement", [False, True])
def test_recovers_inflight_journal_without_original_inbox(updater, monkeypatch, replacement):
    request, status = updater.exchange()
    request_id = str(uuid4())
    updater.refresh(status, "installing", "0.2.0", request_id)
    journal = status.parent.parent / "journal.json"
    updater.write_document(journal, {"version": "0.2.0", "request_id": request_id, "phase": "activating"}, 0o600)
    if replacement:
        request.write_text(json.dumps({"version": "0.3.0", "id": str(uuid4())}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(updater, "apply_update", lambda version, request_id: calls.append((version, request_id)))
    updater.run()
    assert calls == [("0.2.0", request_id)]
    assert updater.read_json(status)["state"] == "installed"
    assert not journal.exists()
    assert request.exists() is replacement


@pytest.mark.skipif(os.name != "posix", reason="The host updater runs on Linux")
def test_rollback_retries_keep_journal_until_terminal_status_is_durable(updater, monkeypatch):
    _, status = updater.exchange()
    journal = status.parent.parent / "journal.json"
    updater.write_document(journal, {"version": "0.2.0", "request_id": REQUEST_ID, "phase": "rolling_back"}, 0o600)

    def fail_restore(*_):
        raise updater.UpdateError("restore_failed")

    monkeypatch.setattr(updater, "apply_update", fail_restore)
    updater.run()
    assert journal.exists()
    assert updater.read_json(status)["state"] == "installing"

    def restored(*_):
        raise updater.Restored("installation_failed")

    refresh = updater.refresh

    def check_status(path, state, *result):
        if state == "failed":
            assert journal.exists()
        refresh(path, state, *result)

    monkeypatch.setattr(updater, "apply_update", restored)
    monkeypatch.setattr(updater, "refresh", check_status)
    updater.run()
    assert updater.read_json(status)["state"] == "failed"
    assert not journal.exists()
