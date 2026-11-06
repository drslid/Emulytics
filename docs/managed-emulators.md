# Émulateurs préparés et persistants

L’utilisateur crée un émulateur dans Appareils et choisit ses applications. Trois commandes distinctes permettent de l’allumer, de préparer ses applications et de l’éteindre. Un parcours nécessite ensuite un appareil préparé et réellement connecté. Éteindre puis rallumer conserve les applications et leurs données. Les appareils externes restent des connexions déclarées et ne reçoivent pas de commandes Docker.

## Contrat de cette tranche

- Création par nom, hôte actif prérempli et applications ; identifiants Android et ressources internes générés automatiquement. Quatre émulateurs gérés au maximum par hôte pour cette version.
- Chrome est fourni par l’image Android locale ; ajout d’applications par APK autonome importé depuis le navigateur. Le serveur extrait le nom du package ; aucun téléchargement d’URL ni identifiant de magasin à saisir.
- La configuration peut être enregistrée hors ligne. « Allumer » démarre Android sans installer d’application ; les APK manquants ne bloquent pas cette commande. « Éteindre » conserve le volume, les applications et leurs données ; le prochain allumage réutilise le même AVD.
- « Préparer les applications » installe les applications choisies et vérifie leur empreinte. Cette commande peut allumer Android si nécessaire, mais exige les APK sélectionnés : un fichier manquant bloque uniquement la préparation. Les applications souhaitées et celles vérifiées sont distinguées. Décocher une application ne supprime pas ses données ni son installation existante.
- L’état `running` correspond à « Allumé · à préparer ». « Lancer un parcours » exige l’état `ready` (« Prêt ») et une connexion Android réellement confirmée ; un émulateur simplement allumé ne suffit pas. Le direct et les captures restent dans Exécutions. Les commandes de gestion et la reconfiguration sont refusées pendant une réservation ou une opération déjà en attente.
- Admin et Operator gèrent les appareils ; Builder peut lancer un parcours sur un appareil prêt ; les rôles de consultation voient les états.

## Implémentation et frontières

Le domaine émulateur reste dans l’API Python pendant la migration progressive. Les trois lectures Go existantes conservent leur contrat. Une migration additive stocke les émulateurs, le catalogue APK et les opérations. Chaque préparation/démarrage/arrêt produit un run et une exécution dans la file PostgreSQL existante. Un enregistrement interne lie l’opération à cette exécution ; les paramètres envoyés par un client ne peuvent pas déclencher de commande de gestion.

Le worker conserve son verrou hôte, son bail avec époque, son watchdog, son journal et ses preuves. Lui seul accède à Docker. Conteneurs et volumes ont des noms générés et des labels vérifiés ; image, réseau, limites et commande viennent du déploiement. Aucun socket Docker, port ADB ou chemin hôte n’est publié dans le navigateur. L’AVD se trouve dans un volume dédié et n’est créé qu’une seule fois.

Déploiement de la séparation des commandes : attendre que la file et les baux soient libres, arrêter les anciens workers, appliquer la migration 015, puis démarrer les nouveaux workers avant de remplacer l’API. Un ancien worker ne doit pas consommer les nouvelles opérations d’allumage, car il déclarerait leur préparation terminée sans la vérifier. Les nouveaux workers restent compatibles avec les anciennes opérations déjà enregistrées.

Les commandes ADB choisissent explicitement le serveur de l’émulateur concerné. Les observations de connexion et le direct utilisent le même adressage, sans changer celui du banc historique. Une réponse Docker incertaine ou une perte du bail conserve la quarantaine ; aucune répétition automatique d’une opération incertaine.

Les APK sont bornés à 128 Mio, contrôlés comme archives APK autonomes et analysés par `aapt` avec délai. Leur nom de stockage est généré ; leur empreinte est vérifiée avant installation. Un APK installé est contrôlé par son package et son empreinte sur Android. Les APK nécessitant plusieurs fichiers, le Play Store, les snapshots clonables et d’autres versions Android ne font pas partie de cette tranche.

## Vérification

Tests Python : `.venv/bin/python -m pytest orchestrator-api/tests -q`. Frontend : `npm --prefix web-ui test`, puis `npm --prefix web-ui run build`. Les tests PostgreSQL vérifient idempotence, réservation, permissions, état `running`, refus des parcours non préparés et compatibilité des anciens workflows. Les tests du runtime vérifient que l’allumage n’installe rien, y compris si un APK importé manque sur Android, et ne déclare `ready` que si les packages sélectionnés correspondent.

Recette du 6 novembre 2026 : **507 tests API, 89 tests frontend, TypeScript et build réussis**. Depuis les boutons de la console locale, le profil existant avec les quatre APK sociaux absents s’allume, confirme sa connexion Android, affiche « Allumé · à préparer », puis s’éteint en conservant le même volume. Les deux opérations réussies ne contiennent aucune installation et restent dans l’historique. Les vingt et un états d’exécution précédents et la configuration du profil sont préservés ; les comptes temporaires sont supprimés. Vingt-quatre contrôles WCAG finaux couvrent cartes et fiches Admin/Viewer en français, allemand et arabe, à 320/1440 px ; deux contrôles supplémentaires couvrent l’arrêt et l’allumage réels. La préparation avec APK signé et le parcours Wikipédia avaient été vérifiés lors de la tranche précédente ; les applications sociales restent à importer et à valider. Preuves locales : `storage/emulator-power-review/`.

Sources de conception : [données et options de l’émulateur Android](https://developer.android.com/studio/run/emulator-commandline), [commandes ADB](https://developer.android.com/tools/adb), [volumes Docker](https://docs.docker.com/engine/storage/volumes/).

Les identifiants des raccourcis du catalogue correspondent aux fiches officielles : [Snapchat](https://play.google.com/store/apps/details?id=com.snapchat.android), [LinkedIn](https://play.google.com/store/apps/details?id=com.linkedin.android), [Instagram](https://play.google.com/store/apps/details?id=com.instagram.android), [TikTok](https://play.google.com/store/apps/details?id=com.zhiliaoapp.musically). Ces liens identifient les applications ; ils ne sont pas utilisés comme sources de téléchargement automatique.
