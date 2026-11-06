"""Local-only account administration: python -m app.auth_admin create USERNAME."""

import argparse
import getpass
import re

import psycopg
from fastapi import HTTPException

from .auth import AuthConfig, AuthStore


def main():
    parser = argparse.ArgumentParser(description="Administration locale des comptes Emulytix")
    parser.add_argument("action", choices=["create", "reset-2fa"])
    parser.add_argument("username")
    args = parser.parse_args()
    username = args.username.lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username):
        parser.error("Identifiant : 3 à 64 caractères, lettres, chiffres, point, tiret ou underscore.")
    try:
        store = AuthStore(AuthConfig.load())
        if args.action == "create":
            password = getpass.getpass("Mot de passe (12 caractères minimum) : ")
            if password != getpass.getpass("Confirmer le mot de passe : "):
                raise SystemExit("Les mots de passe diffèrent.")
            store.create_user(username, password)
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
