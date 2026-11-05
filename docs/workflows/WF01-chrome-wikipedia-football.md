# WF01 — Installer Chrome et rechercher « football » sur Wikipédia

Demande utilisateur du 5 novembre 2026 : depuis l'émulateur, installer Chrome, aller sur Wikipédia et faire une recherche sur le football.

Statut : version exécutable livrée et deux exécutions réussies via l'API et le worker sur le banc Android 10. L'installation d'un APK neuf et la cible Android 14 restent à valider.

## Résultat attendu

Sur un émulateur Android, Google Chrome est disponible, Wikipédia est ouvert et une recherche du terme `football` est effectuée dans l'interface du site. Le résultat doit présenter le sujet Football sur le domaine Wikipédia. La langue française est retenue pour le premier banc.

La recherche française [Spécial:Recherche?search=football](https://fr.wikipedia.org/wiki/Sp%C3%A9cial:Recherche?search=football) redirige actuellement vers l'article [Football](https://fr.wikipedia.org/wiki/Football). Cette redirection est acceptable. Ouvrir directement l'article ou appeler une API depuis le backend ne prouve pas que la recherche a été faite dans Chrome.

## Préconditions et installation

- Un émulateur identifié par son hôte et son serial, dont le démarrage Android est terminé, avec accès réseau et HTTPS opérationnel.
- Relever Android, ABI, dimensions d'écran et langue, puis figer la version de Chrome pour les mesures reproductibles.
- Le package attendu est `com.android.chrome`. Si Chrome est déjà installé et utilisable, conserver cette installation et enregistrer sa version.
- Sinon, installer Chrome via une source identifiée et compatible avec l'émulateur, puis vérifier package, signature et version. Google documente l'installation via le Play Store pour Android 10 ou supérieur : [aide officielle](https://support.google.com/chrome/answer/95346?co=GENIE.Platform%3DAndroid&hl=fr).
- Si le banc n'a pas de Play Store utilisable, fournir un artefact Chrome vérifié pour l'ABI cible, avec prise en charge des APK fractionnés si nécessaire. Le chemin et l'empreinte de l'artefact deviennent des entrées de provisionnement. Aucun APK tiers n'est téléchargé implicitement.
- Les écrans de premier lancement, de connexion, de navigateur par défaut ou de choix de moteur sont relevés sur le banc. Le parcours de navigation n'a pas besoin d'une connexion à un compte Google.

## Étapes et assertions

| ID | Action | Assertion et preuve | Reprise |
|---|---|---|---|
| 01 | Examiner l'émulateur ciblé | Serial attendu, boot terminé, Android/ABI relevés | Si offline, attendre de façon bornée ; si non autorisé, déclarer le blocage |
| 02 | Garantir la présence de Chrome ; installer si absent | `com.android.chrome` présent et version enregistrée | Après interruption d'installation, vérifier package/version avant de réinstaller |
| 03 | Ouvrir Chrome et traiter les écrans de premier lancement identifiés | Activité Chrome au premier plan, interface de navigation disponible | Rejouer seulement les choix de banc documentés ; écran inconnu visible comme erreur |
| 04 | Ouvrir `https://fr.wikipedia.org/` dans Chrome | Domaine Wikipédia observé et contenu du site affiché | Nouvelle navigation autorisée ; échec HTTPS ou réseau signalé |
| 05 | Activer la recherche de Wikipédia | Champ de recherche visible et focalisé, sélecteur observé sur le banc | Réidentifier le champ ; ne pas utiliser un clic arbitraire |
| 06 | Saisir `football` | Valeur du champ observée | Remplacer le contenu du champ pour éviter un terme dupliqué |
| 07 | Soumettre la recherche | Navigation ou résultats Wikipédia observés | Si interruption, examiner URL et contenu avant une nouvelle soumission |
| 08 | Vérifier le résultat et conserver la preuve | Chrome au premier plan, domaine Wikipédia, résultat ou article Football ; capture et observation UI horodatées | Si preuve insuffisante, échec explicite ou revue ; ne pas déclarer un succès sur le seul retour ADB |

Les sélecteurs ont été relevés sur le banc : `searchIcon` pour la recherche du site, `android.widget.EditText` avec `focused=true` pour la saisie, puis `firstHeading` avec `text=Football`. Les fixtures UI sont conservées dans `orchestrator-api/tests/fixtures/wf01/`. Les coordonnées des taps sont calculées depuis les bounds de l'élément identifié, sans emplacement fixe.

L'installation constitue une modification persistante de l'appareil ; son résultat doit être réconcilié après interruption. La navigation et la recherche sont rejouables sous les conditions du tableau. Aucun effacement de données Chrome ni désinstallation n'est requis pour répéter le parcours.

## Critères d'acceptation

- Exécution sans LLM sur le chemin nominal, avec délais et nombre de tentatives bornés.
- Recherche effectuée depuis l'interface de Wikipédia, avec preuve du terme saisi et du résultat affiché.
- Répétition du parcours avec Chrome déjà présent, sans réinstallation ou saisie cumulée inutile.
- Erreurs explicites si l'APK est incompatible, si l'émulateur est offline, si le réseau échoue ou si un écran non reconnu apparaît.
- Passage de toutes les actions par le contrôle exclusif du device avant branchement au worker ; mêmes garanties pour ADB, UIAutomator et récupération.

## Banc et validation

L'hôte expose `/dev/kvm`. Un nouveau banc isolé a été créé avec le script `android-runtime/scripts/start-bench.sh` : Android 10/x86_64, écran 320 × 640 et Chrome 74.0.3729.185 préinstallé. Aucun service d'un autre projet n'a été modifié.

La [version exécutable](../../workflows/chrome-wikipedia-football.v1.json) comporte 11 étapes. Les conditions facultatives gèrent les écrans de bienvenue et la proposition de traduction observés sur ce banc. La prévalidation de toutes les étapes précède les commandes Android ; chaque étape conserve assertion, capture et observation XML.

Deux runs complets ont réussi par l'API et le worker, avec epochs 1 et 2 : 11 étapes validées, 8 actions à effet confirmées et 19 événements par exécution, sans appel LLM. Le terme `football` a été saisi dans l'interface, puis l'URL et le titre Football ont été vérifiés. Les preuves se trouvent dans [validation.json](../../storage/wf01-worker/validation.json), avec [saisie](../../storage/wf01-worker/run-1-query-entered.png) et [résultat](../../storage/wf01-worker/run-1-result.png).

Chrome était présent et déjà initialisé lors de ces deux runs du worker. Le cas « déjà installé » et la répétition sont démontrés ; l'installation d'un nouvel APK, les branches de premier lancement par le worker sur un profil vierge, Android 14 et le device physique restent à tester. Le banc temporaire est arrêté après validation et peut être recréé par le script.

P02 reste partiel : WF01 est défini et vérifié sur ce banc ; les deux autres workflows doivent être précisés. Le worker local n'intègre pas encore le fork ARTEMIS ni la récupération LLM.
