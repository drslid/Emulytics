# Emulytix Study

## 1. Objectif

Construire une plateforme `Emulytix` permettant de lancer un Android dans un environnement conteneurisé, de le visualiser et le contrôler via interface web, d'installer des APK, d'exposer une API de pilotage, et d'ajouter une interface conversationnelle de type ChatGPT capable de transformer des instructions en langage naturel en actions sur l'Android.

La demande cible les capacités suivantes :

- `1 container -> 1 Android`
- installation d'APK
- vue écran en direct dans le navigateur
- contrôle distant
- interface conversationnelle
- API documentée avec Swagger

## 2. Conclusion Exécutive

Le besoin est faisable, mais pas proprement sous la forme d'une seule image Docker monolithique. La bonne approche est un projet unique `Emulytix` composé de plusieurs services conteneurisés :

- un service `android-runtime`
- un service `orchestrator-api`
- un service `web-ui`
- éventuellement un service `llm-agent`
- éventuellement un reverse proxy

Le candidat le plus simple pour l'émulateur web est `budtmo/docker-android`, car il fournit déjà :

- un émulateur Android
- une exposition web via noVNC
- un contrôle via `adb`

En revanche, il dépend fortement de `KVM` et donc de `/dev/kvm` sur l'hôte. Sur le serveur actuel, `/dev/kvm` n'est pas présent. En l'état, cela bloque ou dégrade fortement cette option.

Ma meilleure recommandation produit est donc :

1. cible technique principale : `budtmo/docker-android` sur un hôte compatible `KVM`
2. architecture Emulytix en multi-services autour de cet Android
3. si le serveur actuel doit être utilisé sans changer l'infrastructure : solution alternative managée type `Genymotion`

## 3. Constat sur le serveur actuel

Vérifications locales effectuées :

- `CPU` expose des flags de virtualisation (`vmx`)
- `/dev/kvm` est absent

Interprétation :

- la machine hôte ou l'hyperviseur supporte probablement la virtualisation
- mais la virtualisation imbriquée n'est pas exposée à cet OS
- un conteneur d'émulateur Android accéléré matériellement n'est donc pas garanti

Conséquence :

- `budtmo/docker-android` n'est pas un bon choix de déploiement sur ce serveur précis tant que `KVM` n'est pas disponible

## 4. Évaluation de `budtmo/docker-android`

### Points forts

- projet connu et largement utilisé
- exposition web simple via `noVNC`
- accès `adb`
- persistance possible via volume
- bon candidat pour un MVP

### Limites

- dépendance à `KVM`
- architecture web basée sur `noVNC`, correcte pour l'exploitation mais pas optimale pour une UX moderne
- versions Android récentes limitées dans la version standard
- pas pensé nativement comme plateforme API-first avec orchestration multi-session

### Verdict

`budtmo/docker-android` est un bon moteur d'exécution Android pour le MVP `Emulytix`, mais pas la plateforme complète. Il doit être encapsulé dans une architecture plus large.

Point important ajouté après implémentation :

- la vue Android dans Emulytix ne doit pas être couplée à `budtmo`
- le frontend doit consommer une simple URL d'embed Android
- cela permet de garder aujourd'hui `budtmo` pour Android 14, puis de remplacer plus tard le provider d'affichage ou d'exécution sans refaire le chat

## 5. Vision Produit Emulytix

`Emulytix` doit être conçu comme une plateforme d'exécution et de pilotage Android assistée par langage naturel.

### Cas d'usage visés

- lancer un Android vierge ou préconfiguré
- installer un APK métier
- visualiser l'écran Android en direct
- piloter l'écran à distance
- envoyer des commandes en langage naturel
- observer l'état du device
- récupérer captures, logs et résultats
- intégrer le tout via API

### Cibles d'usage

- QA manuelle augmentée
- démonstration produit
- exécution de scénarios semi-automatisés
- support opérationnel
- analyse de comportement applicatif

## 6. Architecture Recommandée

### 6.1 Vue d'ensemble

Architecture recommandée :

- `android-runtime`
- `orchestrator-api`
- `web-ui`
- `agent-service`
- `reverse-proxy`
- `storage`

