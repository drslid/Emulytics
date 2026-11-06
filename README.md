# Emulytix

Console de pilotage d’une flotte d’appareils mobiles : téléphones, automatisations versionnées, exécutions et preuves. Interface claire inspirée des outils Google, avec connexion par mot de passe et second facteur obligatoire. Le moteur actuel pilote Android ; l’intégration iOS est prévue.

## Démarrer la console locale

```bash
scripts/start-console.sh
```

Ouvrir **http://localhost:3100**. Le script crée `.env.console` avec des secrets aléatoires si ce fichier n’existe pas, démarre PostgreSQL privé, applique les migrations, construit les services API Python/Go, l’ordonnanceur et le frontend, puis publie WF01 dans le catalogue. Sur une installation vierge, il prépare aussi le compte `admin` et un mot de passe temporaire unique. Les secrets de configuration et le mot de passe initial ne sont pas régénérés lors d’un redémarrage.

La stack utilise le projet Compose `emulytix-preview`, ses propres conteneurs et son volume PostgreSQL. Aucun service MobileAgent sur les ports 8080/8443 n’est modifié. Seul le frontend publie un port, limité à `127.0.0.1:3100` ; API et base restent privées. Aucun socket Docker ni accès direct ADB n’est donné à l’API de la console.

### Première connexion après installation

L’accès initial est créé automatiquement. Pour retrouver l’identifiant `admin` et le mot de passe temporaire fourni à cette installation :

```bash
scripts/account.sh initial-access
```

Ces informations sont conservées dans le fichier local `storage/install/initial-access.json`, avec un dossier accessible uniquement à son propriétaire (`700`) et un fichier privé (`600`). Ce fichier reste hors Git et n’est pas servi par le site.

Le premier accès suit ce parcours obligatoire :

1. Saisir le mot de passe temporaire du compte `admin` sur la page de connexion.
2. Choisir et confirmer un nouveau mot de passe personnel, différent du mot de passe temporaire et contenant au moins 12 caractères.
3. Scanner le QR avec Google Authenticator, 2FAS ou une autre application TOTP, puis confirmer un code à six chiffres.
4. Conserver les dix codes de secours affichés une seule fois, puis ouvrir la console.

Le mot de passe temporaire ne donne accès ni au parc ni aux captures. Le changement de mot de passe précède l’enrôlement 2FA, et l’accès métier reste fermé jusqu’à validation du code. Après le changement, le mot de passe temporaire et l’ancien challenge deviennent inutilisables. Les connexions suivantes utilisent le mot de passe personnel puis un code de l’application d’authentification, ou un code de secours inutilisé.

Les comptes existants sont conservés. Un marqueur persistant empêche l’installateur de recréer automatiquement un compte après sa suppression ou un redémarrage. La création interactive reste disponible pour les comptes supplémentaires :

```bash
scripts/account.sh create mon_identifiant
```

La session dure huit heures et la déconnexion la révoque côté serveur. En cas de perte du second facteur et de tous les codes de secours, l’administrateur de l’hôte peut réinitialiser le 2FA :

```bash
scripts/account.sh reset-2fa mon_identifiant
```

Cette commande révoque les sessions et les codes précédents et impose un nouvel enrôlement. Sauvegarder `.env.console` avec la base : sa clé `EMULYTIX_AUTH_KEY` permet de déchiffrer les secrets TOTP. Sa perte ne se résout pas en générant une nouvelle clé.

### Utiliser la console

