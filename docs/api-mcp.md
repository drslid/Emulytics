# API personnelle et MCP

Depuis **Mon profil → API et MCP personnels**, chaque utilisateur peut créer une clé nommée et limitée à ses droits. Les profils proposés sont consultation, lancement ou publication et lancement, selon le rôle. L’expiration est obligatoire (7, 30, 90 ou 365 jours dans l’interface ; de 1 à 365 jours dans le contrat).

La création demande le mot de passe actuel et un **nouveau code de l’application 2FA**. Les codes de secours ne peuvent pas créer une clé. Le secret `emk_…` est affiché une seule fois et doit être conservé dans un gestionnaire de mots de passe ; il n’est enregistré ni en clair dans PostgreSQL, ni dans le stockage du navigateur. Le serveur conserve son empreinte SHA-256 et un préfixe d’identification.

La révocation est immédiate et ne supprime pas les exécutions déjà en file. Modifier le rôle, désactiver le compte, réinitialiser ou changer le mot de passe ou le facteur révoque toutes ses clés. Réactiver le compte ne restaure pas les anciennes clés. Fermer une session de navigation seule ne révoque pas une clé indépendante. Le maximum est de vingt clés actives par utilisateur ; la liste est paginée.

Une réponse perdue pendant la création ne permet pas de récupérer le secret : actualiser la liste, révoquer la clé éventuellement créée puis en créer une autre. Le `request_id` de création empêche une deuxième création pour la même demande.

## REST

Adresse locale : `http://localhost:3100/api/v1`. Pour un accès distant, publier la console derrière HTTPS. Le client transmet `Authorization: Bearer $EMULYTIX_API_KEY`. Les cookies de console et le jeton interne `EMULYTIX_CONTROL_TOKEN` ne donnent aucun accès à cette API. Un en-tête `Origin` présent doit correspondre à l’origine configurée. Les réponses ne sont pas mises en cache.

| Méthode et chemin relatif | Permission explicite requise |
|---|---|
| `GET /capabilities` | Une clé valide ; renvoie ses permissions effectives |
| `GET /devices` | `devices.read` |
| `GET /workflows` et `/workflows/{id}/versions/{version}` | `workflows.read` |
| `POST /workflows` | `workflows.publish` |
| `GET /runs`, `/runs/{id}` et `/runs/{id}/events` | `runs.read` |
| `POST /runs` | `runs.execute` |
| `POST /runs/{id}/cancel` | `runs.cancel` |

Les droits sont l’intersection des permissions inscrites dans la clé et du rôle actuel. Une clé ne peut pas administrer les utilisateurs, lancer des commandes ADB, lire des identifiants ChatGPT, obtenir une session de console ou piloter les opérations système d’émulateur. La lecture d’un appareil déclaré ne démontre pas sa connexion effective.

Les listes prennent `limit` (1 à 100) et `offset` ; les événements prennent `after` et `limit`. Le plafond partagé entre processus est de 600 requêtes par minute et par clé ; le dépassement renvoie `429` et `Retry-After: 60`. Les mutations ont la même trace d’acteur que la console, sans enregistrer leur corps ni le secret.

Un lancement reprend le contrat existant :

```json
{
  "workflow_id": "chrome-wikipedia-football",
  "workflow_version": 1,
  "device_ids": ["local-emulator"],
  "max_concurrency": 1,
  "idempotency_key": "wiki-football-attempt-001",
  "parameters": {}
}
```

Conserver **la même clé d’idempotence et le même corps** après un délai dépassé ou une déconnexion. Une réémission retrouve le même lot ; un contenu différent sous cette clé renvoie `409`. Le serveur donne à ces clés un espace propre à l’utilisateur ; la valeur conservée et renvoyée dans le détail du lot est une empreinte interne. Une table de provenance associe l’utilisateur, l’empreinte de sa clé, le contenu et le lot dans la même transaction que sa création. Un lot ancien portant seulement la même clé interne est refusé. Une clé différente demande une nouvelle exécution. Les versions publiées restent immuables. Une demande d’annulation active peut répondre `202` : attendre ensuite la confirmation du worker dans le détail du lot.

Avant chaque mutation, le serveur revérifie et verrouille l’utilisateur, la clé et ses permissions dans cet ordre. Une révocation effective avant cette vérification interdit l’écriture ; une mutation déjà autorisée termine avant que la révocation puisse être validée. Les préfixes de clés internes `api-` et `retry:` sont réservés et refusés par l’endpoint ordinaire de lancement.

## MCP stdio

Le serveur fourni utilise le transport **stdio**, sans dépendance Python supplémentaire et sans ouvrir de port MCP. Le client lance le script et celui-ci appelle la même API REST, avec la même clé, les mêmes permissions, la même révocation et les mêmes limites.

Configuration type pour un client MCP acceptant un processus local :

```json
{
  "mcpServers": {
    "emulytix": {
      "command": "python3",
      "args": ["/chemin/vers/Emulytix/scripts/emulytix-mcp.py"],
      "env": {
        "EMULYTIX_API_URL": "http://localhost:3100",
        "EMULYTIX_API_KEY": "REMPLACER_PAR_VOTRE_CLE_PERSONNELLE"
      }
    }
  }
}
```

Stocker cette configuration hors du dépôt et utiliser le gestionnaire de secrets du client lorsqu’il le permet. L’URL peut aussi désigner une console distante en HTTPS. Les redirections HTTP sont refusées ; HTTP sans TLS est accepté uniquement pour localhost. Le script n’affiche pas la clé dans ses réponses ou diagnostics.

Outils : `list_devices`, `list_workflows`, `list_runs`, `get_run`, `get_run_events`, `start_run`, `cancel_run`. La découverte ne présente que les outils compatibles avec les permissions effectives. Le serveur REST revérifie néanmoins chaque action. `start_run` exige une clé d’idempotence fournie par le client et ne relance pas automatiquement une demande incertaine. La publication reste disponible par REST ; aucun shell ou outil d’administration n’est exposé.

Le serveur prend en charge initialisation, notification de disponibilité, ping, découverte et appel d’outils, avec réponses textuelles et structurées. Révision principale `2025-11-25`, compatibilité de négociation `2025-06-18` et `2025-03-26`. Ni ressources, prompts, flux SSE, tâches asynchrones MCP ni serveur HTTP/OAuth MCP ne sont annoncés. Les lots Android restent asynchrones dans l’API et se suivent avec `get_run`.

Références officielles : [transport stdio](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [cycle d’initialisation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [outils MCP](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

## Installation et validation

Appliquer la migration `018_personal_api_keys.sql` avant de redémarrer l’API et l’interface. L’API versionnée utilise les services métier Python existants ; cette tranche ne déplace pas de domaines supplémentaires vers Go. Le proxy Next.js ne transmet que le Bearer personnel et les routes documentées, avec corps JSON bornés à 64 Kio, délai et redirections contrôlés.

Tests : `test_personal_api.py` couvre isolation, secret non récupérable, vérification de facteur, rôle, expiration, révocation, limite partagée, CSRF, refus des jetons internes, lancement idempotent et annulation. `test_mcp_adapter.py` couvre cycle, filtrage des outils, arguments, conservation de clé, stdout JSON-RPC et refus des URL non sûres. Les tests frontend vérifient proxy, profils de permissions, expiration et textes dans les dix langues. Les tests PostgreSQL utilisent une base jetable ; aucune clé d’exploitation n’est créée par ces tests.
