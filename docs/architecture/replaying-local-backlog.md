# Reprendre les essais du banc local

Le script `scripts/replay-pending-console.py` vise les quatre demandes WF01 connues de cette installation, créées sur `banc-de-test` (`bench` / `moultiplate`) alors qu'aucun Android ne correspondait à cette connexion. Son mode par défaut est une simulation. Il ne cherche pas toutes les demandes de la base et ne réaffecte jamais une exécution existante.

Une reprise conserve la version du parcours et ses paramètres, puis crée une nouvelle demande sur `local-emulator` avec une clé stable `retry:<source>:<target>`. La source est verrouillée et doit être encore entièrement en attente. L'appareil cible doit avoir une connexion Android fraîche et ne pas être quarantiné. Les demandes annulées ou terminées par l'utilisateur ne sont pas relancées.

Le nouveau run est validé avant l'annulation de la source. Si le processus s'arrête entre les deux commits, la tentative suivante retrouve la même nouvelle demande ; aucun doublon n'est créé. La source conserve ses identifiants d'appareils d'origine, et des événements `run.retried` / `run.retried_from` relient les deux historiques. L'audit conserve l'identifiant source et l'identifiant du remplacement, sans recopier les paramètres.

Après démarrage du banc et seulement lorsque l'opérateur souhaite réellement reprendre ces quatre demandes :

```bash
# Lire ce qui sera repris, sans créer de run.
docker compose --env-file .env.console -p emulytix-preview -f docker-compose.preview.yml exec -T console-api python - < scripts/replay-pending-console.py

# Créer les remplacements et annuler les sources encore en attente.
docker compose --env-file .env.console -p emulytix-preview -f docker-compose.preview.yml exec -T console-api python - --apply < scripts/replay-pending-console.py
```

Les sorties sont des identifiants et des états JSON ; elles ne contiennent ni mots de passe ni contenu des paramètres. Les six tests dédiés utilisent PostgreSQL éphémère et vérifient notamment la concurrence et la réparation d'une interruption entre commits.

## Parallélisme

Le worker courant traite une exécution à la fois. Un téléphone ne peut appartenir qu'à une exécution active grâce au bail PostgreSQL et au verrou local. La capacité réelle est donc bornée par les appareils distincts connectés et les workers disponibles pour leurs hôtes, puis par `max_concurrency` de chaque lot. Le contrat autorise jusqu'à cent appareils par soumission ; il ne constitue pas une preuve de capacité de cent exécutions simultanées. Avec un seul émulateur et un seul worker, les quatre reprises s'exécutent successivement.
