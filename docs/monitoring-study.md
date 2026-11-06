# Étude du monitoring Emulytix

Date : 6 novembre 2026. Périmètre : console, API Python, ordonnanceur, workers Android, PostgreSQL et parc multiappareils.

## Questions opérationnelles

Le monitoring doit permettre de répondre rapidement à cinq questions :

1. Les mesures sont-elles récentes et les services capables de répondre ?
2. Des exécutions attendent-elles, depuis combien de temps et sur quel hôte ?
3. Les workers et les appareils utilisables suffisent-ils à la charge présente ?
4. Les exécutions aboutissent-elles et où passe leur temps ?
5. Quel composant faut-il examiner : service Python, connexion Android, ordonnanceur ou base ?

Une interface claire, proche des conventions des outils Google, doit donner la priorité aux résultats et aux situations à examiner. La couleur accompagne un état écrit ; un graphique d’architecture ne remplace pas les nombres, leur périmètre et leur date.

## Constats avant cette évolution

La console disposait déjà d’un flux SSE toutes les deux secondes, de heartbeats persistés dans PostgreSQL et d’une péremption à vingt secondes. Elle présentait l’architecture, une sonde PostgreSQL, les nombres d’exécutions par état, les réservations d’appareils et les hôtes déclarés.

Ces informations laissaient plusieurs questions ouvertes :

- Le nombre de tâches en file ne montrait pas l’ancienneté de l’attente.
- Un worker vivant et un appareil réservé ne donnaient pas directement le nombre de workers occupés.
- Le nombre d’appareils déclarés ne prouvait pas leur connexion ADB.
- Aucun résultat borné dans le temps ni distribution des durées ne permettait d’évaluer les exécutions récentes.
- Les services ne publiaient pas leur consommation CPU et mémoire propre.
- Le navigateur pouvait conserver un état « en direct » tant qu’aucune erreur explicite du flux n’était signalée.
- Les anciennes identités d’instances restaient mêlées aux services actuels.
- Chaque lecteur du flux pouvait déclencher ses propres agrégations.

Ces constats proviennent de la lecture de `monitor_routes.py`, `telemetry.py`, `console_routes.py` et du composant `monitor.tsx`, avant modification. Ils ne constituent pas une mesure de charge ni une preuve de panne sur une installation réelle.

## Principes issus des sources officielles