### 6.2 Rôle de chaque composant

#### `android-runtime`

Responsabilités :

- démarrer l'émulateur Android
- exposer l'écran via web
- exposer `adb`
- installer les APK
- permettre les interactions tactiles

Implémentation recommandée :

- base initiale : `budtmo/docker-android`
- ports typiques : `6080`, `5554`, `5555`
- volume de persistance : `/home/androidusr`
- contrat à stabiliser côté Emulytix : exposer une URL web embarquable dans le chat, plus l'accès `adb`

#### `orchestrator-api`

Responsabilités :

- créer, démarrer, arrêter, supprimer des sessions Android
- installer des APK
- relayer des commandes tactiles ou système
- exposer l'état du device
- produire une API OpenAPI/Swagger
- sécuriser l'accès

Technos recommandées :

- `FastAPI` ou `NestJS`
- Swagger natif via `OpenAPI`
- client Docker pour gérer les conteneurs
- interface `adb` pour le contrôle device

#### `web-ui`

Responsabilités :

- interface type ChatGPT
- panneau de conversation
- écran Android intégré
- journal des actions
- vue session / device / APK

Technos recommandées :

- `Next.js`
- `React`
- `Tailwind` ou CSS custom
- `WebSocket` ou `SSE` pour les événements temps réel

#### `agent-service`

Responsabilités :

- transformer le langage naturel en plan d'actions
- appeler l'API de contrôle Android
- demander confirmation pour les actions sensibles
- garder un historique des intentions et résultats

Technos recommandées :

- service Python ou Node séparé
- appels LLM externes
- boucle d'exécution tool-based

#### `reverse-proxy`

Responsabilités :

- exposer le front
- exposer l'API
- publier la vue Android
- gérer TLS et authentification éventuelle

Technos recommandées :

- `Traefik` ou `Nginx`

## 7. Pourquoi il ne faut pas faire une seule image

Une seule image contenant Android, backend API, frontend web, reverse proxy et agent IA poserait plusieurs problèmes :

- cycle de build trop lourd
- debug difficile
- scaling impossible par composant
- couplage fort entre UI, orchestration et runtime Android
- maintenance médiocre

Le bon compromis est :

- un dossier produit unique `Emulytix`
- une stack `docker compose`
- plusieurs images spécialisées

## 8. Proposition de structure projet

```text
Emulytix/
  study.md
  docker-compose.yml
  .env
  docs/
  android-runtime/
    Dockerfile
    scripts/
  orchestrator-api/
    Dockerfile
    app/
    openapi/
  web-ui/
    Dockerfile
    src/
  agent-service/
    Dockerfile
    app/
  infra/
    nginx/
    traefik/
  storage/
```

## 9. Interface Web de type ChatGPT

### 9.1 Objectif UX

L'utilisateur doit pouvoir :

- voir l'écran Android
- discuter avec l'assistant
- donner une instruction naturelle
- suivre les actions exécutées
- reprendre la main directement

### 9.2 Layout recommandé

Interface en trois zones :

- colonne gauche : historique des sessions / devices / APK
- zone centrale : conversation type ChatGPT
- panneau droit : écran Android en direct + commandes rapides

### 9.3 Capacités de l'interface

- chat temps réel
- streaming de réponse assistant
- affichage des étapes d'action
- vue Android embarquée
- boutons rapides : `Home`, `Back`, `Recent`, `Install APK`, `Screenshot`, `Restart App`
- affichage des erreurs et confirmations

### 9.4 Logique conversationnelle

Exemples d'instructions :

- "Installe cet APK et ouvre l'application"
- "Va dans les paramètres et active le Wi-Fi"
- "Lance l'app puis connecte-toi avec ce compte"
- "Prends une capture après l'écran d'accueil"

Le système doit convertir ces intentions en commandes atomiques :

- upload APK
- `adb install`
- `adb shell input tap`
- `adb shell input text`
- `adb shell monkey`
- screenshot

## 10. Vue Android dans le navigateur

### Option MVP

Utiliser la vue web fournie par `budtmo/docker-android` via `noVNC`.

Avantages :

