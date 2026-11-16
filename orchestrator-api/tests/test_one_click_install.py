"""Installer behavior without connecting to Docker or to the local console."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def installer(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "scripts/install.py"
    spec = importlib.util.spec_from_file_location("one_click_install_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.sys, "argv", ["install.py"])
    module.original_preflight = module.preflight
    monkeypatch.setattr(module, "preflight", lambda **options: None)
    monkeypatch.setattr(module, "wait_for_console", lambda: None)
    for name in ("EMULYTIX_MANAGED_IMAGE", "EMULYTIX_BENCH_IMAGE"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def execute(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module, "run", execute)
    monkeypatch.setattr(module.subprocess, "run", lambda command, **options: subprocess.CompletedProcess(command, 0))
    return module, calls


def test_check_does_not_write_or_start_services(installer, monkeypatch):
    module, calls = installer
    monkeypatch.setattr(module.sys, "argv", ["install.py", "--check"])
    module.main()
    assert not list(module.ROOT.iterdir())
    assert not calls


@pytest.mark.parametrize("total,available,allow_low_memory,error", [
    (8 * 1024**3, 4 * 1024**3, False, None),
    (8180621312, 6 * 1024**3, False, "7.62 Gio détectés"),
    (8180621312, 6 * 1024**3, True, None),
    (8 * 1024**3, 4 * 1024**3 - 1024, False, "Libérez au moins 4 Gio"),
    (8180621312, 4 * 1024**3 - 1024, True, "Libérez au moins 4 Gio"),
])
def test_memory_override_keeps_the_available_memory_requirement(
    installer, monkeypatch, capsys, total, available, allow_low_memory, error,
):
    module, _ = installer
    monkeypatch.setattr(module.os, "sysconf", lambda name: 4096 if name == "SC_PAGE_SIZE" else total // 4096)
    monkeypatch.setattr(module.Path, "read_text", lambda self: f"MemAvailable: {available // 1024} kB\n")
    if error:
        with pytest.raises(RuntimeError, match=error):
            module.check_memory(allow_low_memory=allow_low_memory)
    else:
        module.check_memory(allow_low_memory=allow_low_memory)
    assert ("capacité réduite acceptée" in capsys.readouterr().out) == (allow_low_memory and total < module.MIN_MEMORY)


def test_low_memory_check_is_explicit_and_does_not_start_services(installer, monkeypatch):
    module, calls = installer
    checked = []
    monkeypatch.setattr(module, "preflight", lambda **options: checked.append(options))
    monkeypatch.setattr(module.sys, "argv", ["install.py", "--check", "--allow-low-memory"])
    module.main()
    assert checked == [{"allow_low_memory": True}]
    assert not list(module.ROOT.iterdir())
    assert not calls


def test_missing_image_requires_explicit_license_acceptance_before_mutations(installer, monkeypatch):
    module, calls = installer
    monkeypatch.setattr(module.subprocess, "run", lambda command, **options: subprocess.CompletedProcess(command, 1))
    with pytest.raises(RuntimeError, match="accept-android-license"):
        module.main()
    assert not list(module.ROOT.iterdir())
    assert not calls


def test_fresh_install_builds_pinned_runtime_then_starts_console_and_worker(installer, monkeypatch, capsys):
    module, calls = installer
    monkeypatch.setattr(module.sys, "argv", ["install.py", "--accept-android-license"])
    monkeypatch.setattr(module.subprocess, "run", lambda command, **options: subprocess.CompletedProcess(command, 1))
    module.main()
    environment = module.ROOT / ".env.console"
    first = environment.read_bytes()
    values = dict(line.split("=", 1) for line in environment.read_text().splitlines())
    assert environment.stat().st_mode & 0o777 == 0o600
    assert len(values["EMULYTIX_CONTROL_TOKEN"]) >= 32
    assert len(values["EMULYTIX_AUTH_KEY"]) >= 40
    assert values["EMULYTIX_POSTGRES_PASSWORD"] not in capsys.readouterr().out
    assert calls[0][0][:2] == ["docker", "build"]
    assert "ANDROID_SDK_LICENSE_ACCEPTED=true" in calls[0][0]
    assert calls[1][0][-1] == "-accel-check"
    assert calls[2][0] == ["bash", "scripts/start-console.sh"]
    assert calls[3][0] == ["bash", "scripts/start-console-android.sh"]
    assert calls[3][1]["env"]["EMULYTIX_MANAGED_IMAGE"] == module.RUNTIME_IMAGE
    monkeypatch.setattr(module.subprocess, "run", lambda command, **options: subprocess.CompletedProcess(command, 0))
    calls.clear()
    module.main()
    assert environment.read_bytes() == first
    assert all(command[:2] != ["docker", "build"] for command, _ in calls)


def test_existing_custom_images_and_secrets_are_preserved(installer):
    module, calls = installer
    environment = module.ROOT / ".env.console"
    original = b"EMULYTIX_AUTH_KEY=untouched\nEMULYTIX_MANAGED_IMAGE='local/custom:2'\nEMULYTIX_BENCH_IMAGE=local/bench:3\n"
    environment.write_bytes(original)
    environment.chmod(0o600)
    module.main()
    assert environment.read_bytes() == original
    options = calls[-1][1]["env"]
    assert options["EMULYTIX_MANAGED_IMAGE"] == "local/custom:2"
    assert options["EMULYTIX_BENCH_IMAGE"] == "local/bench:3"
    assert len(calls) == 3


def test_missing_custom_image_is_not_replaced_with_the_default(installer, monkeypatch):
    module, calls = installer
    monkeypatch.setenv("EMULYTIX_MANAGED_IMAGE", "local/custom:2")
    monkeypatch.setattr(module.subprocess, "run", lambda command, **options: subprocess.CompletedProcess(command, 1))
    with pytest.raises(RuntimeError, match="personnalisée"):
        module.main()
    assert not calls
    assert not (module.ROOT / ".env.console").exists()


@pytest.mark.parametrize('value', ['--help', '', 'repo/image:2\nOTHER=value'])
def test_image_overrides_cannot_be_docker_options_or_multiline_values(installer, monkeypatch, value):
    module, calls = installer
    monkeypatch.setenv('EMULYTIX_BENCH_IMAGE', value)
    with pytest.raises(RuntimeError, match='invalide'):
        module.main()
    assert not calls


def test_badly_quoted_image_is_reported_without_overwriting_configuration(installer):
    module, calls = installer
    environment = module.ROOT / '.env.console'
    original = "EMULYTIX_BENCH_IMAGE='unfinished\n"
    environment.write_text(original)
    environment.chmod(0o600)
    with pytest.raises(RuntimeError, match='invalide'):
        module.main()
    assert environment.read_text() == original
    assert not calls


def test_remote_docker_is_refused_before_hardware_checks(installer, monkeypatch):
    module, calls = installer
    monkeypatch.setattr(module.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(module.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/bin/' + name)
    monkeypatch.setenv('DOCKER_HOST', 'ssh://remote-example')
    monkeypatch.setattr(module, 'run', lambda command, **options: subprocess.CompletedProcess(command, 0, stdout=json.dumps({'OSType': 'linux', 'Architecture': 'x86_64'})))
    with pytest.raises(RuntimeError, match='moteur Docker local'):
        module.original_preflight()


def test_missing_docker_service_explains_how_to_recover(installer, monkeypatch):
    module, calls = installer
    monkeypatch.setattr(module.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(module.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/bin/' + name)

    def unavailable(command, **options):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(module, 'run', unavailable)
    with pytest.raises(RuntimeError, match='Démarrez Docker'):
        module.original_preflight()


@pytest.mark.parametrize("mode", [0o644, 0o666])
def test_existing_environment_must_remain_private(installer, mode):
    module, calls = installer
    environment = module.ROOT / ".env.console"
    environment.write_text("private-secret")
    environment.chmod(mode)
    with pytest.raises(RuntimeError, match="privé"):
        module.main()
    assert not calls
    assert environment.read_text() == "private-secret"


def test_environment_symlink_is_never_followed(installer):
    module, calls = installer
    outside = module.ROOT / "other"
    outside.write_text("untouched")
    (module.ROOT / ".env.console").symlink_to(outside)
    with pytest.raises(OSError):
        module.main()
    assert not calls
    assert outside.read_text() == "untouched"


def test_failed_service_start_can_be_retried_without_rotating_secrets(installer, monkeypatch):
    module, calls = installer

    def fail(command, **options):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(module, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        module.main()
    original = (module.ROOT / ".env.console").read_bytes()
    monkeypatch.setattr(module, "run", lambda *args, **options: None)
    module.main()
    assert (module.ROOT / ".env.console").read_bytes() == original


def test_second_install_cannot_run_concurrently(installer):
    module, calls = installer
    with (module.ROOT / ".install.lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="déjà en cours"):
            module.main()
    assert not calls
    assert not (module.ROOT / ".env.console").exists()


def test_sdk_archive_manifest_has_exact_https_urls_and_sha256_hashes():
    root = Path(__file__).resolve().parents[2]
    rows = [line.split() for line in (root / "android-runtime/sdk-packages.sha256").read_text().splitlines() if line and not line.startswith("#")]
    assert len(rows) == 4
    assert len({row[1] for row in rows}) == 4
    for digest, archive in rows:
        assert len(bytes.fromhex(digest)) == 32
        assert archive.startswith("https://dl.google.com/android/repository/")
        assert archive.endswith(".zip")
