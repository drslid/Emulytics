from __future__ import annotations

import json
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from app.android_driver import AndroidDriver, AssertionFailed, CommandTimeout, DriverError


UI = '''<?xml version="1.0"?><hierarchy><node package="com.android.chrome" resource-id="com.android.chrome:id/url_bar" text="fr.wikipedia.org/wiki/Football" content-desc="Address" class="android.widget.EditText" focused="false" bounds="[10,20][310,80]"/><node package="com.android.chrome" resource-id="search" text="football" content-desc="Search" class="android.widget.EditText" focused="true" bounds="[20,100][300,160]"/></hierarchy>'''


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    executable = tmp_path / "adb"
    log = tmp_path / "commands.jsonl"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys,time\n"
        "with open(os.environ['FAKE_ADB_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if os.environ.get('FAKE_ADB_MODE') == 'sleep':\n"
        " open(os.environ['FAKE_ADB_PID'],'w').write(str(os.getpid()))\n"
        " time.sleep(60)\n"
        "if os.environ.get('FAKE_ADB_MODE') == 'fail':\n"
        " print('offline',file=sys.stderr);sys.exit(1)\n"
        "args=sys.argv[3:]\n"
        "if os.environ.get('FAKE_ADB_MODE')=='failtap' and 'tap' in args: sys.exit(1)\n"
        "if os.environ.get('FAKE_ADB_MODE')=='badpng' and 'screencap' in args: print('not PNG');sys.exit(0)\n"
        f"if args[:2]==['shell','cat']: print({UI!r})\n"
        "elif args[:3]==['shell','uiautomator','dump']: print('UI hierarchy dumped to: '+args[-1])\n"
        "elif args[:3]==['shell','dumpsys','window']: print('mCurrentFocus=Window{0 u0 com.android.chrome/org.chromium.chrome.browser.ChromeTabbedActivity}')\n"
        "elif args[:3]==['shell','pm','path']:\n"
        " print('package:/data/app/chrome/base.apk' if os.environ.get('FAKE_PACKAGE','present')=='present' else '')\n"
        "elif args[:2]==['exec-out','screencap']: sys.stdout.buffer.write(b'\\x89PNG\\r\\n\\x1a\\nDATA')\n"
        "elif args and args[0]=='install': print('Success')\n"
        "else: print('OK')\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("FAKE_ADB_LOG", str(log))
    monkeypatch.setenv("FAKE_ADB_PID", str(tmp_path / "pid"))
    return executable, log


def driver(tmp_path, fake_adb, **kwargs):
    return AndroidDriver("emulator-5554", lambda argv, effect: None, lambda: None,
                         tmp_path / "artifacts", adb_binary=str(fake_adb[0]), **kwargs)


def commands(fake_adb):
    return [json.loads(line) for line in fake_adb[1].read_text().splitlines()]


def test_foreground_package_reads_complete_android10_window_dump(tmp_path, fake_adb, monkeypatch):
    instance = driver(tmp_path, fake_adb)
    def observed(args, **kwargs):
        if args == ["shell", "dumpsys", "window"]:
            return "mCurrentFocus=Window{abc u0 com.android.chrome/org.chromium.chrome.browser.ChromeTabbedActivity}"
        return "Window #0: Window{abc}"
    monkeypatch.setattr(instance, "command", observed)
    assert instance.foreground_package() == "com.android.chrome"


def test_every_command_targets_serial_and_is_guarded(tmp_path, fake_adb):
    guarded = []
    completed = []
    instance = AndroidDriver("emulator-5554", lambda argv, effect: guarded.append((argv, effect)),
                             lambda: None, tmp_path, adb_binary=str(fake_adb[0]),
                             after_command=lambda status, evidence: completed.append((status, evidence)))
    assert instance.command(["get-state"], effect=False).strip() == "OK"
    assert commands(fake_adb) == [["-s", "emulator-5554", "get-state"]]
    assert guarded[0][0][-3:] == ["-s", "emulator-5554", "get-state"]
    assert guarded[0][1] is False
    assert completed[0][0] == "done"


def test_failed_guard_prevents_any_process(tmp_path, fake_adb):
    def forbidden(argv, effect):
        raise RuntimeError("lease lost")
    instance = AndroidDriver("emulator-5554", forbidden, lambda: None, tmp_path,
                             adb_binary=str(fake_adb[0]))
    with pytest.raises(RuntimeError, match="lease lost"):
        instance.command(["shell", "input", "keyevent", "KEYCODE_HOME"], effect=True)
    assert not fake_adb[1].exists()


