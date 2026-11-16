#!/usr/bin/env python3
"""Apply a published Emulytics release from the local installation host."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/drslid/Emulytics.git"
RELEASE_API = "https://api.github.com/repos/drslid/Emulytics"
VERSION = re.compile(r"(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}")
COMMIT = re.compile(r"[a-f0-9]{40}")
UNIT = "emulytics-update"
CORE = ("console-api", "console-go-api", "console-scheduler", "validation-ui", "console-migrate")
LOCK = 4993732774799699781
PSQL = ("exec", "-T", "console-postgres", "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
        "-h", "/var/run/postgresql", "-p", "5432", "-U", "emulytix_console", "-d", "emulytix")
WORKER_SETTINGS = {"EMULYTIX_HOST_ID", "EMULYTIX_LEASE_TTL", "ADB_SERVER_SOCKET",
                   "EMULYTIX_BENCH_NETWORK", "EMULYTIX_MANAGED_IMAGE"}
CHECK_IDLE = """
import os
import sys
from app.execution_store import ACTIVE, ExecutionStore
with ExecutionStore(os.environ['EMULYTIX_DATABASE_URL']).connect() as connection:
    if len(sys.argv) > 1 and connection.execute(
        'SELECT pg_try_advisory_xact_lock_shared(%s) AS acquired', (int(sys.argv[1]),)
    ).fetchone()['acquired']:
        print('unsupported_database')
        raise SystemExit
    active = connection.execute(
        'SELECT 1 FROM executions WHERE status = ANY(%s) LIMIT 1', (list(ACTIVE),)
    ).fetchone()
print('busy' if active else 'idle')
"""
CHECK_API = """
import os
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=3) as response:
    if response.status != 200:
        raise SystemExit(1)