[Google SRE](https://sre.google/sre-book/monitoring-distributed-systems/) recommande de suivre latence, trafic, erreurs et saturation, et de distinguer les latences des succès et des échecs. Pour Emulytix, cela conduit à rapprocher résultats d’exécution, attente et occupation. Cette évolution ne prétend pas fournir un taux d’erreur HTTP ni un débit de requêtes qui ne sont pas collectés.

[Prometheus](https://prometheus.io/docs/practices/instrumentation/) distingue services interactifs, traitements continus et batchs. Les dernières activités et derniers succès sont utiles pour détecter un traitement arrêté. Sa recommandation d’exposer des timestamps plutôt que des âges enregistrés permet de recalculer l’ancienneté même lorsque le producteur ne progresse plus.

Les [recommandations sur les histogrammes](https://prometheus.io/docs/practices/histograms/) rappellent que les quantiles calculés séparément ne s’agrègent pas par une moyenne. Ici les percentiles sont calculés dans PostgreSQL sur les durées individuelles de l’échantillon sélectionné.

[OpenTelemetry](https://opentelemetry.io/docs/specs/semconv/system/process-metrics/) distingue les métriques d’un processus de celles du [conteneur](https://opentelemetry.io/docs/specs/semconv/system/container-metrics/) et de [l’hôte](https://opentelemetry.io/docs/specs/semconv/system/system-metrics/). Ces distinctions guident les unités et les libellés ; aucun SDK OpenTelemetry ni serveur Prometheus n’est ajouté.

## Mesures retenues et formules

### File et activité présentes

| Lecture | Définition | Limite de lecture |
|---|---|---|
| En attente | Nombre d’exécutions dont `status = queued` | Toutes les tâches en file ne sont pas nécessairement exécutables immédiatement : appareil, limite de concurrence du lot ou autre condition peuvent les retenir. |
| Plus ancienne attente | `max(0, observed_at − min(created_at des queued))` | `null` si la file est vide. Il s’agit d’un âge depuis la création, pas d’une estimation de démarrage. |
| Actives | États `leased`, `running`, `recovering`, `verifying_state`, `waiting_auth` | Le nombre d’exécutions actives n’est pas le nombre de workers vivants. |
| Attente d’authentification | Nombre d’exécutions `waiting_auth` | Sous-ensemble des actives, à ne pas additionner une seconde fois. |

Les horodatages métier et `observed_at` utilisent l’horloge PostgreSQL. [La documentation de `clock_timestamp()`](https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT) précise qu’il donne l’heure courante, contrairement à une heure figée au début de transaction. Le navigateur affiche ces dates dans la langue et le fuseau de l’utilisateur.

### Capacité des workers et état du parc

Un worker actif possède un heartbeat récent et un statut `ready`. Le modèle actuel exécute un parcours à la fois par processus worker ; chaque appareil ne peut avoir qu’une exécution active.

- **Workers occupés** : nombre de workers actifs distincts possédant au moins une réservation valide, non expirée et hors quarantaine.
- **Workers libres** : `workers actifs − workers occupés`.
- **Occupation** : `100 × workers occupés / workers actifs`, ou `null` en l’absence de worker actif.
- **Réservations non confirmées** : réservations valides dont le propriétaire ne correspond pas à un worker actif connu. Elles restent visibles au lieu de gonfler l’occupation confirmée.

Les capacités des workers et des téléphones restent séparées. Un worker libre ne rend pas disponible un appareil hors ligne ou réservé ; le total des appareils déclarés ne mesure pas la concurrence exécutable.

La preuve de connexion Android réutilise la sonde ADB transmise par un worker actif du même hôte. Le numéro de série doit apparaître dans cette sonde avec l’état `device` pour compter comme connecté. Les états non autorisé, hors ligne, absent de la sonde, worker hors ligne et inconnu restent distincts. Un appareil prêt est connecté, sans propriétaire de réservation et hors quarantaine. L’état occupé et la connexion sont deux dimensions : une réservation peut survivre à une perte de connexion.

### Résultats et latences

Les fenêtres sont **1 heure**, **24 heures** et **7 jours**, avec **24 heures par défaut**. Elles sont définies par `finished_at`, entre `observed_at − fenêtre` et `observed_at`. Les états retenus sont `succeeded`, `failed`, `cancelled` et `needs_review`.

Le calcul lit au plus les **5 000 dernières exécutions terminées** de la fenêtre, triées par date de fin puis identifiant. Une ligne supplémentaire détecte la troncature. Si la fenêtre contient davantage de résultats, les nombres, taux et percentiles portent tous sur ce sous-ensemble récent ; l’interface annonce cette limite. Ils ne représentent alors pas le total complet de la fenêtre.

| Lecture | Formule et population |
|---|---|
| Réussite | `100 × S / (S + F)`, avec `S = succeeded` et `F = failed`. `null` lorsque `S + F = 0`. |
| Annulées / à vérifier | Comptées séparément ; exclues du dénominateur de réussite. Elles font partie de l’échantillon total. |
| Durée | `finished_at − started_at`, seulement si le démarrage existe et la durée est positive ou nulle. Médiane et P95, accompagnés de leur nombre d’observations. |
| Attente avant démarrage | `started_at − created_at`, seulement si le démarrage existe et l’attente est positive ou nulle. P95 accompagné de son nombre d’observations. |
| Dernière réussite | Dernier `finished_at` réussi connu, même hors de la fenêtre choisie ; `null` si aucune réussite n’est connue. |

Les percentiles utilisent `percentile_cont` et peuvent interpoler entre observations. Un P95 avec peu d’observations est peu représentatif : son effectif doit rester visible. Les populations de durée et d’attente peuvent différer de l’effectif total. Les exécutions encore en attente ou en cours n’y figurent pas ; l’âge de la file complète donc le P95 d’attente des tâches déjà terminées.

Ce taux décrit les résultats par appareil, pas la réussite d’un lot entier, d’une requête HTTP ou d’une tentative élémentaire. Les fenêtres ne sont pas des cohortes de demandes créées pendant la période. Aucun débit d’entrée, taux de reprise, historique de CPU ou objectif de service n’est déduit de ces données.

### Ordonnanceur

Une planification activée est en retard lorsque `next_run_at < observed_at − 30 secondes`. Cette marge est un choix du produit, pas une norme de disponibilité. L’âge du plus ancien retard est calculé depuis sa date prévue ; il n’est pas réduit de trente secondes. Les erreurs enregistrées sont présentées à part : leur présence seule ne prouve pas un incident toujours actif.

Une heure de prochaine exécution renseigne le calendrier ; elle ne confirme ni le dispatch ni le démarrage sur Android.

### PostgreSQL

| Lecture | Ce qui est mesuré | Ce qui ne peut pas en être conclu |
|---|---|---|
| Latence de connexion | Temps monotone autour de l’ouverture d’une connexion et d’une requête légère (`SELECT clock_timestamp()`, qui remplit aussi le rôle de sonde) | Ce n’est ni un P95 SQL, ni le temps des requêtes applicatives, ni une mesure du réseau seul. |
| Connexions utilisées / maximum | Nombre de `client backend` de `pg_stat_activity`, comparé à `max_connections` | Mesure du serveur PostgreSQL, pas uniquement de cette base ou de son pool applicatif. Les places réservées ne sont pas soustraites. |
| Taille | `pg_database_size(current_database())` | Taille de la base, pas espace libre du disque hôte. |

Les statistiques peuvent manquer en cas de droits insuffisants ; leur absence ne devient pas une valeur zéro. [PostgreSQL décrit les vues et leurs restrictions](https://www.postgresql.org/docs/current/monitoring-stats.html). Les statistiques cumulatives nécessiteraient des différences entre échantillons pour produire des débits. [`pg_stat_statements`](https://www.postgresql.org/docs/current/pgstatstatements.html) fournit notamment des moyennes ; elles ne doivent pas être renommées P95.

### Ressources des services Python

Le collecteur utilise la bibliothèque standard et le périmètre du **processus Python courant**, tous ses threads compris. Les sous-processus ADB, l’émulateur, les autres processus du conteneur et l’hôte sont exclus.

- **CPU en cœurs** : `Δtime.process_time() / Δtime.monotonic()`. `1,0` représente un cœur consommé pendant l’intervalle ; ce n’est pas un pourcentage de capacité hôte ou conteneur. Le premier échantillon et les mesures invalides donnent `null`.
- **Mémoire RSS** : pages résidentes de `/proc/self/statm × taille de page`, sous Linux. La valeur est `null` si cette observation n’est pas disponible ; elle ne représente pas toute la mémoire du conteneur.
- **Durée de fonctionnement** : démarrage du processus via `/proc/self/stat` et horloge de démarrage Linux. Sans ces mécanismes, le repli mesure le temps depuis la création du collecteur.

[Python documente](https://docs.python.org/3/library/time.html#time.process_time) le temps CPU du processus et les horloges monotones. Le choix « cœurs consommés » rend le numérateur explicite. La convention OTel `process.cpu.utilization` normalise aussi par le nombre de CPU disponibles ; elle ne correspond donc pas directement à la valeur affichée ici.

## Fraîcheur, transport et coût de collecte

| Paramètre | Valeur retenue | Sens |
|---|---|---|
| Heartbeat d’un service | Environ 5 secondes | Cadence nominale, pouvant s’allonger avec le temps de sonde et d’écriture. |
| Péremption d’un service | 20 secondes | Le heartbeat doit avoir moins de vingt secondes et le service être prêt. |
| Diffusion SSE | 2 secondes | Cadence nominale de diffusion, distincte de la cadence des heartbeats. |
| Cache du snapshot SSE | 2 secondes par fenêtre et processus API | Mutualise les lectures entre spectateurs de ce processus ; les GET directs restent frais. |
| Fraîcheur côté navigateur | 10 secondes sans message reçu | L’état « en direct » expire même sans événement d’erreur réseau. |
| Onglet masqué | Flux suspendu | Reprise de collecte à son retour au premier plan. |

Les décisions d’âge serveur utilisent l’heure PostgreSQL ; le client prolonge l’âge du signal depuis la réception du snapshot. L’horodatage local des ressources est informatif et ne remplace pas l’horloge métier. Les dernières données peuvent être conservées après une interruption, avec un état non confirmé ou ancien. Une mesure absente reste `null` et s’affiche sans valeur inventée. Un vrai compteur observé à zéro reste zéro.

Les anciennes instances sont masquées par défaut, avec accès à l’historique. Si aucun signal vivant n’existe pour un composant, la dernière instance reste utile pour expliquer son absence. Le cache n’assure pas un snapshot transactionnel de tous les composants : les heartbeats, réservations et résultats sont des observations distinctes.

La collecte reste protégée par la session et `monitor.read`, et la session est revérifiée pendant le flux. Aucun accès direct Docker ou ADB n’est ajouté à l’API. Les messages d’indisponibilité ne publient ni exception détaillée ni secrets.

## Limites et suites possibles

Cette évolution améliore le diagnostic sans nouvelle infrastructure de télémétrie, sans envoi d’alertes par courriel et sans métriques fictives. Les états à examiner dans la page sont des aides à l’exploitation, pas un engagement de service.

Si le volume augmente, les prochaines mesures utiles sont le débit d’entrée et de sortie par étape, les latences et erreurs HTTP, les attentes PostgreSQL et un historique des ressources. Elles demandent une collecte adaptée ; elles ne doivent pas être simulées à partir des seuls snapshots présents. La limite de 5 000 résultats protège le travail par requête ; une conservation de séries ou des agrégats persistés seraient une décision séparée.

Pour une éventuelle instrumentation, garder des dimensions bornées et mettre les identifiants d’exécution et messages détaillés dans le journal. [OpenTelemetry explique](https://opentelemetry.io/docs/concepts/signals/metrics/#cardinality-limits) que trop de combinaisons d’attributs augmentent la mémoire et peuvent faire perdre la précision des ventilations lors d’un débordement. Pour d’éventuelles alertes, [Prometheus](https://prometheus.io/docs/practices/alerting/) recommande des symptômes associés à un impact, une durée tolérant les fluctuations et une action possible. Aucun seuil CPU universel ni taux de réussite cible n’est adopté ici.

## Repères dans le dépôt

- [Agrégats et fenêtres](../orchestrator-api/app/monitor_metrics.py)
- [Collecteur des processus](../orchestrator-api/app/process_metrics.py)
- [Heartbeats](../orchestrator-api/app/telemetry.py)
- [Snapshots et flux SSE](../orchestrator-api/app/monitor_routes.py)
- [Preuve de connexion des appareils](../orchestrator-api/app/console_routes.py)
- [Types et règles de fraîcheur du client](../web-ui/lib/monitoring.ts)
- [Interface de monitoring](../web-ui/components/console/monitor.tsx)

Les sources officielles ont été consultées le 6 novembre 2026. Les formules et limites ci-dessus suivent le contrat de collecte retenu dans le dépôt ; les principes SRE, Prometheus et OpenTelemetry n’imposent pas les fenêtres ni les seuils numériques choisis pour Emulytix.
