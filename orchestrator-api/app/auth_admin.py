"""Local-only account administration: python -m app.auth_admin create USERNAME."""

import argparse
import getpass

import psycopg
from fastapi import HTTPException

from .auth import AuthConfig, AuthStore
from .access import ROLE_PERMISSIONS, normalize_username


def main():
    parser = argparse.ArgumentParser(description="Administration locale des comptes Emulytix")
    parser.add_argument("action", choices=["create", "reset-2fa"])
    parser.add_argument("username")
    parser.add_argument("--role", choices=sorted(ROLE_PERMISSIONS), default="admin")
    args = parser.parse_args()
    username = normalize_username(args.username)
    try:
        store = AuthStore(AuthConfig.load())
        if args.action == "create":
            password = getpass.getpass("Mot de passe (12 caractères minimum) : ")
            if password != getpass.getpass("Confirmer le mot de passe : "):
                raise SystemExit("Les mots de passe diffèrent.")
            store.create_user(args.username, password, role=args.role)
            print("Compte créé. La première connexion impose l'activation du 2FA.")
        else:
            if not store.reset_two_factor(username):
                raise SystemExit("Compte introuvable.")
            print("2FA réinitialisé. Toutes les sessions et codes de secours ont été révoqués.")
    except HTTPException as exc:
        raise SystemExit(exc.detail) from None
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except psycopg.errors.UniqueViolation:
        raise SystemExit("Ce compte existe déjà.") from None
    except psycopg.Error:
        raise SystemExit("Base indisponible ou migrations manquantes.") from None


if __name__ == "__main__":
    main()