- rapide à intégrer
- déjà disponible
- peu de développement initial

Inconvénients :

- UX moyenne
- latence supérieure à une intégration plus moderne
- contrôle visuel dépendant de l'iframe / VNC

### Option cible

Créer un composant frontend dédié qui encapsule le flux d'écran Android et affiche :

- état du device
- capture en direct
- overlays d'action
- coordonnées cliquées
- logs utilisateur

À terme, si besoin de meilleure fluidité, remplacer la couche d'affichage par une solution `WebRTC`.

## 11. API exposée

### Exigence

Il faut une API claire, stable et documentée.

### Recommandation

Utiliser `FastAPI`, car cela fournit :

- Swagger UI automatique
- OpenAPI JSON
- validation stricte
- rapidité de développement

### Endpoints MVP proposés

#### Sessions

- `POST /sessions`
- `GET /sessions`
- `GET /sessions/{id}`
- `DELETE /sessions/{id}`
- `POST /sessions/{id}/start`
- `POST /sessions/{id}/stop`

#### APK

- `POST /sessions/{id}/apk`
- `POST /sessions/{id}/apk/install`
- `GET /sessions/{id}/apk`

#### Device Control

- `POST /sessions/{id}/device/tap`
- `POST /sessions/{id}/device/swipe`
- `POST /sessions/{id}/device/text`
- `POST /sessions/{id}/device/key`
- `POST /sessions/{id}/device/open-app`
- `POST /sessions/{id}/device/screenshot`

#### Observabilité

- `GET /sessions/{id}/status`
- `GET /sessions/{id}/screen`
- `GET /sessions/{id}/logs`
- `GET /sessions/{id}/packages`

#### Agent

- `POST /sessions/{id}/chat`
- `GET /sessions/{id}/chat/history`
- `POST /sessions/{id}/agent/plan`
- `POST /sessions/{id}/agent/execute`

### Documentation

Publier :

- Swagger UI : `/docs`
- OpenAPI JSON : `/openapi.json`

## 12. Contrôle Android via API

### Moteurs d'action

Le backend devra utiliser plusieurs couches :

- Docker API pour la gestion des conteneurs
- `adb` pour les commandes Android
- éventuellement OCR / vision pour localiser des éléments à l'écran

### Niveaux de commande

#### Niveau 1 : commandes déterministes

- installer un APK
- lancer une activité
- taper du texte
- appuyer sur un bouton système

#### Niveau 2 : commandes visuelles

- cliquer à des coordonnées
- cliquer sur une zone détectée
- faire défiler

#### Niveau 3 : commandes sémantiques

- "ouvre l'application X"
- "connecte-toi"
- "va sur la page profil"

Le niveau 3 nécessite une couche agent / vision / heuristiques.

## 13. Langage naturel -> actions Android

### Pipeline recommandé

1. l'utilisateur saisit une instruction
2. le frontend envoie la demande à `agent-service`
3. l'agent produit un plan d'action structuré
4. le plan est validé automatiquement ou avec confirmation
5. `orchestrator-api` exécute les actions
6. les résultats sont renvoyés à l'UI

### Format de plan recommandé

```json
{
  "goal": "Installer et ouvrir une application",
  "steps": [
    {"tool": "upload_apk", "args": {"name": "app.apk"}},
    {"tool": "install_apk", "args": {}},
    {"tool": "launch_app", "args": {"package": "com.example.app"}}
  ]
}
```

### Règles importantes

- imposer des outils stricts
- interdire toute exécution shell libre côté agent
- journaliser toutes les actions
- exiger confirmation pour suppression, reset, factory reset, shell root

## 14. Sécurité

### Risques

- exposition du contrôle Android sur Internet
- APK malveillants
- fuite de captures d'écran
- exécution de commandes non maîtrisées
- accès non autorisé à l'API

### Mesures minimales

- authentification sur UI et API
- HTTPS obligatoire
- isolation réseau des runtimes Android
- quotas par session
- scan ou validation des APK uploadés
- journalisation complète
- rôles `admin` / `operator` / `viewer`

## 15. Persistance et stockage

À prévoir :

