# Émulateurs préparés et persistants

L’utilisateur crée un émulateur dans Appareils, choisit ses applications, le démarre et le prépare, puis lance un parcours sur cet appareil. Arrêter et redémarrer conserve les applications et leurs données. Les appareils externes restent des connexions déclarées et ne reçoivent pas de commandes Docker.

## Contrat de cette tranche

- Création par nom, hôte actif prérempli et applications ; identifiants Android et ressources internes générés automatiquement. Quatre émulateurs gérés au maximum par hôte pour cette version.
- Chrome est fourni par l’image Android locale ; ajout d’applications par APK autonome importé depuis le navigateur. Le serveur extrait le nom du package ; aucun téléchargement d’URL ni identifiant de magasin à saisir.
- La configuration peut être enregistrée hors ligne. « Démarrer et préparer » démarre Android et installe les APK sélectionnés. Les applications souhaitées et celles vérifiées sont distinguées. Décocher une application ne supprime pas ses données ni son installation existante.
- « Lancer un parcours » cible l’émulateur préparé et réellement connecté. Le direct et les captures restent dans Exécutions. Arrêt et reconfiguration sont refusés pendant une réservation ou une préparation déjà en attente.
- Admin et Operator gèrent les appareils ; Builder peut lancer un parcours sur un appareil prêt ; les rôles de consultation voient les états.

## Implémentation et frontières

Le domaine émulateur reste dans l’API Python pendant la migration progressive. Les trois lectures Go existantes conservent leur contrat. Une migration additive stocke les émulateurs, le catalogue APK et les opérations. Chaque préparation/démarrage/arrêt produit un run et une exécution dans la file PostgreSQL existante. Un enregistrement interne lie l’opération à cette exécution ; les paramètres envoyés par un client ne peuvent pas déclencher de commande de gestion.

Le worker conserve son verrou hôte, son bail avec époque, son watchdog, son journal et ses preuves. Lui seul accède à Docker. Conteneurs et volumes ont des noms générés et des labels vérifiés ; image, réseau, limites et commande viennent du déploiement. Aucun socket Docker, port ADB ou chemin hôte n’est publié dans le navigateur. L’AVD se trouve dans un volume dédié et n’est créé qu’une seule fois.

Les commandes ADB choisissent explicitement le serveur de l’émulateur concerné. Les observations de connexion et le direct utilisent le même adressage, sans changer celui du banc historique. Une réponse Docker incertaine ou une perte du bail conserve la quarantaine ; aucune répétition automatique d’une opération incertaine.

Les APK sont bornés à 128 Mio, contrôlés comme archives APK autonomes et analysés par `aapt` avec délai. Leur nom de stockage est généré ; leur empreinte est vérifiée avant installation. Un APK installé est contrôlé par son package et son empreinte sur Android. Les APK nécessitant plusieurs fichiers, le Play Store, les snapshots clonables et d’autres versions Android ne font pas partie de cette tranche.

## Vérification

Tests Python : `.venv/bin/python -m pytest orchestrator-api/tests -q`. Frontend : `npm --prefix web-ui test`, puis `npm --prefix web-ui run build`. Les tests PostgreSQL vérifient idempotence, réservation et refus d’accès ; les tests du runtime utilisent un faux client Docker. La recette réelle doit créer un émulateur distinct du banc historique, installer un APK, arrêter/redémarrer, vérifier sa persistance puis réussir le parcours Wikipédia. Le navigateur doit vérifier les états, droits, erreurs et dispositions mobile/RTL.

Sources de conception : [données et options de l’émulateur Android](https://developer.android.com/studio/run/emulator-commandline), [commandes ADB](https://developer.android.com/tools/adb), [volumes Docker](https://docs.docker.com/engine/storage/volumes/).

Les identifiants des raccourcis du catalogue correspondent aux fiches officielles : [Snapchat](https://play.google.com/store/apps/details?id=com.snapchat.android), [LinkedIn](https://play.google.com/store/apps/details?id=com.linkedin.android), [Instagram](https://play.google.com/store/apps/details?id=com.instagram.android), [TikTok](https://play.google.com/store/apps/details?id=com.zhiliaoapp.musically). Ces liens identifient les applications ; ils ne sont pas utilisés comme sources de téléchargement automatique.
