# Revue de la stack et de la file PostgreSQL

État inspecté et première tranche déployée le 6 novembre 2026. Cette note distingue les lectures déjà migrées des domaines qui restent à transférer ; aucun historique n’est réécrit.

## Ce qui existe

| Couche | Implémentation observée | Conséquence |
| --- | --- | --- |
| Interface | React 19 avec Next.js 15, TypeScript, CSS du projet et adoption progressive de Tailwind 4 | React est déjà utilisé ; Tailwind est ajouté au cadre responsive et au menu mobile sans remplacer React. |
| API | Go pour le résumé, la flotte et les agrégats du tableau de bord ; Python/FastAPI pour les autres domaines | La migration est engagée par lectures, avec vérification de compatibilité avant chaque bascule. |
| File d’exécution | Tables PostgreSQL `runs`, `executions`, `device_leases`, `run_events`, `action_journal` | Les demandes et leur progression sont durables ; aucun broker externe n’est nécessaire au fonctionnement actuel. |
| Traitement | Worker Android et ordonnanceur CRON séparés de l’API | Migrer l’API HTTP ne nécessite pas de réécrire simultanément le moteur Android. |

Sources locales : [package.json](../web-ui/package.json), [run_store.py](../orchestrator-api/app/run_store.py), [execution_store.py](../orchestrator-api/app/execution_store.py), [worker.py](../orchestrator-api/app/worker.py), [automation_store.py](../orchestrator-api/app/automation_store.py), [scheduler.py](../orchestrator-api/app/scheduler.py) et [configuration PostgreSQL](../docker-compose.preview.yml).

## La file utilise déjà les mécanismes PostgreSQL

La création d’une demande écrit le run, ses exécutions et son premier événement dans une transaction. Une clé d’idempotence unique retrouve la demande après un résultat réseau incertain et refuse sa réutilisation avec un autre contenu.

Le worker cherche jusqu’à dix candidats de son hôte, triés par ancienneté. L’attribution verrouille le run avec `FOR UPDATE SKIP LOCKED`, relit l’exécution, vérifie le plafond de concurrence, puis verrouille le bail de l’appareil. La transaction réserve un propriétaire, une époque et une expiration. Les actions Android s’exécutent après cette transaction ; leurs confirmations revérifient le bail. L’ordonnanceur utilise également `FOR UPDATE SKIP LOCKED`. Son identifiant dérivé du planning et de l’échéance permet de retrouver le même run après un crash précédant l’avancement du curseur.