- volume par session Android
- stockage des APK uploadés
- stockage des screenshots
- stockage des logs
- stockage de l'historique conversationnel

Recommandation :

- `PostgreSQL` pour la métadonnée
- stockage objet compatible `S3` pour les fichiers

## 16. Observabilité

Le produit doit exposer :

- statut de session
- logs d'installation APK
- latence de l'émulateur
- disponibilité des services
- historique des actions agent

Outils possibles :

- `Prometheus`
- `Grafana`
- `Loki`

## 17. Scénarios de déploiement

### Scénario A : MVP local sur hôte KVM

- `docker-compose`
- un seul Android
- API + UI + agent
- accès restreint

C'est le meilleur point de départ.

### Scénario B : multi-sessions

- plusieurs conteneurs Android
- scheduler de capacité
- files d'attente
- observabilité renforcée

### Scénario C : serveur actuel sans KVM

Sur ce serveur, deux options réalistes :

- migrer Emulytix vers un hôte avec `KVM`
- remplacer le runtime Android local par une solution distante type `Genymotion`

## 18. MVP recommandé

### Périmètre MVP

- 1 session Android
- `budtmo/docker-android`
- API `FastAPI`
- Swagger
- UI `Next.js`
- chat simple
- installation APK
- commandes de base
- screenshot

### Hors MVP

- multi-tenant avancé
- vision avancée
- auto-healing
- orchestration cluster
- fine-grained policy engine

## 19. Roadmap proposée

### Phase 1

- structuration repo
- `docker-compose`
- runtime Android
- API de contrôle minimale
- Swagger

### Phase 2

- UI type ChatGPT
- intégration vue Android
- upload APK
- logs d'action

### Phase 3

- agent langage naturel
- plan d'action structuré
- confirmations
- screenshots commentés

### Phase 4

- multi-session
- auth complète
- observabilité
- quotas et sécurité avancée

## 20. Recommandation finale

La bonne décision pour `Emulytix` est :

- ne pas construire une unique image "qui contient tout"
- construire un produit multi-services dans un seul dossier projet
- utiliser `budtmo/docker-android` comme runtime Android MVP
- prévoir une abstraction `AndroidRuntimeProvider` pour pouvoir remplacer plus tard le moteur d'exécution
- exiger un hôte avec `KVM` pour le runtime Android local

Sur le serveur actuel, la partie Android locale n'est pas le bon point de départ tant que `/dev/kvm` n'est pas disponible.

## 21. Stack cible recommandée

- `android-runtime`: `budtmo/docker-android`
- `orchestrator-api`: `FastAPI`
- `web-ui`: `Next.js`
- `agent-service`: Python
- `database`: `PostgreSQL`
- `reverse-proxy`: `Traefik` ou `Nginx`
- `docs`: Swagger / OpenAPI

## 22. Décision d'architecture

Décision recommandée :

- Produit : `Emulytix`
- Packaging : `docker compose`
- UI : interface conversationnelle + écran Android
- API : `FastAPI` + Swagger
- Runtime Android : `budtmo/docker-android` sur hôte `KVM`

## 23. Sources

- `budtmo/docker-android` : https://github.com/budtmo/docker-android
- `Android adb` : https://developer.android.com/tools/adb
- `Genymotion SaaS` : https://docs.genymotion.com/saas/
- `Genymotion application deployment` : https://docs.genymotion.com/paas/041_Installing_applications/
- `google/android-emulator-container-scripts` : https://github.com/google/android-emulator-container-scripts
- `google/android-emulator-webrtc` : https://github.com/google/android-emulator-webrtc

## 24. Décision pratique pour la suite

Si la suite attendue est une implémentation, l'ordre conseillé est :

1. créer le squelette `Emulytix`
2. écrire le `docker-compose.yml`
3. créer `orchestrator-api` avec Swagger
4. intégrer l'UI de type ChatGPT
5. brancher un runtime Android compatible

Sur ce serveur, je recommande de commencer par les composants non bloqués :

- `web-ui`
- `orchestrator-api`
- `swagger`
- `agent-service`

Puis de brancher le runtime Android dès qu'un hôte `KVM` est disponible.
