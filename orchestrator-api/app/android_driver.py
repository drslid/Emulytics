"""Bounded, guarded Android commands and UI assertions for deterministic workflows."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4
import xml.etree.ElementTree as ET


class DriverError(RuntimeError):
    pass


class CommandTimeout(DriverError):
    pass


class AssertionFailed(DriverError):
    pass


class SelectorNotFound(DriverError):
    pass


class AndroidDriver:
    CHROME = "com.android.chrome"

    def __init__(
        self, serial: str, before_command: Callable[[list[str], bool], None],
        poll: Callable[[], None], artifact_dir: Path, adb_binary: str = "adb",
        *, lock_fd: int | None = None, apk_dir: Path | None = None,
        after_command: Callable[[str, dict], None] | None = None,
        adb_server_host: str | None = None,
    ):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", serial):
            raise DriverError("Invalid device serial")
        self.serial, self.adb_binary = serial, adb_binary
        if adb_server_host is not None and not re.fullmatch(r'emulytix-managed-[a-f0-9]{32}', adb_server_host):
            raise DriverError('Invalid managed ADB server')
        self.adb_server_host = adb_server_host
        self.before_command, self.poll = before_command, poll
        self.after_command = after_command
        self.artifact_dir, self.apk_dir = Path(artifact_dir), Path(apk_dir).resolve() if apk_dir else None
        self.lock_fd = lock_fd
        self._process: subprocess.Popen | None = None
        self._process_guard = threading.Lock()
        self._aborted = threading.Event()
        self._step_deadline: float | None = None

    @staticmethod
    def _stop_process(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)

    def abort(self) -> None:
        """May run from a watchdog while a database-backed poll is blocked."""
        self._aborted.set()
        with self._process_guard:
            process = self._process
        if process is not None:
            self._stop_process(process)

    def _check_abort(self) -> None:
        if self._aborted.is_set():
            raise DriverError("Android command authority was revoked")

    def command(self, args: list[str], *, effect: bool, timeout_s: float = 10, binary: bool = False):
        if not math.isfinite(timeout_s) or not 0.05 <= timeout_s <= 300:
            raise DriverError("Invalid command timeout")
        deadline = time.monotonic() + timeout_s
        if self._step_deadline is not None:
            deadline = min(deadline, self._step_deadline)
        server = ['-H', self.adb_server_host, '-P', '5037'] if self.adb_server_host else []
        argv = [self.adb_binary, *server, "-s", self.serial, *args]
        self._check_abort()
        self.before_command(argv, effect)
        self.poll()
        if time.monotonic() >= deadline:
            raise CommandTimeout("Android command deadline elapsed before launch")
        launcher = [sys.executable, str(Path(__file__).with_name("adb_child.py")), str(os.getpid()), *argv]
        with self._process_guard:
            self._check_abort()
            process = subprocess.Popen(
                launcher, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                pass_fds=(self.lock_fd,) if self.lock_fd is not None else (),
            )
            self._process = process
        status, evidence = "uncertain" if effect else "failed", {}
        try:
            while True:
                self._check_abort()
                self.poll()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CommandTimeout("Android command timed out")
                try:
                    output, error = process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            self._check_abort()
            self.poll()
            evidence = {"returncode": process.returncode, "output_sha256": hashlib.sha256(output).hexdigest()}
            status = "done" if process.returncode == 0 else ("uncertain" if effect else "failed")
            if process.returncode != 0:
                diagnostic = error or (output if not binary else b'')
                raise DriverError('ADB command failed: ' + (diagnostic.decode('utf-8', 'replace')[:500] or f'exit {process.returncode}'))
            return output if binary else output.decode("utf-8", "replace")
        finally:
            if process.poll() is None:
                self._stop_process(process)
            with self._process_guard:
                if self._process is process:
                    self._process = None
            if self.after_command:
                self.after_command(status, evidence)

    def ui_xml(self, *, timeout_s: float = 10) -> str:
        target = "/sdcard/emulytix-ui.xml"
        output = self.command(["shell", "uiautomator", "dump", target], effect=False, timeout_s=timeout_s)
        # Android can exit zero on an idle timeout, leaving an earlier XML file.
        if f"dumped to: {target}" not in output:
            raise DriverError("Android did not confirm a fresh UI hierarchy")
        xml = self.command(["shell", "cat", target], effect=False, timeout_s=timeout_s)
        try:
            ET.fromstring(xml)
        except ET.ParseError as exc:
            raise DriverError("Android returned invalid UI XML") from exc
        return xml

    @staticmethod
    def validate_selector(selector: dict) -> None:
        attributes = {"resource_id", "text", "content_desc", "class", "text_contains", "checked", "focused"}
        if not isinstance(selector, dict) or not selector or set(selector) - attributes:
            raise DriverError("A nonempty supported UI selector is required")
        for key, value in selector.items():
            if key in {"checked", "focused"}:
                if type(value) is not bool:
                    raise DriverError("Boolean UI selectors require a boolean")
            elif not isinstance(value, str) or not value or len(value) > 4096:
                raise DriverError("UI selectors require bounded nonempty strings")

    @classmethod
    def find_node(cls, xml: str, selector: dict) -> ET.Element:
        cls.validate_selector(selector)
        attributes = {"resource_id": "resource-id", "text": "text", "content_desc": "content-desc", "class": "class", "checked": "checked", "focused": "focused"}
        matches = []
        for node in ET.fromstring(xml).iter("node"):
            if all((
                value in node.get("text", "") if key == "text_contains"
                else node.get(attributes[key]) == (str(value).lower() if type(value) is bool else value)
            ) for key, value in selector.items()):
                matches.append(node)
        if not matches:
            raise SelectorNotFound("UI selector matched no elements")
        if len(matches) != 1:
            raise DriverError(f"UI selector matched {len(matches)} elements; exactly one is required")
        return matches[0]

    def tap_selector(self, selector: dict) -> None:
        node = self.find_node(self.ui_xml(), selector)
        self._tap_node(node)

    def _tap_node(self, node: ET.Element) -> None:
        bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
        if bounds is None:
            raise DriverError("UI element has invalid bounds")
        x1, y1, x2, y2 = map(int, bounds.groups())
        if not 0 <= x1 < x2 <= 100_000 or not 0 <= y1 < y2 <= 100_000:
            raise DriverError("UI element has empty or invalid bounds")
        self.command(["shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)], effect=True)

    def press_key(self, keycode: str) -> None:
        if not isinstance(keycode, str) or not re.fullmatch(r"KEYCODE_[A-Z0-9_]{1,60}", keycode):
            raise DriverError("Invalid Android key code")
        self.command(["shell", "input", "keyevent", keycode], effect=True)

    def type_text(self, text: str, *, clear: bool = False) -> None:
        if not isinstance(text, str) or not text or len(text) > 16_384 or not text.isascii() or any(ord(c) < 32 for c in text) or "%s" in text:
            raise DriverError("This input method requires printable ASCII text without literal %s")
        if clear:
            focused = self.find_node(self.ui_xml(), {"class": "android.widget.EditText", "focused": True})
            length = len(focused.get("text", ""))
            if length > 16_384:
                raise DriverError("Focused input is too large to clear safely")
            self.press_key("KEYCODE_MOVE_END")
            if length:
                self.command(["shell", "input", "keyevent", *(["KEYCODE_DEL"] * length)], effect=True)
        self.command(["shell", "input", "text", shlex.quote(text.replace(" ", "%s"))], effect=True)

    @staticmethod
    def _wikipedia_url(url: str) -> None:
        if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 for c in url) or "\\" in url:
            raise DriverError("Only HTTPS Wikipedia navigation is allowed")
        try:
            parsed = urlparse(url)
            allowed = parsed.scheme == "https" and not parsed.username and not parsed.password and parsed.port in (None, 443) and (
                parsed.hostname == "wikipedia.org" or (parsed.hostname or "").endswith(".wikipedia.org"))
        except ValueError:
            allowed = False
        if not allowed:
            raise DriverError("Only HTTPS Wikipedia navigation is allowed")

    @classmethod
    def validate_assertion(cls, assertion: dict, depth: int = 0) -> None:
        if not isinstance(assertion, dict) or depth > 4:
            raise DriverError("Invalid or excessively nested assertion")
        kind = assertion.get("type")
        if kind == "all":
            if set(assertion) != {"type", "checks"} or not isinstance(assertion["checks"], list) or not 1 <= len(assertion["checks"]) <= 10:
                raise DriverError("An all assertion requires bounded checks")
            for check in assertion["checks"]:
                cls.validate_assertion(check, depth + 1)
        elif kind == "ui":
            if set(assertion) != {"type", "selector"}:
                raise DriverError("UI assertions require only type and selector")
            cls.validate_selector(assertion["selector"])
        elif kind == "package":
            if set(assertion) != {"type", "value"} or not isinstance(assertion["value"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{1,199}", assertion["value"]):
                raise DriverError("Invalid package assertion")
        elif kind == "package_installed":
            package = assertion.get('value', cls.CHROME)
            if (set(assertion) - {'type', 'value'} or not isinstance(package, str)
                    or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+', package) or len(package) > 200):
                raise DriverError('Invalid installed package assertion')
        elif kind == "url":
            if set(assertion) - {"type", "host", "path_contains"} or not isinstance(assertion.get("host"), str):
                raise DriverError("Invalid URL assertion")
            cls._wikipedia_url("https://" + assertion["host"] + "/")
            if not isinstance(assertion.get("path_contains", ""), str) or len(assertion.get("path_contains", "")) > 2048:
                raise DriverError("Invalid URL path assertion")
        else:
            raise DriverError("Unsupported workflow assertion")

    @classmethod
    def validate_step(cls, step: dict) -> None:
        allowed = {"id", "action", "args", "selectors", "timeout_ms", "assert", "non_idempotent", "recovery_budget", "recovery_actions", "verify_after_crash", "when"}
        if not isinstance(step, dict) or set(step) - allowed or not isinstance(step.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", step["id"]):
            raise DriverError("Invalid executable step")
        cls.validate_assertion(step.get("assert"))
        if step.get("when") is not None:
            if not isinstance(step["when"], dict) or set(step["when"]) != {"type", "selector"} or step["when"]["type"] != "ui":
                raise DriverError("Only UI conditions are supported")
            cls.validate_selector(step["when"]["selector"])
        selectors = step.get("selectors", [])
        if not isinstance(selectors, list) or len(selectors) > 8:
            raise DriverError("Invalid selector alternatives")
        for selector in selectors:
            cls.validate_selector(selector)
        timeout = step.get("timeout_ms", 10_000)
        if type(timeout) is not int or not 100 <= timeout <= 300_000:
            raise DriverError("Invalid step timeout")
        action, args = step.get("action"), step.get("args", {})
        fields = {"press_key": {"keycode"}, "open_app": {"package_name"}, "tap": {"selector", "x", "y"},
                  "swipe": {"x1", "y1", "x2", "y2", "duration_ms"}, "type_text": {"text", "clear"},
                  "screenshot": set(), "ensure_package": {"package", "apk", "sha256"}, "open_url": {"url"},
                  "open_settings": {"section"}, "read_device_info": {"field"}}
        if not isinstance(action, str) or action not in fields or not isinstance(args, dict) or set(args) - fields[action]:
            raise DriverError("Unsupported action or action arguments")
        if action == "press_key" and (not isinstance(args.get("keycode"), str) or not re.fullmatch(r"KEYCODE_[A-Z0-9_]{1,60}", args["keycode"])):
            raise DriverError("Invalid Android key code")
        if action == 'open_app' and (not isinstance(args.get('package_name'), str)
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+', args['package_name'])
                or len(args['package_name']) > 200):
            raise DriverError('Invalid application package')
        if action == "open_url":
            cls._wikipedia_url(args.get("url"))
        if action == "open_settings" and (set(args) != {"section"} or not isinstance(args["section"], str) or args["section"] not in {"main", "about"}):
            raise DriverError("Unsupported Android settings section")
        if action == "read_device_info" and (set(args) != {"field"} or args["field"] != "android_version"):
            raise DriverError("Unsupported Android device information")
        if action == "type_text":
            text = args.get("text")
            if not isinstance(text, str) or not text or len(text) > 16_384 or not text.isascii() or any(ord(c) < 32 for c in text) or "%s" in text or type(args.get("clear", False)) is not bool:
                raise DriverError("Invalid text input arguments")
        if action == "tap":
            if "selector" in args:
                cls.validate_selector(args["selector"])
            elif not selectors and not all(type(args.get(key)) is int and 0 <= args[key] <= 100_000 for key in ("x", "y")):
                raise DriverError("Tap requires a selector or bounded coordinates")
        if action == "swipe" and (not all(type(args.get(key)) is int and 0 <= args[key] <= 100_000 for key in ("x1", "y1", "x2", "y2")) or type(args.get("duration_ms", 300)) is not int or not 1 <= args.get("duration_ms", 300) <= 10_000):
            raise DriverError("Swipe requires bounded coordinates and duration")
        if action == "ensure_package" and (args.get("package", cls.CHROME) != cls.CHROME or bool(args.get("apk")) != bool(args.get("sha256"))):
            raise DriverError("Invalid Chrome artifact arguments")
        if action == "ensure_package" and args.get("apk") is not None:
            artifact, digest = args["apk"], args.get("sha256")
            if not isinstance(artifact, str) or not artifact or len(artifact) > 256 or Path(artifact).is_absolute() or ".." in Path(artifact).parts:
                raise DriverError("Invalid relative APK artifact")
            if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                raise DriverError("Invalid APK SHA256")

    def open_url(self, url: str) -> None:
        self._wikipedia_url(url)
        self.command(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", shlex.quote(url), self.CHROME], effect=True)

    def ensure_package_installed(self, package: str = CHROME, *, apk: str | None = None, sha256: str | None = None) -> dict:
        if package != self.CHROME:
            raise DriverError("Only the configured Chrome package may be provisioned")
        if self.command(["shell", "pm", "path", package], effect=False).strip().startswith("package:"):
            return {"package": package, "installed": False}
        if not self.apk_dir or not apk or not sha256:
            raise DriverError("A verified Chrome artifact is required")
        artifact = (self.apk_dir / apk).resolve()
        if Path(apk).is_absolute() or not artifact.is_relative_to(self.apk_dir) or not artifact.is_file():
            raise DriverError("APK artifact must remain inside the configured directory")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", sha256) or hashlib.sha256(artifact.read_bytes()).hexdigest() != sha256.lower():
            raise DriverError("APK SHA256 mismatch")
        self.command(["install", "-r", str(artifact)], effect=True, timeout_s=120)
        if not self.command(["shell", "pm", "path", package], effect=False).strip().startswith("package:"):
            raise DriverError("Chrome package missing after installation")
        return {"package": package, "installed": True, "sha256": sha256.lower()}

    def foreground_package(self) -> str:
        window = self.command(["shell", "dumpsys", "window"], effect=False)
        for line in window.splitlines():
            if "mCurrentFocus=" in line or "mFocusedApp=" in line:
                match = re.search(r"\s([A-Za-z][A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+", line)
                if match:
                    return match.group(1)
        raise DriverError("Foreground package could not be observed")

    def read_android_version(self) -> dict:
        release = self.command(["shell", "getprop", "ro.build.version.release"], effect=False).rstrip("\r\n")
        sdk = self.command(["shell", "getprop", "ro.build.version.sdk"], effect=False).rstrip("\r\n")
        # Android documents RELEASE as an opaque label, not necessarily a number.
        if not release.isprintable():
            raise DriverError("Android release could not be read reliably")
        release = release.strip()
        if not release or len(release) > 64 or release.casefold() == "unknown":
            raise DriverError("Android release could not be read reliably")
        if not re.fullmatch(r"[1-9][0-9]{0,4}", sdk) or int(sdk) > 10_000:
            raise DriverError("Android SDK version could not be read reliably")
        return {"type": "android_version", "value": release, "sdk_int": int(sdk),
                "source": "android_system_properties"}

    def check_assertion(self, assertion: dict) -> None:
        kind = assertion.get("type")
        if kind == "all":
            checks = assertion.get("checks")
            if not isinstance(checks, list) or not 1 <= len(checks) <= 10:
                raise DriverError("An all assertion requires bounded checks")
            for check in checks:
                self.check_assertion(check)
        elif kind == "package":
            if self.foreground_package() != assertion.get("value"):
                raise AssertionFailed("Expected package is not in the foreground")
        elif kind == "ui":
            self.find_node(self.ui_xml(), assertion.get("selector", {}))
        elif kind == "url":
            if self.foreground_package() != self.CHROME:
                raise AssertionFailed("URL proof requires Chrome in the foreground")
            node = self.find_node(self.ui_xml(), {"resource_id": self.CHROME + ":id/url_bar"})
            value = node.get("text", "")
            parsed = urlparse(value if "://" in value else "https://" + value)
            if parsed.hostname != assertion.get("host") or assertion.get("path_contains", "") not in parsed.path:
                raise AssertionFailed("Chrome URL does not match the expected host/path")
        elif kind == "package_installed":
            self.validate_assertion(assertion)
            if not self.command(['shell', 'pm', 'path', assertion.get('value', self.CHROME)], effect=False).strip().startswith('package:'):
                raise AssertionFailed('Expected application is not installed')
        else:
            raise DriverError("Unsupported workflow assertion")

    def execute_step(self, step: dict) -> dict:
        self.validate_step(step)
        self._step_deadline = time.monotonic() + step.get("timeout_ms", 10_000) / 1000
        try:
            return self._execute_step(step)
        finally:
            self._step_deadline = None

    def _execute_step(self, step: dict) -> dict:
        action, args = step.get("action"), step.get("args", {})
        timeout_s = step.get("timeout_ms", 10_000) / 1000
        if not 0.1 <= timeout_s <= 300:
            raise DriverError("Invalid step timeout")
        skipped = False
        result = None
        if step.get("when"):
            try:
                self.find_node(self.ui_xml(), step["when"]["selector"])
            except SelectorNotFound:
                skipped = True
        if skipped:
            pass
        elif action == "press_key":
            self.press_key(args.get("keycode"))
        elif action == "tap":
            selectors = [args["selector"]] if args.get("selector") else step.get("selectors", [])
            if selectors:
                self._tap_alternative(selectors)
            else:
                coordinates = [args.get("x"), args.get("y")]
                if not all(type(value) is int and 0 <= value <= 100_000 for value in coordinates):
                    raise DriverError("Tap requires a selector or bounded coordinates")
                self.command(["shell", "input", "tap", *map(str, coordinates)], effect=True)
        elif action == "swipe":
            coordinates = [args.get(key) for key in ("x1", "y1", "x2", "y2")]
            duration = args.get("duration_ms", 300)
            if not all(type(value) is int and 0 <= value <= 100_000 for value in coordinates) or type(duration) is not int or not 1 <= duration <= 10_000:
                raise DriverError("Swipe requires bounded coordinates and duration")
            self.command(["shell", "input", "swipe", *map(str, coordinates), str(duration)], effect=True)
        elif action == "type_text":
            if step.get("selectors"):
                self._tap_alternative(step["selectors"])
            self.type_text(args.get("text"), clear=args.get("clear", False))
        elif action == "open_url":
            self.open_url(args.get("url", ""))
        elif action == "open_app":
            self.command(['shell', 'monkey', '-p', args['package_name'], '-c', 'android.intent.category.LAUNCHER', '1'], effect=True)
        elif action == "open_settings":
            intent = {"main": "android.settings.SETTINGS", "about": "android.settings.DEVICE_INFO_SETTINGS"}[args["section"]]
            self.command(["shell", "am", "start", "-W", "-a", intent, "-p", "com.android.settings"], effect=True)
        elif action == "read_device_info":
            result = self.read_android_version()
        elif action == "ensure_package":
            self.ensure_package_installed(**args)
        elif action != "screenshot":
            raise DriverError("Unsupported Android workflow action")
        assertion = step.get("assert")
        if not isinstance(assertion, dict):
            raise DriverError("Every executable step requires an assertion")
        deadline = self._step_deadline
        while True:
            self._check_abort()
            self.poll()
            try:
                self.check_assertion(assertion)
                break
            except DriverError as exc:
                if time.monotonic() >= deadline:
                    raise AssertionFailed("Step assertion was not satisfied before its deadline") from exc
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        stem = uuid4().hex
        screenshot = self.artifact_dir / (stem + ".png")
        image = self.command(["exec-out", "screencap", "-p"], effect=False, binary=True)
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise DriverError("Android screenshot did not contain a PNG image")
        captured_at = datetime.now(timezone.utc).isoformat()
        screenshot.write_bytes(image)
        xml_path = self.artifact_dir / (stem + ".xml")
        xml_path.write_text(self.ui_xml())
        evidence = {"assertion_passed": True, "skipped": skipped, "captured_at": captured_at,
                    "screenshot": str(screenshot), "ui_xml": str(xml_path),
                    "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()}
        if result is not None:
            evidence["result"] = result
        return evidence

    def _tap_alternative(self, selectors: list[dict]) -> None:
        xml = self.ui_xml()
        failure = None
        for selector in selectors:
            try:
                node = self.find_node(xml, selector)
            except DriverError as exc:
                failure = exc
                continue
            self._tap_node(node)
            return
        raise failure
