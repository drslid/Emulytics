#!/usr/bin/env python3
"""Generate and deliver the first local credential without replacing an existing account."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "storage" / "install"
ACCESS = ARCHIVE / "initial-access.json"
MARKER = "emulytix.initial-access.v1"
COMPOSE = ["docker", "compose", "--env-file", str(ROOT / ".env.console"), "-p", "emulytix-preview",
           "-f", str(ROOT / "docker-compose.preview.yml"), "exec", "-T", "console-api", "python", "-m", "app.install_access"]


def backend(action: str, password: str | None = None) -> dict:
    result = subprocess.run(COMPOSE + [action], cwd=ROOT, text=True, capture_output=True, check=False,
                            input=json.dumps({"password": password}) if password is not None else None, timeout=30)
    if result.returncode:
        raise RuntimeError("Le premier accès n’a pas pu être initialisé. Vérifiez le service et ses migrations.")
    return json.loads(result.stdout)


def read_access() -> dict:
    fd = os.open(ACCESS, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("Le fichier d’accès initial doit être privé (mode 600) et appartenir à l’utilisateur local.")
        item = json.load(source)
    if not isinstance(item, dict) or item.get("schema") != MARKER or item.get("username") != "admin" or not isinstance(item.get("password"), str) or not 12 <= len(item["password"]) <= 1024:
        raise RuntimeError("Le fichier d’accès initial est invalide ; il n’a pas été remplacé.")
    return item


def main():
    parser = argparse.ArgumentParser(description="Préparation du premier accès Emulytix")
    parser.add_argument("--show", action="store_true", help="Afficher le mot de passe temporaire encore valide dans ce terminal")
    args = parser.parse_args()
    ARCHIVE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if ARCHIVE.is_symlink() or ARCHIVE.resolve().parent != (ROOT / "storage").resolve():
        raise RuntimeError("Répertoire d’installation invalide.")
    if ARCHIVE.stat().st_uid != os.getuid() or ARCHIVE.stat().st_mode & 0o077:
        raise RuntimeError("Le répertoire d’installation doit être privé (mode 700).")
    lock = os.open(ARCHIVE / ".bootstrap.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        status = backend("status")
        if status["initialized"] and not status["pending"]:
            print("Le premier accès est déjà configuré. Aucun compte ni mot de passe n’a été réinitialisé.")
            return
        if not ACCESS.exists() and not status["initialized"]:
            item = {"schema": MARKER, "username": "admin", "password": secrets.token_urlsafe(24)}
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=ARCHIVE, prefix=".initial-access-") as output:
                json.dump(item, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
                os.link(output.name, ACCESS, follow_symlinks=False)
        if not ACCESS.exists():
            raise RuntimeError("Le compte initial existe mais son fichier privé manque. Aucun mot de passe n’a été réinitialisé.")
        item = read_access()
        directory = os.open(ARCHIVE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        status = backend("check" if status["initialized"] else "bootstrap", item["password"])
        if not status["pending"]:
            print("Un compte est déjà configuré. Aucun mot de passe n’a été remplacé.")
            return
        if not status["matches"]:
            raise RuntimeError("Le fichier d’accès ne correspond pas au compte initial. Aucun mot de passe n’a été remplacé.")
        print("Premier accès : identifiant admin")
        if args.show:
            print("Mot de passe temporaire : " + item["password"])
        else:
            print("Mot de passe temporaire dans " + str(ACCESS))
            print("Pour l’afficher : scripts/account.sh initial-access")
        print("La première connexion impose un nouveau mot de passe, puis l’activation du 2FA.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        print("Initialisation du premier accès impossible. Vérifiez le fichier privé et le service ; aucun accès existant n’a été remplacé.", file=sys.stderr)
        raise SystemExit(1)
