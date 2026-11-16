#!/usr/bin/env python3
"""Install the local console and its Android runtime without replacing user data."""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_IMAGE = "emulytix/android-runtime:0.9.0"
MIN_MEMORY = 8 * 1024**3
MIN_DISK = 25 * 1024**3


def run(command: list[str], **options) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=True, **options)


def check_memory(*, allow_low_memory: bool = False) -> None:
    total = int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    if total < MIN_MEMORY:
        detected = f"{total / 1024**3:.2f} Gio détectés"
        if not allow_low_memory:
            raise RuntimeError(
                f"Au moins 8 Gio de RAM sont nécessaires pour la console et un émulateur ({detected}). "
                "Augmentez la RAM allouée à Linux/WSL ou utilisez --allow-low-memory pour accepter une capacité réduite. "
                "Au moins 4 Gio disponibles restent obligatoires."
            )
        print(f"Attention : mémoire totale inférieure aux 8 Gio recommandés ({detected}) ; capacité réduite acceptée.", flush=True)
    readings = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    available = int(readings["MemAvailable"].split()[0]) * 1024
    if available < 4 * 1024**3:
        raise RuntimeError(
            f"Libérez au moins 4 Gio de RAM avant de démarrer la console et Android ({available / 1024**3:.2f} Gio disponibles)."
        )


def preflight(*, allow_low_memory: bool = False) -> None:
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("L’émulateur local nécessite Linux x86_64 avec KVM. Aucun service n’a été modifié.")
    for executable in ("docker", "bash"):
        if not shutil.which(executable):
            raise RuntimeError(f"{executable} est introuvable. Installez Docker Engine et Docker Compose avant de relancer.")
    try:
        info = json.loads(run(["docker", "info", "--format", "{{json .}}"], capture_output=True, text=True, timeout=15).stdout)
        run(["docker", "compose", "version"], capture_output=True, text=True, timeout=15)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        raise RuntimeError("Docker/Compose indisponible. Démarrez Docker et vérifiez l’accès de votre utilisateur.") from None
    if info.get("OSType") != "linux" or info.get("Architecture") not in ("x86_64", "amd64"):
        raise RuntimeError("Le serveur Docker doit être Linux x86_64 sur cette machine avec accès KVM.")
    # A remote daemon cannot mount the project or /dev/kvm from this machine safely.
    endpoint = os.environ.get("DOCKER_HOST")
    if not endpoint:
        endpoint = run(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], capture_output=True, text=True, timeout=15).stdout.strip()
    if not endpoint.startswith("unix:"):
        raise RuntimeError("Utilisez le moteur Docker local ; les chemins et KVM appartiennent à cette machine.")
    kvm = Path("/dev/kvm")
    rootless = any("rootless" in option for option in info.get("SecurityOptions", []))
    if not kvm.exists() or not stat.S_ISCHR(kvm.stat().st_mode) or (rootless and not os.access(kvm, os.R_OK | os.W_OK)):
        raise RuntimeError("KVM inaccessible (/dev/kvm). Activez la virtualisation ; en mode Docker rootless, vérifiez aussi votre appartenance au groupe kvm.")
    check_memory(allow_low_memory=allow_low_memory)
    docker_root = Path(info.get("DockerRootDir", "/var/lib/docker"))
    for directory in (ROOT, docker_root):
        if directory.exists() and shutil.disk_usage(directory).free < MIN_DISK:
            raise RuntimeError(f"Prévoyez 25 Gio libres pour les images, les données et Android ({directory}).")
    print("Prérequis validés : Docker, Compose, KVM, mémoire et stockage.", flush=True)


def runtime_settings() -> dict[str, str]:
    values = dict.fromkeys(("EMULYTIX_MANAGED_IMAGE", "EMULYTIX_BENCH_IMAGE"), RUNTIME_IMAGE)
    destination = ROOT / ".env.console"
    if destination.exists() or destination.is_symlink():
        fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise RuntimeError(".env.console doit vous appartenir et être privé (chmod 600). Aucun secret n’a été remplacé.")
            for line in source:
                name, separator, value = line.strip().partition("=")
                if separator and name in values:
                    try:
                        fields = shlex.split(value, comments=True)
                    except ValueError:
                        raise RuntimeError(f"Image invalide dans {name}. Vérifiez .env.console.") from None
                    if len(fields) != 1 or not fields[0]:
                        raise RuntimeError(f"Image invalide dans {name}. Vérifiez .env.console.")
                    values[name] = fields[0]
    result = {name: os.environ.get(name, value) for name, value in values.items()}
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,254}', value) for value in result.values()):
        raise RuntimeError("Nom d’image Android invalide. Indiquez un nom Docker avec sa version explicite.")
    return result


