# Emulytix

Emulytix est un squelette de plateforme pour piloter un runtime Android via API et interface conversationnelle.

## Contenu

- `web-ui`: interface de type ChatGPT avec panneau Android
- `orchestrator-api`: API FastAPI exposée avec Swagger
- `agent-service`: service de planification langage naturel -> actions
- `android-runtime`: wrapper autour de `budtmo/docker-android`

## Démarrage rapide

Copier l'environnement :

```bash
cp .env.example .env
```

Démarrer la stack hors Android :

```bash
docker compose up --build
```

Services attendus :

- UI : `http://localhost:3000`
- API : `http://localhost:8010`
- Swagger : `http://localhost:8010/docs`
- Agent : `http://localhost:8011`

## OpenAI

Deux modes sont prévus :

- clé serveur via `.env` avec `OPENAI_API_KEY`
- clé temporaire saisie dans l'interface web et envoyée au backend pour la requête en cours

Modèle par défaut :

- `gpt-5.4`

Modèles configurés par défaut :

- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.4-nano`
- `gpt-4o-mini`

## Fonctionnalités API

Le backend expose déjà :

- statut runtime Android
- upload APK
- installation du dernier APK uploadé
- uninstall de package
- key events Android
- screenshots
- chat -> plan OpenAI -> exécution

## Runtime Android

Le runtime Android est derrière le profil `android` :

```bash
docker compose --profile android up --build
```

Prérequis :

- hôte Linux compatible `KVM`
- `/dev/kvm` présent

Le serveur actuel ne remplit pas ce prérequis. La stack démarre donc sans Android par défaut.

## Mode All-in-One

Une image monolithique a été ajoutée pour répondre à la contrainte "tout dans une image".

Démarrage :

```bash
docker compose --profile all-in-one up --build emulytix-all-in-one
```

Ce mode embarque dans une seule image :

- runtime Android `budtmo/docker-android`
- `orchestrator-api`
- `agent-service`
- `web-ui`

Prérequis :

- `/dev/kvm` exposé sur l'hôte pour avoir l'Android réel

Sans `KVM`, le conteneur démarre quand même les services UI/API/agent mais l'Android reste hors ligne.
