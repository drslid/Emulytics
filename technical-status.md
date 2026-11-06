# Emulytix Technical Status

## 1. Besoin fonctionnel

Le besoin cible est le suivant :

- lancer un Android dans Docker
- le voir dans une interface web
- le contrôler visuellement et par commandes
- converser avec une IA OpenAI pour piloter l'Android
- choisir le modèle OpenAI, avec `gpt-5.4` par défaut et des modèles moins chers disponibles
- uploader un APK
- installer l'APK sur l'Android
- désinstaller ensuite les applications installées
- exposer une API documentée avec Swagger
- pouvoir fonctionner avec `KVM` si nécessaire
- disposer d'une option "tout dans une image"

## 2. Ce qui a été fait techniquement

### Structure projet

Le dossier `Emulytix` a été créé avec les composants suivants :

- `study.md`
- `README.md`
- `docker-compose.yml`
- `orchestrator-api/`
- `agent-service/`
- `web-ui/`
- `android-runtime/`
- `storage/`

### API d'orchestration

Le service `orchestrator-api` a été implémenté en `FastAPI`.

Fonctions déjà présentes :

- création et lecture de sessions
- endpoint de santé
- endpoint `runtime-capabilities`
- endpoint `android/status`
- endpoint `ai/models`
- endpoint `screen`
- endpoint de chat `sessions/{id}/chat`
- upload APK
- listing des APK uploadés
- suppression d'un APK uploadé
- demande d'installation APK
- key events Android
- open app
- uninstall package
- screenshot
- logs de session
- Swagger via `/docs`

Fichier principal :

- [main.py](/home/slid/Emulytix/orchestrator-api/app/main.py)

### Runtime Android

Le runtime Android a été préparé autour de `budtmo/docker-android`.

Fichiers présents :

- [Dockerfile](/home/slid/Emulytix/android-runtime/Dockerfile)
- [bootstrap.sh](/home/slid/Emulytix/android-runtime/scripts/bootstrap.sh)

Le service Docker est déjà prévu dans [docker-compose.yml](/home/slid/Emulytix/docker-compose.yml) derrière un profil `android`.

État de la stratégie runtime :

- `budtmo/docker-android` reste actuellement la meilleure base locale pour conserver Android 14
- la vue embarquée Emulytix n'est plus couplée à `budtmo`
- Emulytix consomme maintenant une URL d'embed Android configurable
- cela permet de remplacer plus tard `budtmo/noVNC` par un autre provider web sans refaire le frontend ni le flux de chat
- `dockerify-android` a été évalué comme provider web alternatif, mais son README décrit encore un AVD Android 11 au premier boot, donc moins récent que notre base actuelle

### Mode All-in-One

Un mode monolithique a été ajouté pour satisfaire la contrainte "tout dans une image".

Fichiers ajoutés :

- [Dockerfile](/home/slid/Emulytix/all-in-one/Dockerfile)
- [start.sh](/home/slid/Emulytix/all-in-one/start.sh)

Ce mode embarque dans une seule image :

- Android `budtmo/docker-android`
- `orchestrator-api`
- `agent-service`
- `web-ui`

Le bootstrap :

- démarre Android si `/dev/kvm` existe
- démarre quand même UI/API/agent sans Android si `KVM` manque
- bascule sur un stockage interne si `/storage` n'est pas writable

### Frontend

Le frontend `web-ui` a été créé en `Next.js`.

Fonctions présentes :

- vue type chat
- affichage du statut réel du runtime Android
- sélection de modèle OpenAI
- saisie d'une clé API OpenAI temporaire
- upload APK
- installation du dernier APK
- saisie d'un package à désinstaller
- boutons `Home`, `Back`, `Recent`, `Screenshot`
- vue Android intégrée dans l'interface
- vue Android maintenant injectée dans la colonne de conversation
- viewport Android alimenté par une URL d'embed configurable

Fichiers principaux :

- [page.tsx](/home/slid/Emulytix/web-ui/app/page.tsx)
- [globals.css](/home/slid/Emulytix/web-ui/app/globals.css)

### Agent OpenAI

Le service `agent-service` a été relié à OpenAI avec fallback local.

Fonctions présentes :

- modèle par défaut `gpt-5.4`
- modèles configurables :
  - `gpt-5.4`
  - `gpt-5.4-mini`
  - `gpt-5.4-nano`
  - `gpt-4o-mini`