print(os.environ['EMULYTIX_VERSION'])
"""


class UpdateError(RuntimeError):
    pass


class Restored(UpdateError):
    """Activation failed and the previous stack is running again."""


def command(args, *, timeout=30, capture=False, check=True, environment=None):
    return subprocess.run(
        args, cwd=ROOT, env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(environment or {})},
        timeout=timeout, check=check, text=True, capture_output=capture,
    )


def git(*args):
    return command(["git", *args], capture=True).stdout.strip()


def exchange():
    storage = ROOT / "storage"
    exchange_root = storage / "updates"
    for directory in (storage, exchange_root, exchange_root / "requests", exchange_root / "status"):
        if directory.is_symlink():
            raise UpdateError("unsafe_exchange")
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.stat().st_uid != os.getuid():
            raise UpdateError("unsafe_exchange")
    return exchange_root / "requests" / "request.json", exchange_root / "status" / "status.json"


def read_json(path, limit=1024):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Invalid update exchange file")
        content = source.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Update exchange file is too large")
        document = json.loads(content)
    if not isinstance(document, dict):
        raise ValueError("Invalid update exchange document")
    return document


def write_document(path, value, mode):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".status-", delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(value, output)
            output.flush()
            os.fchmod(output.fileno(), mode)
            os.fsync(output.fileno())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


def refresh(path, state, version=None, request_id=None, error=None):
    result = dict(state=state, version=version, request_id=request_id, updated_at=int(time.time()), error=error)
    write_document(path, result, 0o644)


def valid_version(value):
    return isinstance(value, str) and VERSION.fullmatch(value) is not None


def valid_request_id(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
        return parsed.version == 4 and str(parsed) == value
    except ValueError:
        return False


def requested_update(path):
    request = read_json(path)
    request_id = request.get("id")
    if set(request) != {"version", "id"} or not valid_version(request.get("version")) or not valid_request_id(request_id):
        raise ValueError("Invalid update request")
    return request["version"], request_id


def github_json(endpoint):
    request = Request(RELEASE_API + endpoint, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "Emulytics host updater",
    })
    try:
        with urlopen(request, timeout=12) as response:
            data = response.read(262145)
        if len(data) <= 262144:
            document = json.loads(data)
            if isinstance(document, dict):
                return document
    except (OSError, ValueError):
        pass
    raise UpdateError("release_unavailable")


def published_target(version):
    tag = "v" + version
    release = github_json("/releases/latest")
    if release.get("tag_name") != tag or release.get("draft") is not False or release.get("prerelease") is not False:
        raise UpdateError("version_unavailable")
    release_commit = release.get("target_commitish")
    if not isinstance(release_commit, str) or not COMMIT.fullmatch(release_commit):
        raise UpdateError("invalid_release")
    reference = github_json("/git/ref/tags/" + tag)
    expected = reference.get("object")
    if (reference.get("ref") != "refs/tags/" + tag or not isinstance(expected, dict)
            or expected.get("type") not in {"commit", "tag"} or not COMMIT.fullmatch(str(expected.get("sha", "")))):
        raise UpdateError("invalid_release")
    command(["git", "fetch", "--no-tags", REPOSITORY, "refs/tags/" + tag], timeout=90)
    if git("rev-parse", "FETCH_HEAD") != expected["sha"]:
        raise UpdateError("invalid_release")
    candidate = git("rev-parse", expected["sha"] + "^{commit}")
    if candidate != release_commit or git("show", candidate + ":VERSION") != version:
        raise UpdateError("invalid_release")
    return candidate


def compose_prefix(source, worker):
    prefix = ["docker", "compose", "--env-file", str(ROOT / ".env.console"), "-p", "emulytix-preview",
              "-f", str(source / "docker-compose.preview.yml")]
    if worker:
        prefix += ["-f", str(source / "docker-compose.console-worker.yml"), "--profile", "worker"]
    return prefix


def compose(*args, source=None, worker=False, **options):
    return command(compose_prefix(source or ROOT, worker) + list(args), **options)


def installation_containers(service, running=False):
    args = ["docker", "ps"] + ([] if running else ["--all"])
    ids = command(args + [
        "--filter", "label=com.docker.compose.project=emulytix-preview",
        "--filter", "label=com.docker.compose.service=" + service, "--format", "{{.ID}}",
    ], capture=True).stdout.split()
    for container in ids:
        directory = command(["docker", "inspect", "--format",
                             '{{index .Config.Labels "com.docker.compose.project.working_dir"}}', container],
                            capture=True).stdout.strip()
        if not directory or Path(directory).resolve() != ROOT:
            raise UpdateError("different_installation")
    return ids


def local_worker():
    workers = installation_containers("console-worker", running=True)
    if not workers:
        return None
    if len(workers) != 1:
        raise UpdateError("different_installation")
    return {name: value for name, value in container_environment(workers[0]).items() if name in WORKER_SETTINGS}


def container_environment(container):
    settings = json.loads(command(["docker", "inspect", "--format", "{{json .Config.Env}}", container], capture=True).stdout)
    if not isinstance(settings, list) or any(not isinstance(item, str) for item in settings):
        raise UpdateError("different_installation")
    environment = {}
    for assignment in settings:
        name, separator, value = assignment.partition("=")
        if separator:
            environment[name] = value
    return environment


def local_database(dsn):
    if not isinstance(dsn, str) or any(ord(character) <= 32 or character in "?#" for character in dsn):
        return False
    try:
        connection = urlsplit(dsn)
        credentials, _, authority = connection.netloc.rpartition("@")
        return (connection.scheme in {"postgres", "postgresql"}
                and authority == "console-postgres:5432"
                and "@" not in credentials
                and connection.username == "emulytix_console"
                and connection.path == "/emulytix")
    except ValueError:
        return False


def require_local_database(source=None):
    configuration = json.loads(compose("config", "--format", "json", source=source, capture=True).stdout)
    services = configuration.get("services", {})
    api = services.get("console-api", {}).get("environment", {})
    postgres = services.get("console-postgres", {}).get("environment", {})
    if not local_database(api.get("EMULYTIX_DATABASE_URL")) or (
        postgres.get("POSTGRES_DB"), postgres.get("POSTGRES_USER")
    ) != ("emulytix", "emulytix_console"):
        raise UpdateError("unsupported_database")


@contextmanager
def deployment_lock():
    process = subprocess.Popen(compose_prefix(ROOT, False) + list(PSQL), cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

    def held():
        if process.poll() is not None:
            raise UpdateError("restore_failed")

    try:
        try:
            process.stdin.write(f"SELECT pg_try_advisory_lock({LOCK});\n".encode())
        except BrokenPipeError:
            raise UpdateError("update_lock_unavailable") from None
        answer = b""
        deadline = time.monotonic() + 12
        with selectors.DefaultSelector() as stream:
            stream.register(process.stdout, selectors.EVENT_READ)
            while not answer.endswith(b"\n"):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not stream.select(remaining):
                    raise UpdateError("update_lock_unavailable")
                fragment = os.read(process.stdout.fileno(), 16)
                if not fragment or len(answer) + len(fragment) > 16:
                    raise UpdateError("update_lock_unavailable")
                answer += fragment
        if answer != b"t\n":
            raise UpdateError("update_busy" if answer == b"f\n" else "update_lock_unavailable")
        yield held
        held()
    finally:
        process.stdin.close()
        process.stdout.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def ensure_idle(*, verify_gate=False):
    containers = installation_containers("console-api", running=True)
    if containers:
        if len(containers) != 1:
            raise UpdateError("different_installation")
        container = containers[0]
        if not local_database(container_environment(container).get("EMULYTIX_DATABASE_URL")):
            raise UpdateError("unsupported_database")
        check = ["docker", "exec", container, "python", "-c", CHECK_IDLE]
        if verify_gate:
            check.append(str(LOCK))
        running = command(check, capture=True).stdout.strip()
        if running == "unsupported_database":
            raise UpdateError("unsupported_database")
        if running != "idle":
            raise UpdateError("active_runs")
    else:
        # The API may be stopped during recovery. Keep the existing worker's leases safe.
        output = compose(*PSQL, "-c",
                         "SELECT EXISTS(SELECT 1 FROM executions WHERE status IN "
                         "('leased','running','recovering','verifying_state','waiting_auth'));",
                         capture=True).stdout.strip()
        if output != "f":
            raise UpdateError("active_runs")


def activate(worker, version):
    from install import wait_for_console

    command(["bash", "scripts/start-console.sh"], timeout=1800, environment={"EMULYTIX_UPDATING": "1"})
    if worker is not None:
        compose("up", "-d", "--wait", "--no-deps", "--no-build", "console-worker",
                worker=True, timeout=900, environment=worker)
    wait_for_console()
    observed = compose("exec", "-T", "console-api", "python", "-c", CHECK_API, capture=True).stdout.strip()
    if observed != version:
        raise UpdateError("installation_failed")


def verify_data_paths(revision):
    files = git("ls-tree", "-r", "--name-only", revision, "--", ".env.console", ".env", ".install.lock", "storage")
    if set(files.splitlines()) - {"storage/.gitkeep"}:
        raise UpdateError("invalid_release")


def setup_journal(path, version, request_id, head):
    try:
        journal = read_json(path, 4096)
    except FileNotFoundError:
        journal = None
    except (OSError, ValueError):
        raise UpdateError("restore_failed") from None
    if journal is not None:
        worker = journal.get("worker")
        if (journal.get("request_id") != request_id or journal.get("version") != version
                or journal.get("phase") not in {"preparing", "activating", "rolling_back"}
                or not all(isinstance(journal.get(key), str) and COMMIT.fullmatch(journal[key]) for key in ("original", "target"))
                or head not in (journal["original"], journal["target"])
                or not isinstance(journal.get("branch"), str)
                or not valid_version(journal.get("previous_version"))
                or (journal["phase"] == "rolling_back" and not isinstance(journal.get("failure"), str))
                or (worker is not None and (not isinstance(worker, dict)
                    or any(key not in WORKER_SETTINGS or not isinstance(value, str) for key, value in worker.items())))):
            raise UpdateError("restore_failed")
        return journal
    current = git("show", "HEAD:VERSION")
    if not valid_version(current):
        raise UpdateError("invalid_installation_version")
    requested = tuple(map(int, version.split(".")))
    installed = tuple(map(int, current.split(".")))
    if requested <= installed:
        raise UpdateError("not_newer")
    target = published_target(version)
    ancestry = command(["git", "merge-base", "--is-ancestor", head, target], check=False)
    if ancestry.returncode:
        raise UpdateError("diverged_checkout")
    for revision in (head, target):
        verify_data_paths(revision)
    branch = command(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], check=False, capture=True).stdout.strip()
    journal = dict(request_id=request_id, version=version, original=head, branch=branch, target=target,
                   phase="preparing", worker=local_worker(), previous_version=current)
    write_document(path, journal, 0o600)
    return journal


def prebuild(path, target, worker):
    if path.is_symlink():
        raise UpdateError("unsafe_exchange")
    if path.exists():
        command(["git", "worktree", "remove", "--force", "--", str(path)])
    command(["git", "worktree", "add", "--detach", "--", str(path), target])
    try:
        require_local_database(path)
        compose("build", *CORE, source=path, timeout=1800)
        if worker is not None:
            compose("build", "console-worker", source=path, worker=True, timeout=900, environment=worker)
    finally:
        command(["git", "worktree", "remove", "--", str(path)])


def restore(journal):
    original, branch = journal["original"], journal["branch"]
    if git("status", "--porcelain", "--untracked-files=no"):
        raise UpdateError("dirty_checkout")
    if git("rev-parse", "HEAD") != original:
        command(["git", "switch", "--no-overwrite-ignore", "--detach", original])
    if branch and git("rev-parse", "refs/heads/" + branch) == original:
        command(["git", "switch", "--no-overwrite-ignore", "--", branch])
    require_local_database()
    prebuild(ROOT / "storage" / "updates" / (".build-" + journal["request_id"]), original, journal["worker"])
    activate(journal["worker"], journal["previous_version"])


def apply_update(version, request_id):
    if not (ROOT / ".env.console").is_file() or (ROOT / ".env.console").is_symlink():
        raise UpdateError("missing_installation")
    if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT or git("status", "--porcelain", "--untracked-files=no"):
        raise UpdateError("dirty_checkout")
    head = git("rev-parse", "HEAD")
    endpoint = os.environ.get("DOCKER_HOST") or command(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], capture=True,
    ).stdout.strip()
    if not endpoint.startswith("unix:"):
        raise UpdateError("nonlocal_docker")
    journal_path = ROOT / "storage" / "updates" / "journal.json"
    postgres = installation_containers("console-postgres", running=True)
    if len(postgres) != 1:
        raise UpdateError("missing_installation")
    database = container_environment(postgres[0])
    if (database.get("POSTGRES_DB"), database.get("POSTGRES_USER")) != ("emulytix", "emulytix_console"):
        raise UpdateError("unsupported_database")
    installation_containers("console-api")
    journal = setup_journal(journal_path, version, request_id, head)
    target, worker = journal["target"], journal["worker"]
    if journal["phase"] == "preparing":
        require_local_database()
        ensure_idle()
        prebuild(journal_path.parent / (".build-" + request_id), target, worker)
    with deployment_lock() as held:
        ensure_idle(verify_gate=True)
        held()
        if git("rev-parse", "HEAD") != head or git("status", "--porcelain", "--untracked-files=no"):
            raise UpdateError("dirty_checkout")
        if journal["phase"] == "rolling_back":
            try:
                restore(journal)
                held()
            except (OSError, subprocess.SubprocessError, RuntimeError, ValueError):
                raise UpdateError("restore_failed") from None
            raise Restored(journal["failure"])
        journal["phase"] = "activating"
        write_document(journal_path, journal, 0o600)
        try:
            if git("rev-parse", "HEAD") != target:
                command(["git", "switch", "--no-overwrite-ignore", "--detach", target])
            require_local_database()
            activate(worker, version)
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
            journal["phase"] = "rolling_back"
            journal["failure"] = str(error) if isinstance(error, UpdateError) else "installation_failed"
            write_document(journal_path, journal, 0o600)
            try:
                held()
                restore(journal)
                held()
            except (OSError, subprocess.SubprocessError, RuntimeError, ValueError):
                raise UpdateError("restore_failed") from None
            raise Restored(journal["failure"]) from None


def discard_matching_request(path, version, request_id):
    try:
        pending = requested_update(path)
    except (OSError, ValueError):
        return
    if pending == (version, request_id):
        path.unlink(missing_ok=True)


def recovery_pending(journal):
    try:
        return read_json(journal, 4096).get("phase") in {"activating", "rolling_back"}
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True


def run():
    import fcntl

    request, status = exchange()
    journal = status.parent.parent / "journal.json"
    lock_fd = os.open(ROOT / ".install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            old = read_json(status)
        except (OSError, ValueError):
            old = {}
        try:
            durable = read_json(journal, 4096)
        except FileNotFoundError:
            durable = None
        except (OSError, ValueError):
            refresh(status, "installing", old.get("version"), old.get("request_id"), "restore_failed")
            return
        if durable is not None:
            version, request_id = durable.get("version"), durable.get("request_id")
            if not valid_version(version) or not valid_request_id(request_id):
                refresh(status, "installing", old.get("version"), old.get("request_id"), "restore_failed")
                return
        else:
            try:
                version, request_id = requested_update(request)
            except FileNotFoundError:
                state = old.get("state")
                if state in {"installed", "failed"}:
                    refresh(status, state, old.get("version"), old.get("request_id"), old.get("error"))
                else:
                    refresh(status, "idle")
                return
            except (OSError, ValueError):
                refresh(status, "failed", error="invalid_request")
                request.unlink(missing_ok=True)
                return
        if old.get("request_id") == request_id and old.get("state") in {"installed", "failed"}:
            refresh(status, old["state"], version, request_id, old.get("error"))
        else:
            refresh(status, "installing", version, request_id)
            try:
                apply_update(version, request_id)
            except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
                code = str(error) if isinstance(error, UpdateError) else "installation_failed"
                if not isinstance(error, Restored) and (code == "restore_failed" or recovery_pending(journal)):
                    refresh(status, "installing", version, request_id, code)
                    return
                refresh(status, "failed", version, request_id, code)
                print(f"Emulytics: {code}", file=sys.stderr, flush=True)
            else:
                refresh(status, "installed", version, request_id)
        journal.unlink(missing_ok=True)
        discard_matching_request(request, version, request_id)


def unit_argument(argument):
    if any(ord(character) < 32 for character in argument):
        raise UpdateError("invalid_installation_path")
    return '"' + argument.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def enable():
    command(["systemctl", "--user", "show-environment"], capture=True)
    exchange()
    home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    directory = home / "systemd" / "user"
    directory.mkdir(parents=True, exist_ok=True)
    executable = " ".join(unit_argument(part) for part in (
        ":" + str(Path(sys.executable).resolve()), str(ROOT / "scripts" / "update.py"), "run",
    ))
    (directory / (UNIT + ".service")).write_text(
        "[Unit]\nDescription=Apply a requested Emulytics release\n\n"
        "[Service]\nType=oneshot\nTimeoutStartSec=14400\nUMask=0077\n"
        f"ExecStart={executable}\n", encoding="utf-8",
    )
    (directory / (UNIT + ".timer")).write_text(
        "[Unit]\nDescription=Check for Emulytics update requests\n\n"
        "[Timer]\nOnStartupSec=1s\nOnUnitInactiveSec=15s\nAccuracySec=1s\n\n"
        "[Install]\nWantedBy=timers.target\n", encoding="utf-8",
    )
    command(["systemctl", "--user", "daemon-reload"])
    command(["systemctl", "--user", "enable", "--now", UNIT + ".timer"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("enable", "run"))
    try:
        (enable if parser.parse_args().action == "enable" else run)()
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        reason = str(error) if isinstance(error, UpdateError) else "host_updater_unavailable"
        print(f"Emulytics: {reason}", file=sys.stderr)
        raise SystemExit(1)
