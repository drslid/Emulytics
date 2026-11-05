# Emulytix x Artemis — Plan d'exécution (v3 consolidée)

Date : 2026-11-05  
Source : [study.md](study.md)  
Statut : Plan corrigé pour exécution — v3 recentrée sur la viabilité de la couche d'inférence, le mode "scripté par défaut / LLM en secours", le fencing côté hôte et le dimensionnement matériel/données.

Ce document remplace la v2. Changements majeurs par rapport à la v2 :
1. La dépendance Device Code est traitée comme un **risque de viabilité** (contractuel et capacitaire), avec plan B obligatoire au Go/No-Go J3.
2. Les trois workflows sont exécutés en **mode scripté déterministe** ; la vision LLM n'intervient qu'en **récupération**.
3. Le fencing est complété par un **watchdog hôte** et une **réinitialisation device** à la reprise, car un `kill -9` ne coupe rien.
4. Ajout d'une **vérification d'état post-crash** avant de basculer en `needs_review`.
5. Artemis est assumé comme **fork interne patché** et non comme submodule figé.
6. Ajout de chantiers **dimensionnement matériel**, **données personnelles / secrets**, **observabilité**.
7. S2 est déchargé : le pool de comptes devient optionnel, piloté par les mesures du Spike.

---

## Décisions d'architecture — Arbitrages consolidés