def ensure_environment(images: dict[str, str] | None = None) -> None:
    destination = ROOT / ".env.console"
    if destination.exists() or destination.is_symlink():
        fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise RuntimeError(".env.console doit vous appartenir et être privé (chmod 600). Aucun secret n’a été remplacé.")
        return
    password = secrets.token_hex(24)
    values = {
        "EMULYTIX_POSTGRES_PASSWORD": password,
        "EMULYTIX_DATABASE_URL": f"postgresql://emulytix_console:{password}@console-postgres:5432/emulytix",
        "EMULYTIX_CONTROL_TOKEN": secrets.token_urlsafe(32),
        "EMULYTIX_AUTH_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "EMULYTIX_PUBLIC_ORIGIN": "http://localhost:3100",
        "EMULYTIX_COOKIE_SECURE": "false",
        **(images or runtime_settings()),
    }
    with tempfile.NamedTemporaryFile(mode="w", dir=ROOT, prefix=".env.console-") as candidate:
        candidate.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
        candidate.flush()
        os.fsync(candidate.fileno())
        os.link(candidate.name, destination, follow_symlinks=False)
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    print("Configuration privée créée. Les futurs lancements conserveront les accès et les données.", flush=True)


def wait_for_console() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:3100/connexion", timeout=3) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise RuntimeError("L’interface n’est pas encore disponible sur le port 3100. Vérifiez validation-ui puis relancez ; les données sont conservées.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Installer Emulytix et un émulateur local, sans supprimer les données existantes.")
    parser.add_argument("--accept-android-license", action="store_true", help="Accepter les conditions Android SDK : https://developer.android.com/studio/terms")
    parser.add_argument("--check", action="store_true", help="Vérifier uniquement les prérequis, sans installation")
    parser.add_argument("--allow-low-memory", action="store_true", help="Accepter moins de 8 Gio de RAM totale ; exige toujours 4 Gio disponibles")
    args = parser.parse_args()
    preflight(allow_low_memory=args.allow_low_memory)
    if args.check:
        return
    images = runtime_settings()
    missing = {image for image in images.values() if subprocess.run(["docker", "image", "inspect", image], cwd=ROOT, capture_output=True, check=False, timeout=15).returncode != 0}
    if missing - {RUNTIME_IMAGE}:
        raise RuntimeError("Une image Android personnalisée est absente. Construisez-la ou téléchargez-la explicitement avant de relancer.")
    if missing and not args.accept_android_license:
        raise RuntimeError("L’image Android doit être construite. Consultez https://developer.android.com/studio/terms puis relancez avec --accept-android-license si vous acceptez ces conditions.")
    lock_fd = os.open(ROOT / ".install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Une installation est déjà en cours dans ce dossier.") from None
        ensure_environment(images)
        if missing:
            print("Construction d’Android 10 et Chrome depuis les archives officielles vérifiées (environ 1,8 Go à télécharger).", flush=True)
            run(["docker", "build", "--platform", "linux/amd64", "--build-arg", "ANDROID_SDK_LICENSE_ACCEPTED=true", "-f", "android-runtime/Dockerfile.console", "-t", RUNTIME_IMAGE, "android-runtime"])
        run(["docker", "run", "--rm", "--device", "/dev/kvm", "--entrypoint", "/opt/android-sdk/emulator/emulator", images["EMULYTIX_BENCH_IMAGE"], "-accel-check"])
        run(["bash", "scripts/start-console.sh"])
        runtime_environment = dict(os.environ)
        runtime_environment.update(images)
        run(["bash", "scripts/start-console-android.sh"], env=runtime_environment)
        wait_for_console()
    print("Emulytix est prêt : http://localhost:3100\nPremier accès : scripts/account.sh initial-access\nChangez le mot de passe temporaire, activez le 2FA, puis préparez votre premier parcours.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, RuntimeError) else "Une étape a échoué. Corrigez la cause indiquée puis relancez la même commande ; les données sont conservées."
        print(message, file=sys.stderr)
        raise SystemExit(1)