- utilisation d'une clé serveur `OPENAI_API_KEY`
- support d'une clé temporaire fournie par l'UI
- fallback local si aucune clé n'est disponible
- génération d'un plan d'actions structuré

Fichier principal :

- [main.py](/home/slid/Emulytix/agent-service/app/main.py)

### Stockage

Un stockage local a été ajouté :

- [storage/.gitkeep](/home/slid/Emulytix/storage/.gitkeep)

Le backend y stocke les APK uploadés et les screenshots.

### Configuration

Le fichier [docker-compose.yml](/home/slid/Emulytix/docker-compose.yml) a été enrichi avec :

- variables OpenAI
- volume de stockage local
- séparation entre URL interne Android et URL publique Android
- sélection du conteneur runtime Android

Le fichier [.env.example](/home/slid/Emulytix/.env.example) contient les variables nécessaires.

## 3. Ce qui a été validé techniquement

Validations effectuées :

- compilation Python des services API et agent
- validation `docker compose config`
- build et démarrage réels de :
  - `emulytix-web-ui`
  - `emulytix-orchestrator-api`
  - `emulytix-agent-service`
- réponse du frontend
- réponse de l'API
- réponse de l'agent
- création de session
- upload d'un APK de test
- suppression du fichier APK uploadé
- chat backend avec fallback sans clé OpenAI
- build réel de l'image monolithique `all-in-one`
- démarrage réel du monolithe sans `KVM`
- vérification réelle dans le monolithe de :
  - UI
  - API
  - agent
  - statut runtime local
  - chat fallback
- boot Android réel en mode logiciel dans le monolithe
- accès ADB réel avec device `emulator-5554`
- `sys.boot_completed=1`
- endpoint `android/status` renvoyant un runtime disponible
- URL noVNC auto-connectée embarquable directement dans le chat

## 4. État actuel

Le blocage initial lié à `/dev/kvm` a été partiellement contourné dans l'image monolithique.

Conséquence actuelle :

- l'Android démarre réellement ici en mode logiciel
- le viewport Android est disponible dans Emulytix
- les actions ADB réelles peuvent être testées sur ce serveur
- `KVM` reste recommandé pour de meilleures performances et une meilleure stabilité

## 5. Ce qu'il reste à faire

### Priorité haute

- durcir le flux chat -> plan -> actions ADB de bout en bout
- valider l'ergonomie de la vue Android dans la colonne de conversation
- exposer plus clairement l'abstraction de provider Android dans l'API
- documenter le remplacement futur de `budtmo` par un provider web alternatif si nécessaire

### Priorité haute une fois KVM disponible

- démarrer l'Android réel
- valider le viewport web Android
- valider les commandes `adb`
- valider installation APK réelle
- valider désinstallation package réelle
- valider chat OpenAI -> plan -> exécution réelle
- valider le mode `all-in-one` complet avec `/dev/kvm`

### Priorité moyenne

- rendre l'UI compatible reverse proxy
- homogénéiser les URLs publiques
- ajouter un proxy intégré ou des routes unifiées
- brancher de vrais flux screenshot téléchargeables
- enrichir la gestion des erreurs côté frontend
- ajouter un mode OAuth OpenAI applicatif si le choix final n'est pas l'API key

### Priorité basse

- auth utilisateur applicative
- historique persistant du chat
- multi-session Android
- audit complet des actions

## 6. Décision d'architecture en cours

À ce stade, deux modes coexistent :

- mode `compose` multi-services, déjà fonctionnel pour UI + API + agent
- mode `all-in-one`, à ajouter pour répondre à la contrainte "tout dans une image"

## 7. Étape suivante engagée

L'étape suivante engagée est :

- valider l'image `all-in-one` sur un hôte avec `KVM`
- brancher l'Android réel dans les parcours APK/chat
- décider si l'auth OpenAI reste en API key ou doit inclure OAuth

## 8. Références de fichiers clés

- [study.md](/home/slid/Emulytix/study.md)
- [technical-status.md](/home/slid/Emulytix/technical-status.md)
- [docker-compose.yml](/home/slid/Emulytix/docker-compose.yml)
- [README.md](/home/slid/Emulytix/README.md)
- [main.py](/home/slid/Emulytix/orchestrator-api/app/main.py)
- [main.py](/home/slid/Emulytix/agent-service/app/main.py)
- [page.tsx](/home/slid/Emulytix/web-ui/app/page.tsx)


