# Nettoyage avant publication — 8 novembre 2026

Le nettoyage conserve une seule installation maintenue : `scripts/install.sh`, les scripts de la console, `docker-compose.preview.yml` et `docker-compose.console-worker.yml`. Les vérifications utilisent cette installation et les tests, sans commande de suppression sur les données locales.

## Éléments retirés

Quatorze fichiers suivis, représentant 806 lignes, ont été retirés après recherche de leurs références dans les scripts, la CI, les Dockerfiles, le code et les tests.

| Élément | Motif |
|---|---|
| `docker-compose.yml`, `docker-compose.runtime.yml` | Profils historiques remplacés par la stack console. Ils conservaient notamment des publications directes de ports API, agent, VNC et ADB ainsi qu’un accès Docker depuis l’ancienne API. |
| `agent-service/` | Ancien planificateur par clé OpenAI et heuristiques, appelé uniquement par les profils prototypes. La génération maintenue utilise les capacités vérifiées et la connexion ChatGPT personnelle. |
| `all-in-one/` | Image et lanceur prototypes avec leur ancien agent, sans appel depuis l’installation ni la CI maintenues. |
| `android-runtime/Dockerfile`, `android-runtime/scripts/bootstrap.sh` | Ancien wrapper Android remplacé par `Dockerfile.console`, les archives SDK vérifiées et les scripts de banc maintenus. |
| `web-ui/Dockerfile` | Ancien conteneur de développement utilisant `npm install`. La console utilise `Dockerfile.preview`, le verrou npm et le build de production. |
| `scripts/replay-pending-console.py`, son test dédié et `docs/architecture/replaying-local-backlog.md` | Outil de réparation ponctuelle de quatre demandes propres à l’installation de développement. La relance contrôlée du produit utilise désormais les services et droits partagés. |

Le retrait des tests de cet outil ponctuel accompagne le retrait complet de cet outil ; il ne réduit pas les tests des services de relance maintenus.

`.env.example` décrit maintenant uniquement les variables de la console, avec secrets vides, authentification activée et restrictions explicites du mode HTTP localhost. Les paramètres de l’ancien agent, de sa clé API et de ses ports directs ont été retirés. Aucun fichier `.env` actif n’a été remplacé.

## Éléments conservés

- Les migrations SQL, les définitions de parcours et les tests des fonctionnalités maintenues.
- Les fichiers sources de marque, le script d’export, les icônes, les polices et leurs licences : ils servent à produire et afficher l’identité actuelle.
- `PLAN.MD`, les études et `technical-status.md` comme contexte de conception et journal historique. Une note en tête du plan et du journal distingue les commandes prototypes retirées de l’installation actuelle.
- Le stockage, les captures, les APK locaux, les fichiers de configuration privés, les comptes et les volumes Android/PostgreSQL. Ils restent hors Git et n’ont pas été nettoyés par suppression.
- Les autres stacks présentes sur l’hôte, identifiées comme appartenant à d’autres projets.

Les imports relatifs du frontend ont également été parcourus : aucun module `lib/` ou `components/console/` supplémentaire n’a été identifié sans référence. Les dépendances Python partagées conservées, dont Docker et HTTPX, ont encore des appels dans le runtime et le monitoring.

## Vérification

- **37 tests réussis** : installateur en une commande, helper Android et initialisation du parcours fourni.
- Configuration Compose de la stack console et du profil worker validée avec `config --quiet`.
- Recherche des anciens chemins dans les points d’entrée maintenus ; les références restantes dans le plan et le journal sont explicitement historiques. Le retrait du code API historique appartient à la revue de sécurité séparée.
- Aucun fichier de clé privée, base, APK, archive, journal, HAR ou état de navigateur identifié parmi les fichiers suivis lors du contrôle de ces catégories.
- Contrôle des ports : la console de ce dépôt publie uniquement `127.0.0.1:3100`. Ce contrôle ne constitue pas un audit des autres projets de l’hôte.

Les contrôles de dépendances, la recherche complète de secrets dans l’historique, les tests globaux et la publication GitHub sont réalisés séparément lors de la préparation de livraison.