- **Tableau de bord** : synthèse du parc, histogramme d’activité quotidienne sur sept jours calendaires dans le fuseau du navigateur, répartition des résultats et capacité actuelle. Les graphiques comptent les exécutions par appareil ; les indicateurs du haut comptent les lancements. Les effectifs et le tableau de données restent accessibles, avec signalement des mesures périmées et des connexions non confirmées.
- **Appareils** : création d’émulateurs persistants, choix des applications, import d’APK, démarrage/préparation, arrêt et lancement d’un parcours. Les appareils déjà existants se connectent séparément. Les noms acceptent les espaces et les identifiants sont générés automatiquement ; une déclaration seule ne prouve aucune connexion.
- **Parcours** : instructions, étapes visuelles ou JSON avancé, modèles, brouillons et versions publiées immuables. « Modifier les étapes » ouvre le brouillon courant, y compris pour le parcours Wikipédia fourni : modifier les paramètres et vérifications, ajouter, dupliquer, déplacer ou supprimer une étape, puis « Enregistrer le brouillon » et « Publier » pour créer la version suivante. Les anciennes exécutions et planifications conservent leur version.
- **Exécutions** : lancement immédiat, lot explicite et suivi par appareil. Ouvrir un parcours en cours affiche automatiquement son écran Android en direct à côté des captures qui arrivent étape par étape. Un seul direct est ouvert à la fois dans le détail ; les captures suivent la version exécutée, avec aperçu agrandi, clavier, image originale, heure et durée. Le direct s’arrête à la fin, les captures et le journal restent consultables. Une demande d’arrêt reste distincte de son résultat confirmé.
- **Planifications** : jour/semaine/mois ou CRON avancé, fuseau IANA, aperçu des cinq prochaines dates, pause/reprise. L'ordonnanceur démarre automatiquement ; un worker connecté reste nécessaire à l'exécution.
- **Monitoring** : file et ancienneté de l’attente, workers occupés, appareils réellement prêts, résultats sur 1 h/24 h/7 jours et durées médiane/p95. CPU et RSS des processus Python, sonde et statistiques PostgreSQL, instances actuelles et anciennes. Le flux partagé expire côté navigateur après dix secondes sans message ; les heartbeats deviennent périmés après vingt secondes. Les définitions, sources et limites sont détaillées dans l’[étude du monitoring](docs/monitoring-study.md).
- **Journal** : événements d'exécution et d'administration, pagination, recherche, catégories et niveaux, sans secrets ni corps des requêtes.
- **Utilisateurs** : annuaire avec recherche, filtres et fiche détaillée ; nom, prénom, e-mail de contact, rôle, activation et actions de sécurité. Réservé à Admin ; les nouveaux comptes changent leur mot de passe et activent TOTP.
- **Mon profil** : modification de son identité et de son e-mail de contact, rôle, langue et section Sécurité du compte intégrée, avec mot de passe, second facteur, session et déconnexion. Petits drapeaux, dix langues détectées depuis le navigateur et arabe RTL.
- **Banc de validation** : les deux réussites WF01 archivées restent disponibles sur `/validation`.

| Rôle de référence | Autorisations |
|---|---|
| Admin | Toute la console, utilisateurs et sécurité |
| Builder | Créer/publier les parcours, lancer/planifier/arrêter les exécutions, consulter le parc et le monitoring |
| Operator | Gérer les appareils, lancer/planifier/arrêter les parcours publiés |
| Viewer | Consulter le parc, les parcours publiés, résultats, planifications et monitoring |
| Auditor | Lecture, avec accès supplémentaire aux journaux et à la traçabilité |

Les noms de rôles sont traduits ; les identifiants serveur restent stables. Les droits sont vérifiés sur chaque requête et avant chaque échéance. Le dernier Admin opérationnel, actif avec un mot de passe personnel et un 2FA confirmé, doit être conservé. Un compte Admin encore en cours d'activation ne suffit pas à le remplacer. Les clés personnelles, l'API publique et le MCP appartiennent à une prochaine tranche.

La console n’invente aucune flotte de démonstration. Le catalogue WF01 est préchargé ; les téléphones et les runs sont ceux enregistrés dans cette base. Sans worker sur l’hôte ciblé, une nouvelle exécution reste en attente. Le worker Android et son banc sont documentés plus bas. Les anciens contrôles directs APK/chat/ADB sont désactivés dans cette stack.

Pour préparer un Android local réellement exécutable après le démarrage de la console :

```bash
scripts/start-console-android.sh
```

Le script crée le banc privé s'il est absent, ou vérifie le banc existant sans le remplacer. Il attend un Android démarré, enregistre **Émulateur local** sous `bench-host` / `emulator-5554` (ou réutilise l'appareil déjà enregistré pour cette connexion), puis démarre le worker et vérifie son accès ADB. Les déclarations d'autres hôtes et leurs demandes ne sont pas modifiées. La commande peut être relancée tant que le banc est actif ; elle refuse de remplacer un conteneur étranger ou arrêté.

Dans **Appareils**, choisir cet émulateur, puis lancer **Recherche Wikipédia**. Le helper ne crée aucun run ; le worker peut toutefois reprendre les demandes déjà en attente pour `bench-host`. Un téléphone déclaré avec un autre hôte ou un autre numéro Android nécessite sa propre connexion réelle : son nom ne suffit pas à le rattacher au banc.

L’ajout d’un appareil propose les hôtes dont un worker `ready` répond depuis moins de vingt secondes, même si aucun appareil n’y est encore déclaré. L’hôte unique est prérempli. « Aucun worker actif sur cet hôte » concerne uniquement l’hôte de la ligne, avec dernier signal connu ou absence de signal ; une ancienne déclaration ne prouve pas une panne du worker actuel. La connexion Android exige toujours une observation ADB du bon numéro sur le bon hôte.