## Console d'exploitation — 6 novembre 2026

La console locale `http://localhost:3100` distingue Tableau de bord, Appareils, Parcours, Exécutions, Planifications, Monitoring, Journal, Utilisateurs et Mon profil/Sécurité. Les comptes et le parc préexistants sont conservés. Les migrations 005–008 ajoutent cinq rôles avec droits serveur, audit, brouillons et versions publiées, planifications persistantes, noms d'affichage et heartbeats. Le service `console-scheduler` est inclus dans le démarrage normal.

Une planification suit un CRON à cinq champs et un fuseau explicite, avec aperçu et pause/reprise. Les échéances produisent des runs idempotents et recontrôlent les droits du créateur. Le monitoring SSE reçoit des observations réelles et distingue services absents et signaux périmés. Les journaux exposent des codes d'événements et corrélations autorisés, sans arguments ni secrets.

Dix langues locales, détection navigateur, choix persistant par petits drapeaux, polices locales et arabe RTL. Les noms métier restent ceux saisis par les utilisateurs. Les catalogues ont reçu une première traduction automatique et une revue de terminologie technique ; une validation linguistique native reste à faire avant diffusion internationale.

Le moteur reste le profil Chrome/Wikipédia et la saisie ASCII validés sur le banc. L'ajout d'appareil est une déclaration, sans démarrage automatique d'Android. iOS, l'API publique, le MCP et les clés personnelles restent prévus au PLAN.MD. L'édition d'un planning complet passe actuellement par sa recréation ; la console propose pause/reprise.


### Vérification réelle du lancement local — 6 novembre 2026

Le banc Android et `console-worker` sont désormais actifs. L'appareil réel à sélectionner est **Émulateur local** (`bench-host` / `emulator-5554`). Le premier run lancé depuis le site a terminé `succeeded` avec 11 étapes : Chrome, recherche de football dans Wikipédia, titre final vérifié et capture disponible dans Activité. Le run et les preuves restent dans la base courante, distincts de l'archive `/validation`.

La déclaration `banc-de-test` sous `bench` / `moultiplate` et ses quatre soumissions en attente sont conservées ; elles ne correspondent pas à cette connexion Android. L'interface affiche désormais ce défaut de connexion et interdit une nouvelle confirmation immédiate sur un appareil non observé connecté. Les cinq états d'échec de connexion sont distincts de l'occupation et de la quarantaine. Le helper `scripts/start-console-android.sh` prépare un banc connecté sans réaffecter les anciennes demandes.

### Écran actuel et reprise du backlog — 6 novembre 2026

La page /ecrans, les appareils et le détail d'une exécution proposent désormais l'écran Android actuel en lecture seule, actualisé environ une fois par seconde. Le worker capture uniquement à la demande ; l'API sert une image privée vérifiée avec date et fraîcheur. Une image ancienne est signalée figée. Chaque lecture vérifie la session et les permissions. L'API n'a toujours aucun accès Docker/ADB.

Les quatre anciennes demandes ont été reprises sur local-emulator, puis leurs sources annulées avec lien de provenance. Les quatre remplacements ont réussi leurs 11 étapes. Les lots d'origine restent immuables. La capacité courante est une exécution simultanée ; les quatre ont été observées en série sur le seul émulateur connecté. Tests : 268 API et 30 frontend. Direct, plein écran, mobile et expiration ont été observés dans le navigateur.


### Actions personnelles de sécurité — 6 novembre 2026

Mon profil propose maintenant des actions réelles : changement de mot de passe, remplacement de l'application 2FA, renouvellement des codes de secours. Réauthentification, limitation persistante, anti-rejeu et rotation des sessions sont appliqués côté serveur. Le QR temporaire chiffré expire après cinq minutes et reste lié à la session initiatrice. Le 2FA obligatoire n'est pas désactivé pendant le remplacement.

La migration 010 ajoute la configuration TOTP temporaire. Les actions sont disponibles pour les cinq rôles sur leur propre compte, sans accès par Bearer de service ni possibilité de choisir un autre utilisateur. Les autres sessions sont fermées après modification ; la session courante est renouvelée. Validation : 288 tests API, 31 tests frontend et cinq groupes de contrôles dans le navigateur. Le compte administrateur existant n'a pas servi aux essais.