def test_timeout_neutralizes_process(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_MODE", "sleep")
    with pytest.raises(CommandTimeout):
        driver(tmp_path, fake_adb).command(["get-state"], effect=False, timeout_s=0.3)
    pid = int((tmp_path / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_cancellation_during_command_neutralizes_process(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_MODE", "sleep")
    def cancelled():
        if (tmp_path / "pid").exists():
            raise RuntimeError("cancel requested")
    instance = AndroidDriver("emulator-5554", lambda argv, effect: None, cancelled, tmp_path,
                             adb_binary=str(fake_adb[0]))
    with pytest.raises(RuntimeError, match="cancel requested"):
        instance.command(["shell", "input", "keyevent", "KEYCODE_HOME"], effect=True)
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid").read_text()), 0)


def test_selector_uses_real_unique_node_bounds(tmp_path, fake_adb):
    instance = driver(tmp_path, fake_adb)
    instance.tap_selector({"resource_id": "search"})
    assert commands(fake_adb)[-1][-4:] == ["input", "tap", "160", "130"]


@pytest.mark.parametrize("selector", [{}, {"unexpected": "search"}, {"class": "android.widget.EditText"}, {"text": "missing"}])
def test_empty_unknown_ambiguous_or_missing_selector_cannot_tap(tmp_path, fake_adb, selector):
    with pytest.raises(DriverError):
        driver(tmp_path, fake_adb).tap_selector(selector)
    assert not any("tap" in command for command in commands(fake_adb)) if fake_adb[1].exists() else True


@pytest.mark.parametrize("url", ["http://fr.wikipedia.org/", "https://wikipedia.org.evil.test/", "https://evil.test/", "file:///etc/passwd", "https://user@fr.wikipedia.org/"])
def test_navigation_rejects_unapproved_urls_without_adb(tmp_path, fake_adb, url):
    with pytest.raises(DriverError):
        driver(tmp_path, fake_adb).open_url(url)
    assert not fake_adb[1].exists()


def test_navigation_and_text_use_safe_adb_arguments(tmp_path, fake_adb):
    instance = driver(tmp_path, fake_adb)
    instance.open_url("https://fr.wikipedia.org/")
    instance.type_text("football; $(touch /tmp/should-not-exist)")
    assert commands(fake_adb)[0][-2:] == ["https://fr.wikipedia.org/", "com.android.chrome"]
    assert commands(fake_adb)[1][-1].startswith("'")
    assert not Path("/tmp/should-not-exist").exists()


def test_package_already_present_is_not_reinstalled(tmp_path, fake_adb):
    assert driver(tmp_path, fake_adb).ensure_package_installed()["installed"] is False
    assert not any("install" in command for command in commands(fake_adb))


def test_missing_package_requires_trusted_artifact(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_PACKAGE", "missing")
    with pytest.raises(DriverError, match="artifact"):
        driver(tmp_path, fake_adb).ensure_package_installed()


def test_apk_path_escape_and_wrong_digest_are_rejected(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_PACKAGE", "missing")
    apk_dir = tmp_path / "apks"
    apk_dir.mkdir()
    (apk_dir / "chrome.apk").write_bytes(b"APK")
    instance = driver(tmp_path, fake_adb, apk_dir=apk_dir)
    with pytest.raises(DriverError):
        instance.ensure_package_installed(apk="../escape.apk", sha256="0" * 64)
    with pytest.raises(DriverError, match="SHA256"):
        instance.ensure_package_installed(apk="chrome.apk", sha256="0" * 64)
    assert not any("install" in command for command in commands(fake_adb))


def test_success_requires_assertion_not_only_exit_zero(tmp_path, fake_adb):
    with pytest.raises(AssertionFailed):
        driver(tmp_path, fake_adb).execute_step({"id": "home", "action": "press_key", "args": {"keycode": "KEYCODE_HOME"},
                                               "assert": {"type": "ui", "selector": {"text": "not on screen"}}, "timeout_ms": 150})


def test_package_url_and_ui_assertions_produce_artifacts(tmp_path, fake_adb):
    evidence = driver(tmp_path, fake_adb).execute_step({
        "id": "search", "action": "press_key", "args": {"keycode": "KEYCODE_ENTER"}, "timeout_ms": 1000,
        "assert": {"type": "all", "checks": [
            {"type": "package", "value": "com.android.chrome"},
            {"type": "url", "host": "fr.wikipedia.org", "path_contains": "/wiki/Football"},
            {"type": "ui", "selector": {"text": "football"}},
        ]},
    })
    assert evidence["assertion_passed"] is True
    assert Path(evidence["screenshot"]).read_bytes().startswith(b"\x89PNG")
    assert "football" in Path(evidence["ui_xml"]).read_text()


def test_capture_timestamp_records_a_valid_png_before_the_xml_observation(tmp_path, fake_adb, monkeypatch):
    from app import android_driver

    observed = []
    captured = datetime(2026, 11, 6, 19, 30, tzinfo=timezone.utc)
    class CaptureClock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            observed.append('timestamp')
            return captured

    instance = driver(tmp_path, fake_adb)
    monkeypatch.setattr(instance, 'check_assertion', lambda assertion: None)
    def command(args, **kwargs):
        assert args == ['exec-out', 'screencap', '-p']
        observed.append('capture')
        return b'\x89PNG\r\n\x1a\nexample'
    def xml():
        observed.append('xml')
        return UI
    monkeypatch.setattr(instance, 'command', command)
    monkeypatch.setattr(instance, 'ui_xml', xml)
    monkeypatch.setattr(android_driver, 'datetime', CaptureClock, raising=False)

    evidence = instance.execute_step({'id': 'proof', 'action': 'screenshot', 'args': {},
                                      'assert': {'type': 'package', 'value': 'com.android.chrome'}})
    assert evidence['captured_at'] == captured.isoformat()
    assert observed == ['capture', 'timestamp', 'xml']


def test_adb_child_dies_when_worker_process_is_killed(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_MODE", "sleep")
    code = (
        "from pathlib import Path; from app.android_driver import AndroidDriver; "
        f"AndroidDriver('emulator-5554',lambda a,e:None,lambda:None,Path({str(tmp_path)!r}),"
        f"adb_binary={str(fake_adb[0])!r}).command(['get-state'],effect=False,timeout_s=30)"
    )
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    worker = subprocess.Popen([sys.executable, "-c", code], env=environment)
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "pid").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "pid").exists()
        child = int((tmp_path / "pid").read_text())
        worker.kill()
        worker.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            stat = Path(f"/proc/{child}/stat")
            try:
                state = stat.read_text().split()[2]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(0.05)
        else:
            pytest.fail("ADB child survived its worker")
    finally:
        if worker.poll() is None:
            worker.kill(); worker.wait(timeout=5)


def test_abort_kills_adb_even_when_poll_is_blocked(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_MODE", "sleep")
    blocked, release = threading.Event(), threading.Event()
    errors = []
    def poll():
        if (tmp_path / "pid").exists():
            blocked.set()
            release.wait(timeout=5)
    instance = AndroidDriver("emulator-5554", lambda argv, effect: None, poll, tmp_path,
                             adb_binary=str(fake_adb[0]))
    def run():
        try:
            instance.command(["get-state"], effect=False)
        except DriverError as error:
            errors.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert blocked.wait(timeout=5)
        instance.abort()
        with pytest.raises(ProcessLookupError):
            os.kill(int((tmp_path / "pid").read_text()), 0)
        with pytest.raises(DriverError, match="revoked"):
            instance.command(["get-state"], effect=False)
    finally:
        release.set(); worker.join(timeout=5)
    assert errors


def test_selector_distinguishes_focused_and_checked_booleans():
    xml = '<hierarchy><node class="android.widget.EditText" focused="false" checked="false"/><node class="android.widget.EditText" focused="true" checked="true"/></hierarchy>'
    found = AndroidDriver.find_node(xml, {"class": "android.widget.EditText", "focused": True, "checked": True})
    assert found.get("focused") == "true"


def test_preinstalled_social_application_can_be_opened_and_verified(tmp_path, fake_adb):
    result = driver(tmp_path, fake_adb).execute_step({
        'id': 'open-linkedin', 'action': 'open_app', 'args': {'package_name': 'com.linkedin.android'},
        'assert': {'type': 'package_installed', 'value': 'com.linkedin.android'},
    })
    assert result['assertion_passed']
    observed = commands(fake_adb)
    assert any('com.linkedin.android' in command and 'monkey' in command for command in observed)
    assert any(command[-3:] == ['pm', 'path', 'com.linkedin.android'] for command in observed)


@pytest.mark.parametrize('package', ['com.example;id', '-bad.option', 'com.example app', 'com.example/Activity'])
def test_application_packages_cannot_inject_shell_commands(tmp_path, fake_adb, package):
    with pytest.raises(DriverError):
        driver(tmp_path, fake_adb).execute_step({'id': 'invalid-app', 'action': 'open_app',
            'args': {'package_name': package}, 'assert': {'type': 'package_installed', 'value': package}})
    assert not fake_adb[1].exists()


def test_installation_failure_reported_on_stdout_has_a_useful_diagnostic(tmp_path):
    import sys
    executable = tmp_path / 'failing-adb'
    executable.write_text(f'#!{sys.executable}\nprint("Failure [INSTALL_FAILED_NO_MATCHING_ABIS]")\nraise SystemExit(1)\n')
    executable.chmod(0o700)
    instance = AndroidDriver('emulator-5554', lambda *args: None, lambda: None, tmp_path,
                             adb_binary=str(executable))
    with pytest.raises(DriverError, match='INSTALL_FAILED_NO_MATCHING_ABIS'):
        instance.command(['install', '-r', 'example.apk'], effect=True)


def test_absent_when_skips_action_but_still_verifies_assertion(tmp_path, fake_adb):
    result = driver(tmp_path, fake_adb).execute_step({
        "id": "optional", "action": "tap", "args": {"selector": {"resource_id": "first-run"}},
        "when": {"type": "ui", "selector": {"resource_id": "first-run"}},
        "assert": {"type": "package", "value": "com.android.chrome"},
    })
    assert result["skipped"] is True
    assert not any("tap" in command for command in commands(fake_adb))


@pytest.mark.parametrize("change", [
    {"action": "shell", "args": {"command": "id"}},
    {"args": {"keycode": "KEYCODE_HOME", "shell": "id"}},
    {"assert": {"type": "unknown"}},
    {"when": {"type": "script", "command": "id"}},
])
def test_complete_step_is_validated_before_any_adb(tmp_path, fake_adb, change):
    step = {"id": "home", "action": "press_key", "args": {"keycode": "KEYCODE_HOME"},
            "assert": {"type": "package", "value": "com.android.chrome"}, **change}
    with pytest.raises(DriverError):
        driver(tmp_path, fake_adb).execute_step(step)
    assert not fake_adb[1].exists()


def test_step_deadline_also_bounds_action_process(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_MODE", "sleep")
    started = time.monotonic()
    with pytest.raises(CommandTimeout):
        driver(tmp_path, fake_adb).execute_step({"id": "home", "action": "press_key", "args": {"keycode": "KEYCODE_HOME"},
                                               "timeout_ms": 200, "assert": {"type": "package", "value": "com.android.chrome"}})
    assert time.monotonic() - started < 2


def test_selector_fallback_does_not_repeat_an_action_that_failed_after_launch(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_MODE", "failtap")
    with pytest.raises(DriverError):
        driver(tmp_path, fake_adb).execute_step({
            "id": "search", "action": "tap", "args": {},
            "selectors": [{"resource_id": "search"}, {"text": "football"}],
            "assert": {"type": "package", "value": "com.android.chrome"},
        })
    assert sum("tap" in command for command in commands(fake_adb)) == 1


def test_clear_text_uses_observed_field_and_android10_keyevents(tmp_path, fake_adb):
    driver(tmp_path, fake_adb).type_text("football", clear=True)
    recorded = commands(fake_adb)
    assert not any("keycombination" in command for command in recorded)
    assert any(command.count("KEYCODE_DEL") == len("football") for command in recorded)


def test_a_failed_screenshot_is_not_recorded_as_image_proof(tmp_path, fake_adb, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_MODE", "badpng")
    instance = driver(tmp_path, fake_adb)
    with pytest.raises(DriverError, match="PNG"):
        instance.execute_step({"id": "proof", "action": "screenshot", "args": {},
                               "assert": {"type": "package", "value": "com.android.chrome"}})
    assert list(instance.artifact_dir.glob("*.png")) == []


@pytest.mark.parametrize("effect,expected", [(True, "uncertain"), (False, "failed")])
def test_nonzero_exit_does_not_prove_an_effect_was_absent(tmp_path, fake_adb, monkeypatch, effect, expected):
    monkeypatch.setenv("FAKE_ADB_MODE", "fail")
    completed = []
    instance = driver(tmp_path, fake_adb, after_command=lambda status, evidence: completed.append(status))
    with pytest.raises(DriverError):
        instance.command(["get-state"], effect=effect)
    assert completed == [expected]


@pytest.mark.parametrize("args", [
    {"package": "com.android.chrome", "apk": ["chrome.apk"], "sha256": ["0" * 64]},
    {"package": "com.android.chrome", "apk": "../chrome.apk", "sha256": "0" * 64},
    {"package": "com.android.chrome", "apk": "chrome.apk", "sha256": "invalid"},
])
def test_invalid_artifact_shape_is_rejected_before_any_command(tmp_path, fake_adb, args):
    with pytest.raises(DriverError):
        driver(tmp_path, fake_adb).execute_step({"id": "install", "action": "ensure_package", "args": args,
                                               "assert": {"type": "package_installed"}})
    assert not fake_adb[1].exists()