Ce banc requiert `/dev/kvm` et l'image Android déjà présente localement `emulytix/android-runtime-check:0.8.1`. Il utilise Android 10 / Chrome 74, et ne représente pas la cible Android 14 du plan. Aucun port Android/ADB n'est publié. Après un arrêt de la console, réactivez ce profil avec le helper. Le démarrage normal de la console ne lance pas Android ; le helper active le profil facultatif `docker-compose.console-worker.yml`.

L’[étude de l’interface](docs/design/control-console.md) décrit les choix élément par élément ; l’[audit MobileAgent](docs/design/mobileagent-audit.md) détaille les idées reprises et leurs limites.

### Administrer les comptes

Dans **Utilisateurs**, un Admin crée un compte à partir du prénom, du nom facultatif, de l'e-mail et du rôle. Les espaces sont corrigés et les accents conservés. L'identifiant de connexion est proposé automatiquement ; si le même nom existe déjà, un suffixe distingue le nouveau compte. Un identifiant personnalisé reste possible. Le mot de passe temporaire est affiché une seule fois et impose un changement avant l'activation du 2FA.

La recherche et les filtres de rôle, d'activation, de 2FA et de première connexion portent sur tout l'annuaire, y compris les pages suivantes. La fiche d'un compte donne ses dates connues, ses sessions actives et le nombre de codes de secours restants. Les dates inconnues des anciens comptes restent vides. Modifier le rôle ou désactiver un compte ferme ses sessions et ses connexions en cours ; modifier uniquement son identité conserve ses accès.

| Action de sécurité | Effet |
|---|---|
| Réinitialiser le mot de passe | Génère un accès temporaire affiché une seule fois, ferme les sessions et impose un nouveau mot de passe ; le facteur existant reste configuré |
| Imposer un changement de mot de passe | Ferme les sessions et impose un nouveau mot de passe après saisie du mot de passe actuel |
| Réinitialiser le 2FA | Ferme les sessions, supprime l'ancien facteur et ses codes de secours, puis exige un nouvel enrôlement |
| Fermer les sessions | Révoque les sessions et les connexions en cours, en conservant le mot de passe et le facteur |

Les modifications d'accès sont revérifiées côté serveur dans la transaction. La protection du dernier Admin opérationnel s'applique aussi aux actions qui lui imposeraient une nouvelle activation. Un Admin gère son propre mot de passe et son propre facteur depuis **Mon profil** ; il peut fermer toutes ses sessions depuis sa fiche, ce qui le déconnecte aussi.

Chaque utilisateur peut modifier son prénom, son nom et son e-mail dans **Mon profil**. L'identifiant de connexion reste fixe. L'e-mail est un contact facultatif pour les comptes existants, unique sans distinction de casse, et sa syntaxe est validée. Cette adresse n'est pas vérifiée : aucun message n'est envoyé et elle ne sert ni d'identifiant de connexion ni de canal de récupération. Les changements d'identité sont tracés sans copier les noms ou adresses dans le journal.

### Gérer sa sécurité personnelle

Dans **Mon profil → Sécurité du compte**, chaque utilisateur peut changer son mot de passe, remplacer son application d'authentification et renouveler ses codes de secours. Ces actions demandent le mot de passe actuel et une confirmation par un facteur disponible. Le 2FA reste obligatoire.

Le remplacement affiche un QR temporaire lié à la session et conserve l'ancien facteur jusqu'à validation d'un code de la nouvelle application. Après activation, les anciens codes de secours sont remplacés. Les nouveaux codes ne sont affichés qu'une fois : les conserver avant de fermer le dialogue. Annuler conserve l'ancien facteur, mais un code de secours déjà utilisé reste consommé.

Changer son mot de passe ou son application d'authentification ferme les autres sessions et renouvelle la session courante. Le renouvellement des codes exige l'application d'authentification ; si elle est perdue, utiliser d'abord un code de secours pour changer d'application. Le dernier code disponible est réservé à cette récupération. Si aucun facteur n'est disponible, un administrateur peut réinitialiser l'accès depuis Utilisateurs ou les outils locaux.

### Observer et exécuter plusieurs parcours

