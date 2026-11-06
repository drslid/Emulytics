"""Private installer IPC. Credentials enter through stdin, never command arguments."""

import argparse
import json
import sys

import psycopg
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException

from .auth import AuthConfig, AuthStore, PASSWORD_HASHER


def state(store: AuthStore, password: str | None = None) -> dict:
    with store.connect() as connection:
        installation = connection.execute("SELECT bootstrapped FROM auth_installation WHERE singleton").fetchone()
        user = connection.execute(
            "SELECT id,password_hash,password_change_required FROM auth_users WHERE username='admin'"
        ).fetchone()
    pending = bool(user and user["password_change_required"])
    matches = False
    if password and pending:
        try:
            matches = PASSWORD_HASHER.verify(user["password_hash"], password)
        except (VerificationError, InvalidHashError):
            pass
    return {"initialized": installation["bootstrapped"], "pending": pending,
            "user_id": str(user["id"]) if user else None, "matches": matches}


def main():
    parser = argparse.ArgumentParser(description="Initialisation privée du premier accès")
    parser.add_argument("action", choices=["status", "bootstrap", "check"])
    args = parser.parse_args()
    try:
        store = AuthStore(AuthConfig.load())
        if args.action == "status":
            result = state(store)
        else:
            payload = json.loads(sys.stdin.read(8192))
            if not isinstance(payload, dict):
                raise ValueError("Invalid installer payload")
            password = payload.get("password")
            if set(payload) != {"password"} or not isinstance(password, str) or not 12 <= len(password) <= 1024:
                raise ValueError("Invalid installer payload")
            created = store.bootstrap_user(password) if args.action == "bootstrap" else False
            result = {**state(store, password), "created": created}
        print(json.dumps(result))
    except (ValueError, TypeError, KeyError, psycopg.Error, HTTPException):
        raise SystemExit("Initialisation indisponible. Vérifiez la configuration et les migrations.") from None


if __name__ == "__main__":
    main()
