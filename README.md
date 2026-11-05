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

## Première tranche : runs persistants

La première tranche du [plan](PLAN.MD) ajoute une API PostgreSQL pour déclarer des appareils, enregistrer des versions immuables de workflows, créer des runs idempotents, consulter leurs exécutions et événements, et annuler les runs encore en attente.

Les appareils déclarés ne sont pas considérés comme connectés. Les runs restent `queued` tant qu'aucun worker du bon hôte n'est lancé. Le worker local décrit ci-dessous peut maintenant les exécuter sur un appareil ciblé. Les événements se consultent en JSON paginé ; le flux SSE sera ajouté ensuite.

Le premier parcours métier demandé est décrit dans [WF01 : Chrome → Wikipédia → recherche football](docs/workflows/WF01-chrome-wikipedia-football.md), avec une [version exécutable](workflows/chrome-wikipedia-football.v1.json). Pour l'instant, utiliser des métadonnées de banc sans secrets : les paramètres sont stockés dans PostgreSQL, et le coffre n'est pas encore intégré.

### Activer PostgreSQL et appliquer les migrations

Le mode historique démarre avec `EMULYTIX_DATABASE_URL` vide. Les nouvelles routes requièrent une URL PostgreSQL et un jeton `EMULYTIX_CONTROL_TOKEN`. Le profil Compose `runs` ajoute PostgreSQL 17 avec un volume persistant, sans publier son port sur l'hôte.

Depuis la racine du projet, préparer les secrets pour une première installation locale :

```bash
export EMULYTIX_POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export EMULYTIX_CONTROL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export EMULYTIX_DATABASE_URL="postgresql://emulytix:${EMULYTIX_POSTGRES_PASSWORD}@postgres:5432/emulytix"

docker compose --profile runs up -d postgres
docker compose --profile runs run --build --rm migrate
docker compose up -d --build orchestrator-api
```

Conserver ces valeurs pour les redémarrages, par exemple dans le fichier `.env` local non versionné. Un volume PostgreSQL déjà initialisé garde son mot de passe initial ; regénérer une variable ne change pas ce mot de passe. Le service `migrate` attend que PostgreSQL soit prêt. Relancer la commande de migration applique les migrations manquantes.

L'URL ci-dessus utilise `postgres`, le nom du service sur le réseau Compose. Pour lancer l'API directement sur l'hôte, fournir une URL de base accessible depuis cet hôte. Le mode all-in-one reçoit aussi l'URL et le jeton, mais PostgreSQL demeure un service externe à son image.

Une configuration absente, un schéma non migré ou une base indisponible rend les routes de cette tranche indisponibles avec une réponse `503` ; le démarrage de l'API et les routes historiques restent indépendants de PostgreSQL.

### Routes et authentification

Chaque requête de cette tranche utilise `Authorization: Bearer $EMULYTIX_CONTROL_TOKEN`. Ce jeton partagé protège uniquement les nouvelles routes. Il ne constitue pas une gestion de rôles et ne protège pas les anciennes routes `/sessions`, le chat ou le contrôle Android historique ; utiliser encore le banc dans un environnement à accès restreint.

| Route | Usage |
|---|---|
| `POST /devices`, `GET /devices` | Déclarer un appareil immuable et lister les déclarations |
| `POST /workflows` | Enregistrer une version immuable de workflow |
| `GET /workflows/{workflow_id}/versions/{version}` | Lire la version utilisée par les runs |
| `POST /runs`, `GET /runs` | Créer un run et lister les runs persistants |
| `GET /runs/{run_id}` | Lire un run et ses exécutions |
| `POST /runs/{run_id}/cancel` | Annuler un run en attente, ou demander l'arrêt au worker actif |
| `GET /runs/{run_id}/events` | Lire les événements durables, en JSON |
| `GET /executions/{execution_id}/actions` | Consulter les intentions et résultats des actions Android |