Dans **Appareils → Créer un émulateur**, saisir son nom, choisir l’hôte et les applications, puis ouvrir sa fiche. Le catalogue propose Chrome, Snapchat, LinkedIn, Instagram et TikTok. Chrome est fourni par l’image ; les autres applications nécessitent leurs APK autonomes compatibles, à importer avec **Importer un APK**. Le nom du package est détecté automatiquement ; un fichier manquant reste signalé et empêche la préparation.

**Démarrer et préparer** démarre Android, installe les fichiers choisis et vérifie leur empreinte sur l’appareil. **Lancer un parcours** présélectionne cet émulateur après confirmation de sa connexion. **Arrêter l’émulateur** conserve son volume et ses données ; le redémarrage réutilise le même AVD. Décocher une application ne la désinstalle pas. La configuration et les opérations de gestion nécessitent Admin ou Operator ; Builder peut lancer un parcours sur un appareil prêt.

Cette tranche utilise l’image locale **Android 10 · x86_64**, avec quatre émulateurs configurables par hôte. Cette limite ne constitue pas une mesure de capacité simultanée. Le Play Store et les APK découpés en plusieurs fichiers ne sont pas intégrés. Le worker doit disposer du profil Compose Android, du réseau privé du banc et de l’image locale ; seul ce worker reçoit le socket Docker. Les nouvelles ressources ont leurs propres noms et volumes et ne remplacent pas le banc existant. Architecture et vérification : [émulateurs gérés](docs/managed-emulators.md).

Ouvrir **http://localhost:3100/activite**, puis le détail d’un parcours en cours. Le premier appareil actif affiche automatiquement son écran en direct, avec les captures des étapes dans le même détail. Sur un lot, « Voir en direct » change le téléphone observé ; « Masquer l’écran » reste mémorisé pendant les rafraîchissements. Le direct est lié à l’exécution et à son bail, et les images antérieures à son démarrage sont refusées. Après la fin, seules les captures du parcours restent proposées. Les anciens liens `/ecrans` redirigent vers Exécutions après contrôle de la connexion.

L’observation reste en lecture seule, à environ une image par seconde. Une image ancienne est marquée figée. Fermer le détail ou masquer l’onglet arrête les requêtes ; la demande de capture expire ensuite. Le détail et les captures d’un parcours actif sont actualisés environ toutes les deux secondes. Chaque image exige une session et des droits de consultation ; aucun port Android public n’est ajouté.

Chaque processus worker exécute un parcours à la fois et un téléphone ne reçoit qu'une exécution active. Avec un émulateur et un worker, les demandes sont traitées en série. Plusieurs appareils et workers permettent davantage d'exécutions simultanées, selon les limites du lot et les ressources disponibles. Cent appareils par demande est une borne du contrat, pas un résultat de charge sur cette machine.

Les quatre demandes initiales ont été reprises sur l'émulateur réel, avec des événements reliant les historiques. Le [script de reprise](docs/architecture/replaying-local-backlog.md) est spécifique à ces quatre demandes et utilise des clés stables.

### Arrêter ou relancer

```bash
docker compose --env-file .env.console -p emulytix-preview -f docker-compose.preview.yml down
scripts/start-console.sh
```

Ne pas ajouter `--volumes` pour conserver les comptes, appareils et runs. Les preuves locales sont montées en lecture seule : `storage/wf01-worker` pour le banc historique et `storage/runs` pour les exécutions courantes. Les captures arbitraires du stockage ne sont pas exposées.

### Configuration de sécurité

Les cookies sont HttpOnly / SameSite Strict. Le mode HTTP avec cookies non Secure est limité au localhost explicitement configuré. Pour un accès par réseau ou domaine, utiliser HTTPS, fixer `EMULYTIX_PUBLIC_ORIGIN` à l’origine exacte et `EMULYTIX_COOKIE_SECURE=true`, puis placer la console derrière un reverse proxy TLS. L’origine `http://localhost:3100` doit être utilisée telle quelle en local : `127.0.0.1` est une autre origine.

Les mots de passe sont hachés avec Argon2, les secrets TOTP chiffrés, les sessions et codes de secours stockés sous forme d’empreintes. Le contrôle anti-rejeu TOTP, les challenges de cinq minutes et les limites de tentatives sont persistés dans PostgreSQL. Derrière le BFF, le plafond IP de 50 tentatives par 15 minutes couvre actuellement tous les opérateurs de l’instance ; la limite par compte est distincte (10 tentatives). Les comptes partagent le même espace : les cinq rôles contrôlent les actions ; l’isolation entre clients reste à implémenter.