| Décision | Recommandation et implémentation sur la base Artemis |
|---|---|
| **Stratégie d'intégration** | **Fork interne patché** d'Artemis (`emulytix/artemis-fork`), commit de référence tagué, patchs versionnés dans un dossier `patches/` avec rebase documenté. Cœur d'exécution Android conservé ; couches d'entrée/sortie remplacées (`llm/router.py`, `runtime/device_lock.py`, wrapper du contrôleur Android). On renonce au vocabulaire "submodule figé" : dès qu'on purge `runner.py`, c'est un fork. |
| **Périmètre Artemis récupéré** | **Conservés** : `DevicePool`, contrôleurs ADB/UIAutomator, exécuteur d'actions, capture de traces. **`FlashRunner`** conservé uniquement comme **moteur de récupération** (voir ligne suivante). **Purgés** : fallback Gemini dans `agents/flash/runner.py`, rapports QA lourds, analyse vidéo post-run. |
| **Mode d'exécution : scripté par défaut, LLM en secours** | Les 3 workflows (< 15 étapes, déterministes) sont écrits en **scripts d'étapes** (sélecteurs UIAutomator, `resource-id`, texte, coordonnées relatives) exécutés sans aucun appel LLM. Chaque étape déclare : sélecteur(s), timeout, assertion de succès, flag `non_idempotent`. **Codex Vision n'est appelé que si** : sélecteur introuvable après timeout, assertion échouée, ou écran inconnu détecté (pop-up, permission, mise à jour). Le LLM reçoit l'objectif de l'étape et tente de ramener l'app sur le chemin nominal, avec un budget borné (max N appels par étape, M par run). Effet attendu : division par 10-50 de la charge LLM, runs plus rapides et reproductibles. |
| **Couche d'inférence & viabilité** | Adaptateur Codex app-server (`chatgptDeviceCode`) derrière une **interface `VisionProvider` abstraite** (`analyze(screenshot, goal) -> action`). **Risque assumé** : Device Code = comptes ChatGPT individuels ; un pool de comptes rotatifs pour un service commercial expose à la suspension de comptes en plein run client, et les quotas sont des plafonds glissants (5h / hebdo), pas seulement par minute. **Décision** : le Spike J1-J3 mesure la capacité **soutenue sur 48h** et produit un avis sur la viabilité contractuelle. **Plan B obligatoire** câblé derrière la même interface : (a) API payante (OpenAI/Anthropic/Gemini via clé entreprise), (b) modèle vision local (type Qwen2-VL) sur un hôte GPU. Le choix du provider devient une configuration, pas une architecture. |
| **Orchestration distribuée & Fencing** | FastAPI + PostgreSQL pour l'état global. Un worker par exécution active. Baux renouvelables avec `lease_epoch` (fencing token). **Complément v3** : (1) le wrapper ADB vérifie l'epoch avant chaque commande ; (2) un **watchdog par hôte** tue (`SIGKILL`) tout worker dont le bail est expiré en base, car un process mort ne coupe rien lui-même et le démon ADB est partagé par hôte ; (3) tout nouveau preneur de bail exécute une **réinitialisation device** (`adb reconnect`, `am force-stop` de l'app cible, déverrouillage) avant la première action. |
| **Reprise et effets métier** | Journal durable dans PostgreSQL **avant** chaque action (`action_journal` : étape, intention, epoch, horodatage, `status = intent`). Après l'action : `status = done` + capture. En cas de crash sur une étape `non_idempotent` avec intention journalisée mais non confirmée : le worker repreneur exécute une **vérification d'état** scriptée (assertion d'écran / lecture d'un identifiant de confirmation / vision LLM si nécessaire). Si l'état est déterminable → reprise ou marquage `succeeded`. Si indéterminable → `needs_review`. Objectif : `needs_review` est l'exception, pas la réponse par défaut au crash. |
| **Périmètre commercial & Matériel** | 3 workflows courts et déterministes. Chantier infra séparé dès S1 avec **budget chiffré** (voir section Dimensionnement). Émulateurs comptés à 3 Go RAM + 2 vCPU chacun ; physiques limités par contrôleur USB et alimentation. |
| **Données, secrets & conformité** | Captures d'écran = données potentiellement personnelles : rétention paramétrable (défaut 30 j), stockage chiffré (MinIO/S3 SSE), masquage optionnel des zones sensibles par règle de workflow. Identifiants saisis sur les téléphones stockés dans un coffre (Vault / secret manager), injectés en mémoire au worker, jamais journalisés en clair. |
| **Observabilité** | Logs structurés (JSON) centralisés, métriques Prometheus (durée d'étape, appels LLM par run, 429, quarantaines, baux expirés), traces corrélées par `run_id`/`execution_id`/`lease_epoch`. Coût unitaire par run calculé et exposé. |

---

## Contrat technique à figer (J1)

- **`POST /runs`** : `workflow_id` + version, paramètres, liste figée de `device_id`, concurrence max, `idempotency_key` ; réponse `202 + run_id`.
- **Format de workflow versionné** (YAML/JSON) : liste d'étapes `{id, action, selector(s), timeout_ms, assert, non_idempotent, recovery_budget}`. Toute modification = nouvelle version ; les runs référencent une version précise.
- **Cycle de vie d'une exécution (1 par device)** : `queued` → `leased` → `running` → (`recovering` | `verifying_state` | `waiting_auth` | `needs_review`) → `succeeded` | `failed` | `cancelled`.
- **Fencing** : `lease_epoch` incrémenté à chaque prise de bail. Durée de bail = 3 × intervalle heartbeat. Expiration → watchdog hôte tue le worker → device réinitialisé par le repreneur.
- **Interface `VisionProvider`** : `analyze(screenshot, goal, context) -> {action, confidence}` avec implémentations `codex_device_code`, `api_key`, `local_vlm`. Sélection par config, bascule possible à chaud par workflow.
- **Flux temps réel & Contrôle** : `GET /devices`, `GET /runs/{id}`, SSE rejouable par `Last-Event-ID`. `cancel` (interrompt avant la prochaine action, révoque le bail), `retry-failed` (nouvelle exécution liée, ignore les `succeeded`), `resolve-review` (opérateur tranche : `succeeded` / `retry` / `failed`).

---

## Dimensionnement matériel (chantier Infra, chiffré au S1)

| Poste | Hypothèse de travail | À valider en S1 |
|---|---|---|
| Physiques par hôte | 15-20 par contrôleur USB, hubs alimentés, 1 hôte = 2 contrôleurs max | Limite réelle en captures ADB en boucle |
| Émulateurs par hôte | 3 Go RAM + 2 vCPU chacun ; hôte 128 Go / 32 cœurs ≈ 25-30 émulateurs | Stabilité ADB et CPU à 25 |
| Cible 100 devices | ~3 hôtes physiques (~40 phones) + ~2-3 hôtes émulation (~60 émulateurs) | Nombre d'hôtes et budget présentés fin S1 |
| Stockage captures | ~200 Ko × ~30 captures/run × runs/jour | Volume et rétention |
| GPU (plan B local) | 1 GPU 24 Go pour un VLM 7B en récupération uniquement | Débit suffisant si LLM = secours seulement |

---

## Plan d'exécution recalibré — S1 / S2 / S3

Capacité : 3 sprints de 2 semaines — 2 Devs Backend/Runtime, 1 Dev Frontend, 1 référent Exploitation/Infra dès S1.

| Sprint | Backlog et livrables | Dépendances | Validation de sortie (Go / No-Go) |
|---|---|---|---|
| **S1 — Fondations, Fork Artemis, Mode scripté, Spike viabilité LLM** | **P0 Backend (J1-J3)** : Spike Device Code via Codex : rafale (req/min) **et** capacité soutenue 48h (plafonds glissants). Avis écrit sur la viabilité contractuelle. Interface `VisionProvider` + implémentation `codex_device_code` + squelette `api_key`. Audit statique Artemis, purge Gemini, suppression des variables `GEMINI_API_KEY`/`OPENAI_API_KEY` sur les workers.<br>**P0 Runtime (J4-J10)** : fork Artemis tagué, format de workflow, moteur d'étapes scriptées, `FlashRunner` réduit au rôle de récupération avec budget borné, persistance PostgreSQL, journal avant action, `cancel`, traces corrélées. 1er workflow scripté de bout en bout.<br>**P0 Front** : UI Ops-first — sélectionner, lancer, suivre, arrêter, logs/captures.<br>**P0 Infra** : banc de test (limite devices par contrôleur USB, émulateurs par hôte), **budget matériel chiffré**, MinIO et logs centralisés en place. | Comptes Device Code de test, 1 physique + 1 émulateur, 3 workflows documentés étape par étape avec actions `non_idempotent` identifiées. | **Go/No-Go J3** : capacité soutenue chiffrée + avis viabilité. Si non viable ou insuffisant → plan B (API payante ou VLM local) activé immédiatement, budget validé.<br>**Sortie S1** : 1 workflow réussi sur physique et émulateur **sans aucun appel LLM en chemin nominal** ; récupération LLM démontrée sur un pop-up injecté ; zéro appel non routé ; survie de l'état au redémarrage de l'API ; budget infra validé. |
| **S2 — Orchestration distribuée & Résilience** | **P0 Backend/Runtime** : scheduler PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`), baux + `lease_epoch` injectés dans le wrapper ADB, heartbeats, **watchdog hôte**, **réinitialisation device à la reprise**, **vérification d'état post-crash** pour les étapes `non_idempotent`, `needs_review` en dernier recours. Régulation LLM simple (token bucket global) sur le provider retenu. Les 3 workflows scriptés.<br>**P1 (si Spike l'impose)** : pool de sessions Device Code avec circuit breaker 429 et état `waiting_auth`. *Décalé en S3 si le mode scripté rend la charge LLM marginale.*<br>**P0 Front** : lots, résultats partiels, `retry-failed`, écran `resolve-review`. Filtres SSE avancés → S3.<br>**P0 Infra** : parc 25-50 devices sur ≥ 2 hôtes, test de charge ADB pur, quarantaine automatique des devices déconnectés. | Sortie S1 validée ; provider LLM tranché ; ≥ 2 hôtes ADB. | **10-20 exécutions simultanées** sur les 3 workflows. Chaos : `kill -9` worker (watchdog + reprise vérifiée), débranchement USB, coupure réseau hôte, expiration forcée de jeton. **Zéro double effet métier** sur étape critique ; zéro pilotage concurrent ; taux de `needs_review` sur crash simulé < 30 %. |
| **S3 — Passage à l'échelle (100), Finition & Livraison** | **P0 Runtime/Infra** : montée 25 → 50 → 100, backpressure sur capacité LLM, isolation des hôtes défaillants, rétention/masquage captures, coût par run exposé.<br>**P1 reporté de S2** : pool de comptes si encore pertinent, filtres SSE.<br>**P0 Front** : polissage UI, tableaux de bord vélocité/quotas/coût, modèles de lancement, raccourcis opérateurs. | Parc de 100 validé en ADB pur fin S2. | **Endurance 1h à 100 devices actifs**, perte d'un hôte ADB absorbée, validation UX opérateurs pilotes, dossier conformité données (rétention, chiffrement, secrets) remis. |

---

## KPI et seuils réalistes

| KPI | S1 (1-2 dev.) | S2 (10-20 dev.) | S3 (50-100 dev.) |
|---|---:|---:|---:|
| Taux de complétion métier vérifié (reprises automatiques incluses) | ≥ 85 % | ≥ 90 % | ≥ 93 % |
| Exécutions sans intervention humaine (hors `needs_review` légitimes) | ≥ 75 % | ≥ 85 % | ≥ 90 % |
| Sécurité d'état (zéro double effet métier) | 100 % | 100 % | 100 % |
| **Appels LLM par run en chemin nominal** | 0 | 0 | 0 |
| **Appels LLM moyens par run (récupération incluse)** | — | ≤ 3 | ≤ 2 |
| Délai p95 d'allocation (API → bail) | ≤ 2 s | ≤ 5 s | ≤ 10 s |
| Délai p95 d'arrêt effectif (`cancel` → bail révoqué, ADB stoppé) | ≤ 3 s | ≤ 5 s | ≤ 5 s |
| **Délai p95 de neutralisation d'un worker zombie** (bail expiré → process tué) | — | ≤ 10 s | ≤ 10 s |
| Temps opérateur économisé vs manuel | Référence | ≥ 50 % | ≥ 70 % |

Métriques de supervision : taux de 429 (< 2 %), latence d'étape scriptée, latence boucle de récupération, taux de quarantaine, taux de `needs_review`, coût LLM par run, consommation des plafonds glissants par compte.

---

## Matrice des risques corrigée

| Risque | Parade et responsable |
|---|---|
| **Device Code non viable** (suspension de comptes, plafonds glissants, app-server non contractuel) | Spike 48h + avis viabilité au J3 ; `VisionProvider` abstrait avec plan B (API payante / VLM local) câblé en S1 ; décision de provider tranchée avant S2. **Resp. : Backend + Direction**. |
| **Charge LLM structurellement trop élevée** | Mode scripté par défaut, LLM uniquement en récupération avec budget borné ; KPI "0 appel en chemin nominal". **Resp. : Runtime**. |
| **Worker zombie** (process survivant, démon ADB partagé) | Epoch vérifié dans le wrapper ADB + watchdog hôte `SIGKILL` + réinitialisation device par le repreneur. **Resp. : Runtime + Exploitation**. |
| **Crash sur action non-idempotente → explosion de `needs_review`** | Vérification d'état post-crash scriptée par workflow avant tout passage en revue humaine. **Resp. : Runtime + Métier**. |
| **Appels LLM cachés dans Artemis** | Audit statique J1 ; variables d'API retirées des workers ; test "zéro appel non routé" en sortie S1. **Resp. : Runtime**. |
| **Dérive de l'app cible (changement d'UI)** | Workflows versionnés ; sélecteurs multiples par étape ; la récupération LLM signale les écarts ; alerte si taux de récupération d'une étape > seuil. **Resp. : Métier + Runtime**. |
| **Saturation matérielle à 100** | Budget chiffré fin S1 ; test ADB pur 25-50 en S2 ; quarantaine auto. **Resp. : Exploitation**. |
| **Données personnelles dans les captures / secrets** | Chiffrement, rétention, masquage ; coffre de secrets ; dossier conformité en S3. **Resp. : Backend + Exploitation**. |
| **Surcharge S2** | Pool de comptes et filtres SSE rétrogradés en P1/S3 ; S2 recentré sur fencing, résilience et les 3 workflows. **Resp. : Produit**. |
| **Divergence du fork Artemis** | Patchs versionnés, rebase trimestriel documenté, tests de non-régression sur les 3 workflows. **Resp. : Runtime**. |

---

## Checklist Ready-to-Build (Prérequis J1)

- [ ] **Code Artemis** : fork créé, commit de référence tagué, appels `llm/router.py` et fallbacks de `agents/flash/runner.py` cartographiés.
- [ ] **Accès LLM** : 2-3 comptes Device Code de test pour le Spike **et** une clé API entreprise (plan B) disponible pour activation immédiate si No-Go.
- [ ] **Métier** : 3 workflows documentés étape par étape avec sélecteurs identifiés, assertions de succès, actions `non_idempotent` et **procédure de vérification d'état** associée à chacune.
- [ ] **Infra** : 1 physique, 1 émulateur, Codex app-server, MinIO et collecte de logs accessibles ; grille de budget matériel prête à remplir.
- [ ] **Secrets & données** : coffre de secrets choisi ; politique de rétention des captures validée avec le client.
- [ ] **Contrat** : schéma PostgreSQL (`runs`, `executions`, `device_leases`, `action_journal`, `workflows`), format de workflow, interface `VisionProvider` et contrat SSE validés par le binôme Backend/Frontend.