PostgreSQL documente explicitement l’emploi de `SKIP LOCKED` pour limiter la contention entre consommateurs d’une table servant de file. Cette option ne constitue pas une garantie générale d’ordre FIFO strict. [Documentation PostgreSQL 17 — SELECT](https://www.postgresql.org/docs/17/sql-select.html).

Les protections métier dépassent la réservation d’un message : un appareil conserve un seul propriétaire, les écritures anciennes sont refusées par l’époque du bail, et une action incertaine ou un bail expiré conduit à une vérification humaine avec quarantaine. Le système ne revendique pas une exécution physique « exactement une fois » en présence de panne.

La lecture du code et des tests ne relève pas de défaut étayé de double attribution. Des tests existants couvrent huit claims concurrents pour une exécution, des runs concurrents ciblant un même téléphone, le plafond par run, les écritures après expiration et la reprise du dispatcher. Le filtrage des runs saturés avant la limite de candidats est déjà testé. Références : [tests d’exécution](../orchestrator-api/tests/test_execution_store.py), [tests worker](../orchestrator-api/tests/test_worker.py), [tests d’automatisation](../orchestrator-api/tests/test_automation.py).

## Ce que peuvent apporter LISTEN/NOTIFY et PGMQ

Il faut préciser le mécanisme visé lorsqu’on parle de « queue PostgreSQL » : la version déployée fournit tables, transactions et verrous ; le projet n’utilise pas de commande SQL native `QUEUE` ni de bibliothèque de messagerie additionnelle.

Aujourd’hui, un worker inoccupé sonde environ chaque seconde ; l’ordonnanceur passe environ toutes les cinq secondes. `LISTEN/NOTIFY` pourrait réveiller le worker après commit pour réduire les sondages et le délai d’attente. Les tables resteraient la source durable et une sonde périodique resterait nécessaire après déconnexion ou notification manquée. Au démarrage, il faudrait valider `LISTEN`, puis inspecter les travaux présents, afin de couvrir la course d’abonnement documentée. Les notifications ne doivent transporter aucun secret. [PostgreSQL 17 — LISTEN](https://www.postgresql.org/docs/17/sql-listen.html), [NOTIFY](https://www.postgresql.org/docs/17/sql-notify.html).

PGMQ est une option additionnelle de messagerie sur PostgreSQL, installable comme extension ou comme objets SQL. Il fournit notamment fenêtres de visibilité et archivage. Sa garantie de livraison pendant une fenêtre de visibilité ne garantit pas qu’un geste Android produise son effet une seule fois après un crash. Une intégration devrait conserver les identifiants durables, le fencing, le verrou par appareil et les règles de quarantaine existants. [Documentation officielle PGMQ](https://pgmq.github.io/pgmq/latest/).

**Proposition :** conserver la file PostgreSQL actuelle, mesurer les délais et requêtes sous charge, puis ajouter un réveil `LISTEN/NOTIFY` si ces mesures le justifient. Évaluer PGMQ sur une base jetable si une API de messagerie standardisée devient un besoin ; son installation n’est pas nécessaire pour disposer d’une file PostgreSQL durable.

## Première tranche API Go en service

Le service privé `console-go-api` implémente `GET /console/summary`, `GET /console/fleet` et `GET /console/dashboard`. Il lit directement PostgreSQL avec pgx et un pool borné. Le proxy Next.js lui adresse uniquement ces trois lectures lorsque `EMULYTIX_GO_API_INTERNAL_URL` est configuré. Aucune panne ne provoque une bascule silencieuse vers un autre backend. Pour les deux routes historiques, retirer cette configuration rétablit les lectures Python ; les nouveaux graphiques nécessitent leur agrégat Go.

Chaque requête Go transmet uniquement le cookie de session à `/auth/me` sur l’autorité Python, puis vérifie la permission requise. Aucun jeton de service ou en-tête d’identité fourni par le navigateur n’est utilisé. Les rôles et révocations ne sont pas mis en cache. Le Go ne reçoit ni clé de chiffrement 2FA ni jeton de contrôle. Les mutations, l’authentification, les captures, le monitoring détaillé, le worker et l’ordonnanceur restent dans leurs composants existants.

Les timestamps des lectures migrées conservent la représentation UTC du contrat HTTP observé, les champs absents restent `null` et les listes vides restent des tableaux. La flotte garde ses vérifications hôte/numéro Android et son seuil de fraîcheur de vingt secondes. L’agrégat du tableau de bord compte toutes les fins d’exécution des sept dates civiles, sans échantillonnage ni limite de cent lancements. Les transitions de fuseau à minuit sont couvertes, y compris date répétée ou sautée.

Le conteneur est sans port hôte, non privilégié, sans écriture de système de fichiers et sans capacités Linux supplémentaires. Son healthcheck sonde PostgreSQL. Un heartbeat `api-go` apparaît dans Monitoring ; il indique trois routes migrées, sans inventer de mesure CPU/RSS du processus.

## Poursuite de la migration

Go apporte un outil de compilation et des primitives de concurrence adaptées à un service HTTP ; `context` permet de propager délais et annulations, et la bibliothèque SQL fournit transactions et gestion de connexions. Ces capacités sont documentées, mais ne prouvent aucun gain de débit, de mémoire ou de latence pour Emulytix sans comparaison mesurée. [Organisation et compilation Go](https://go.dev/doc/code), [context](https://pkg.go.dev/context), [database/sql](https://pkg.go.dev/database/sql).

Les prochaines tranches doivent suivre des domaines remplaçables : figer leurs contrats, migrer progressivement leurs lectures, puis déplacer les écritures une fois leurs invariants prouvés. L’API Python reste disponible pendant la transition, avec un seul chemin d’écriture actif par domaine.

Conditions à préserver avant chaque bascule :

- Contrats HTTP, codes d’erreur, pagination, identifiants et valeurs `null` ; compatibilité avec le proxy Next.js existant.
- Mots de passe Argon2, secrets 2FA chiffrés, enrôlement obligatoire, codes de secours, sessions, révocation, limitation des tentatives, CSRF et cinq rôles. La compatibilité des formats persistés doit être testée sans réinitialiser les comptes.
- Immutabilité des versions de parcours, empreintes JSON canoniques, révisions optimistes, idempotence des demandes, ordres des événements et historique.
- Capture privée avec contrôles de fichier/empreinte, SSE, déconnexion et arrêt des flux, fraîcheur des observations et journaux sans secrets.
- Transactions de claim, concurrence par run et appareil, propriété/époque/expiration des baux, annulation, quarantaine et résistance au crash de l’ordonnanceur.

Les essais doivent utiliser des bases PostgreSQL jetables et un driver Android simulé, avec comparaison des contrats Python/Go, concurrence et injection de pannes. Un benchmark commun doit isoler latence API, coût des requêtes et temps Android avant d’attribuer un gain au langage. Aucun changement du langage de l’API n’augmente à lui seul le nombre de téléphones connectés ou de workers disponibles.