Les listes acceptent `limit` (1 à 100, défaut 100) et `offset` (défaut 0). Les événements acceptent `after` (identifiant d'événement, défaut 0) et `limit`, et répondent avec `{items, limit, after}`. Les contrats détaillés figurent dans Swagger : `http://localhost:8010/docs`.

### Essayer un parcours complet

Les exemples supposent que le jeton est disponible dans le shell et que l'API écoute sur `localhost:8010`. Déclarer d'abord un appareil de banc :

```bash
curl --fail-with-body http://localhost:8010/devices \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"bench-emulator","host_id":"bench-host","serial":"emulator-5554","kind":"emulator"}'
```

Enregistrer un workflow de démonstration ; son assertion et son action sont stockées pour le futur moteur, sans être exécutées :

```bash
curl --fail-with-body http://localhost:8010/workflows \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"workflow_id":"bench-home","version":1,"steps":[{"id":"home","action":"press_key","args":{"keycode":"KEYCODE_HOME"},"assert":{"type":"package","value":"com.android.launcher3"}}]}'
```

Créer un run et conserver son identifiant :

```bash
EMULYTIX_RUN_ID="$(curl --fail-with-body http://localhost:8010/runs \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"workflow_id":"bench-home","workflow_version":1,"device_ids":["bench-emulator"],"max_concurrency":1,"idempotency_key":"bench-001"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')"

curl --fail-with-body "http://localhost:8010/runs/${EMULYTIX_RUN_ID}" \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}"
curl --fail-with-body "http://localhost:8010/runs/${EMULYTIX_RUN_ID}/events?after=0&limit=100" \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}"
curl --fail-with-body -X POST "http://localhost:8010/runs/${EMULYTIX_RUN_ID}/cancel" \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}"
```

Renvoyer la même demande avec `bench-001` retrouve le même run, y compris après son annulation ou le redémarrage de l'API. Réutiliser cette clé avec un autre contenu est un conflit. La version du workflow et le lot d'appareils restent figés.

### Vérifier la tranche

Préparer l'environnement Python et l'image utilisée par les tests d'intégration :

```bash
uv venv .venv
uv pip install --python .venv/bin/python \
  -r orchestrator-api/requirements.txt \
  -r orchestrator-api/requirements-dev.txt
docker pull postgres:17-alpine
.venv/bin/python -m pytest orchestrator-api/tests
```

Les tests PostgreSQL utilisent Docker et une base éphémère avec des schémas isolés ; aucune URL de base applicative n'est nécessaire. Les cas couverts et les limites restantes sont suivis dans `PLAN.MD`.

Un [rapport Graphify local](graphify-out/GRAPH_REPORT.md) et un [graphe HTML](graphify-out/graph.html) décrivent les dépendances des sources analysées, avec leur portée et leurs limites. Ces artefacts locaux sont rafraîchis après les changements de code.

## Worker local et parcours Chrome/Wikipédia

Le worker sélectionne les exécutions de son `host_id`, obtient un bail PostgreSQL avec epoch et garde un verrou local par appareil. Il valide toutes les étapes avant de commencer, cible chaque commande par serial et journalise les intentions avant les actions à effet. Les observations sont soumises aux mêmes contrôles de bail et conservées dans les preuves des étapes.

Un watchdog indépendant arrête le client ADB à l'échéance locale même si une requête PostgreSQL bloque. Le lanceur Linux lie aussi la vie du client ADB à celle du worker. Un bail expiré occupé ou une action dont l'effet est incertain entraîne `needs_review` et la quarantaine du device, sans reprise automatique.

Cette tranche utilise un contrôleur ADB déterministe. L'adaptation des composants ARTEMIS, la récupération LLM et la revue opérateur restent au plan. Le profil courant autorise les actions prévues pour Chrome/Wikipédia ; il n'expose pas de shell libre.

### Démarrer le banc observé

Le script de banc utilise une image **déjà présente localement**, `emulytix/android-runtime-check:0.8.1`, contenant Android 10/x86_64 et Chrome 74. Il ne la télécharge pas et ne représente pas la validation Android 14 prévue au plan. Il faut Docker et `/dev/kvm` :

```bash
./android-runtime/scripts/start-bench.sh
```

Un nouvel AVD est créé dans le conteneur `emulytix-wf01-android`, sur le réseau privé `emulytix-wf01-bench`. Aucun port Android/ADB n'est publié. Le script refuse de remplacer un conteneur existant. Les noms et l'image sont configurables par `EMULYTIX_BENCH_CONTAINER`, `EMULYTIX_BENCH_NETWORK` et `EMULYTIX_BENCH_IMAGE`.

Le package `com.android.chrome` est déjà installé dans ce banc. Le workflow vérifie sa présence avant de naviguer. Pour un appareil sans Chrome, le driver attend un APK approuvé sous `storage/runtime-apks/` avec une empreinte SHA256 ; la signature et l'ABI doivent être contrôlées lors de cette approbation. Les installations par Play Store et APK fractionnés ne sont pas automatisées dans cette tranche.

### Relier API, PostgreSQL et worker

Après avoir défini les secrets et `EMULYTIX_DATABASE_URL` comme indiqué plus haut :

```bash
export EMULYTIX_HOST_ID=bench-host
export ADB_SERVER_SOCKET=tcp:emulytix-wf01-android:5037

docker compose -f docker-compose.yml -f docker-compose.runtime.yml \
  --profile runs --profile worker up -d postgres
docker compose -f docker-compose.yml -f docker-compose.runtime.yml \
  --profile runs --profile worker run --build --rm migrate
docker compose -f docker-compose.yml -f docker-compose.runtime.yml \
  --profile runs --profile worker up -d --build orchestrator-api worker
```

L'override runtime désactive le contrôle Android historique de l'API pour éviter son utilisation parallèle avec le worker. Le banc n'expose pas de contrôle interactif noVNC. Les workers du même hôte doivent partager le volume `worker_locks`, le même identifiant d'hôte et le même serveur ADB. Le worker ne monte ni socket Docker ni `/dev/kvm`.

Déclarer l'appareil et publier le workflow, puis créer le run :

```bash
curl --fail-with-body http://localhost:8010/devices \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"wf01-emulator","host_id":"bench-host","serial":"emulator-5554","kind":"emulator"}'
curl --fail-with-body http://localhost:8010/workflows \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary @workflows/chrome-wikipedia-football.v1.json
curl --fail-with-body http://localhost:8010/runs \
  -H "Authorization: Bearer ${EMULYTIX_CONTROL_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"workflow_id":"chrome-wikipedia-football","workflow_version":1,"device_ids":["wf01-emulator"],"max_concurrency":1,"idempotency_key":"wf01-001"}'
```

Le résultat de `GET /runs/{run_id}` contient l'état et les preuves des étapes dans `executions[].evidence.steps`. Les captures et observations XML sont écrites sous `storage/runs/{execution_id}/{lease_epoch}/`. Utiliser une nouvelle clé d'idempotence pour demander une nouvelle exécution.

L'annulation d'un run actif retourne `202` avec `cancel_requested=true` tant que le worker n'a pas confirmé la fin. Une action incertaine peut aboutir à `needs_review`. L'annulation d'un lot encore en attente reste immédiate (`200`). Les exécutions sans propriétaire confirmé ne sont pas présentées comme neutralisées.

Pour arrêter le banc créé par le script après arrêt du worker :

```bash
docker compose -f docker-compose.yml -f docker-compose.runtime.yml \
  --profile runs --profile worker stop worker
docker rm --force --volumes emulytix-wf01-android
```

Les preuves locales de validation sont conservées dans `storage/wf01-worker/`. Le stockage local, l'absence d'interface de résolution de quarantaine et le banc Android 10 restent des limites de cette tranche ; les jalons S1/S2/S3 restent ouverts.