Le navigateur passe par `/api/control/*`, sans jeton Bearer de service. Les pages, l’API, les anciennes routes et les captures sont contrôlées côté serveur. Les appels de scripts existants peuvent conserver leur Bearer, injecté hors du navigateur. Le monitoring diffuse les mesures par SSE et revalide la session pendant le flux. Les événements des exécutions sont actualisés périodiquement. Le contrôle vidéo Android en direct reste un lot du [plan](PLAN.MD).

## Répertoires

- `web-ui` : console Next.js, formulaires de connexion/2FA et BFF de même origine.
- `orchestrator-api` : API FastAPI, authentification, catalogue, stockage PostgreSQL et worker Android.
- `console-api-go` : premières lectures HTTP migrées vers Go : résumé, flotte et agrégats du tableau de bord ; authentification déléguée à l’autorité de session existante.
- `workflows` : versions exécutables des parcours déterministes.
- `android-runtime` : banc émulateur et wrapper de runtime.
- `agent-service` : ancien planificateur conversationnel, non requis par la console déterministe.

La [revue de stack](docs/architecture-stack-review.md) décrit cette migration et la file PostgreSQL existante. Les formulaires et mutations restent sur leurs services actuels ; la migration Go ne modifie pas les comptes, versions de parcours ou baux du worker. La [revue responsive](docs/responsive-review.md) décrit l’adoption progressive de Tailwind et la compatibilité navigateur.

## Développement et vérification

### Logo et raccourcis mobiles

L’identité Emulytix utilise un monogramme coloré, indépendant d’un système mobile. Les choix et contrôles sont décrits dans l’[étude de marque](docs/design/brand-identity.md). L’[image maîtresse](design/brand/emulytix-master.png) est conservée avec son [prompt de création](design/brand/prompt.txt).

Le logo de l’interface et les favicons sont dans `web-ui/public/brand` et `web-ui/public/icons`. Le fichier ICO contient les tailles 16, 32 et 48 ; `apple-touch-icon.png` est une image opaque de 180 px. Le manifeste `/manifest.webmanifest` référence les PNG 192/512 et une variante `maskable` séparée, dont le signe reste dans la zone centrale sûre. Ces ressources publiques ne donnent aucun accès aux données de la console.

Pour régénérer les tailles à partir de la source, avec ImageMagick (`convert` et `identify`) installé sur le poste de développement :

```bash
node scripts/export-brand.mjs
```

Le manifeste et les icônes préparent les raccourcis d’écran d’accueil. L’instance locale reste limitée au localhost de cet ordinateur ; un essai sur téléphone physique demande une URL HTTPS accessible et l’origine d’authentification correspondante. Aucun cache hors ligne de données privées n’a été ajouté.

### Application

```bash
cd web-ui
npm ci
npm test
npm run build
```

La suite backend utilise des bases PostgreSQL jetables isolées :

```bash
.venv/bin/python -m pytest orchestrator-api/tests -q
```

Les fichiers `docker-compose.yml` et `docker-compose.runtime.yml` conservent les profils historiques et le banc worker. Le déploiement console ci-dessus utilise une base distincte : ne pas supposer que les données d’un autre projet Compose y sont importées.

## Première tranche : runs persistants

La première tranche du [plan](PLAN.MD) ajoute une API PostgreSQL pour déclarer des appareils, enregistrer des versions immuables de workflows, créer des runs idempotents, consulter leurs exécutions et événements, et annuler les runs encore en attente.

Les appareils déclarés ne sont pas considérés comme connectés. Les runs restent `queued` tant qu'aucun worker du bon hôte n'est lancé. Le worker local décrit ci-dessous peut maintenant les exécuter sur un appareil ciblé. Les événements se consultent en JSON paginé ; le flux SSE sera ajouté ensuite.

Le premier parcours métier demandé est décrit dans [WF01 : Chrome → Wikipédia → recherche football](docs/workflows/WF01-chrome-wikipedia-football.md), avec une [version exécutable](workflows/chrome-wikipedia-football.v1.json). Pour l'instant, utiliser des métadonnées de banc sans secrets : les paramètres sont stockés dans PostgreSQL, et le coffre n'est pas encore intégré.

### Activer PostgreSQL et appliquer les migrations

Le mode historique démarre avec `EMULYTIX_DATABASE_URL` vide. Pour les appels de scripts, les routes de contrôle requièrent une URL PostgreSQL et un jeton `EMULYTIX_CONTROL_TOKEN` ; la console décrite plus haut utilise sa session après 2FA. Le profil Compose `runs` ajoute PostgreSQL 17 avec un volume persistant, sans publier son port sur l'hôte.

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
