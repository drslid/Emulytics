# Installer Emulytix et son émulateur local

Depuis un checkout du dépôt, lancer :

```bash
./scripts/install.sh --accept-android-license
```

L’option confirme l’acceptation des [conditions Android SDK](https://developer.android.com/studio/terms). Sans cette option, une image Android manquante n’est pas construite. L’installateur reste non interactif : une étape qui échoue explique la cause et s’arrête ; relancer la même commande reprend en conservant les accès et les données.

Cette première distribution cible **Linux x86_64 avec KVM**, Docker Engine, le plugin Docker Compose, Bash et Python 3. Elle nécessite au moins 8 Gio de RAM physique, 4 Gio disponibles au lancement et 25 Gio libres pour les images et les données. Les archives Android représentent environ 1,8 Go de téléchargement ; les bases Docker et dépendances applicatives s’y ajoutent. Docker Desktop macOS/Windows, ARM et les serveurs Docker distants ne sont pas pris en charge par cet installateur d’émulateur.

Pour vérifier les prérequis sans créer de configuration ou démarrer un service :

```bash
./scripts/install.sh --check
```

## Ce que la commande prépare

1. Vérifie Docker, Compose, le moteur local, KVM, la mémoire et les disques concernés.
2. Crée `.env.console` en mode privé, uniquement s’il manque. Un fichier existant est conservé octet pour octet ; les chemins redirigés par lien symbolique et les droits trop ouverts sont refusés.
3. Construit `emulytix/android-runtime:0.9.0` si nécessaire, depuis le Dockerfile suivi par Git et les archives officielles vérifiées par SHA-256.
4. Vérifie réellement l’accélération KVM dans l’image sélectionnée, avant de lancer les services applicatifs.
5. Lance PostgreSQL, les migrations, les API, l’ordonnanceur et l’interface ; initialise le premier accès seulement si l’installation n’en possède pas déjà un.
6. Prépare le banc Android privé et le worker, en réutilisant son appareil enregistré. Les nouveaux bancs créent leur AVD uniquement au premier démarrage. Un banc arrêté n’est redémarré que si son marqueur et sa commande confirment cette conservation.

La console est accessible sur [http://localhost:3100](http://localhost:3100). Pour consulter le mot de passe temporaire encore valide, exécuter `scripts/account.sh initial-access` dans un terminal privé. Le compte `admin` doit ensuite changer ce mot de passe et activer le 2FA. L’installateur ne réinitialise aucun compte existant et n’imprime pas les secrets dans ses journaux ordinaires.

Le lancement de l’installateur ne crée pas de nouvelle exécution. Le worker peut néanmoins reprendre les demandes déjà en attente sur `bench-host` : relancer l’installation sur une console utilisée ne constitue pas une mise en pause de ses travaux.

## Images et données existantes

Les variables `EMULYTIX_BENCH_IMAGE` et `EMULYTIX_MANAGED_IMAGE` peuvent désigner des images personnalisées déjà présentes. Les valeurs de l’environnement courant prennent le pas sur `.env.console`, puis sur la valeur par défaut. Une image personnalisée absente déclenche un message explicite ; elle n’est ni remplacée par une autre ni téléchargée implicitement.

Les scripts ne suppriment aucun volume PostgreSQL ou profil d’émulateur existant. Le banc initial et les profils gérés conservent des cycles de vie distincts. Arrêter ou supprimer volontairement des conteneurs avec d’autres commandes Docker reste une action d’administration extérieure à l’installateur.

Un ancien banc arrêté dont la commande recrée l’AVD est refusé, sans démarrage ni remplacement. Conserver son conteneur et sauvegarder ses données avant de préparer une migration ; le helper ne modifie pas automatiquement sa commande ni sa politique Docker de redémarrage. Un ancien banc déjà allumé reste utilisable sans être redémarré par l’installateur. Les redémarrages effectués hors du helper, notamment par Docker, restent soumis à la commande de cet ancien conteneur.

Ne pas supprimer `.env.console` pour résoudre une erreur : il contient notamment la clé nécessaire pour déchiffrer les facteurs et connexions de l’installation. Sauvegarder ce fichier avec les données, dans un emplacement privé. La restauration complète d’une sauvegarde doit encore être vérifiée dans une recette dédiée.

## Runtime Android reproductible

`android-runtime/Dockerfile.console` fixe le digest de la base Java 17. `android-runtime/sdk-packages.sha256` fixe les URL et empreintes de quatre archives Google :

| Composant | Version |
|---|---|
| Android / image système Google APIs | API 29, x86_64, révision 13 |
| Android Emulator | 37.2.12, build 16428233 |
| Platform Tools | 37.0.1 |
| Command-line Tools | 12.0, build 11076708 |

Chrome est celui livré dans cette image système. Aucun APK n’est récupéré depuis un site tiers. Ce socle Android 10 correspond au parcours de recette actuel ; il ne garantit pas la compatibilité des versions récentes de Snapchat, LinkedIn, Instagram ou TikTok. Leur préparation exige des APK compatibles et approuvés. Le Dockerfile historique ciblant Android 14 est séparé de ce runtime vérifié.

La construction ne dépend plus d’une image privée créée manuellement sur la machine de développement. Elle n’est pas une promesse d’identité binaire de tous les paquets système : les mises à jour APT restent résolues lors du build. Les images construites pour une diffusion précise doivent être identifiées par digest et conservées dans le registre choisi, en respectant les conditions de redistribution des composants Android et Google. Le workflow fourni construit localement et ne publie pas ces images.

## Vérifications automatiques et publication GitHub

`.github/workflows/ci.yml` vérifie l’API et le worker avec un PostgreSQL jetable, le frontend, les types, le build, l’audit npm, les tests Go avec détection de concurrence, `go vet`, les scripts Bash et la configuration Compose. Il n’utilise aucun compte ou secret de l’installation locale. Les actions sont épinglées par commit ; les paquets applicatifs sont installés depuis les verrous du dépôt.

Le workflow manuel `android-runtime.yml` reconstruit l’image depuis les archives officielles après acceptation explicite des conditions Android SDK. Il vérifie les outils et la révision système. Il ne démarre pas un émulateur et ne remplace pas une recette KVM du parcours Chrome/Wikipédia.

La recette locale du 8 novembre 2026 a construit l’image depuis ces sources, créé puis démarré un conteneur et un réseau éphémères distincts du banc existant, vérifié l’accélération KVM, Android API 29 et Chrome `74.0.3729.185` préinstallé. Le conteneur et le réseau ont ensuite été retirés. Les tests ciblés de l’installateur, de l’accès initial et du helper Android passent ; la syntaxe Bash, Actionlint et le contrôle réel `--check` passent également. Cette recette ne remplace pas l’installation complète d’un clone vierge avec toutes ses étapes applicatives.

Une recette supplémentaire a démarré deux fois le même nouveau banc isolé, avec arrêt Docker entre les deux. Un fichier témoin écrit dans `/data/local/tmp`, suivi d’un `sync` Android, et l’empreinte du fichier AVD `.ini` sont restés identiques après le second démarrage. Les dates de démarrage Docker ont bien changé. Le banc historique a conservé son identifiant, son état actif et sa date de démarrage ; aucune API ou base applicative n’a été utilisée pendant cet essai. Les ressources éphémères ont été supprimées. Cette preuve porte sur le redémarrage du conteneur, pas sur sa suppression/recréation ni sur une restauration depuis sauvegarde.

La CI doit être exécutée sur le dépôt GitHub de destination avant de considérer une version publiable. Le propriétaire a choisi [Apache-2.0](../LICENSE) pour le code original d’Emulytix ; les composants tiers conservent leurs propres licences et conditions, indiquées dans [NOTICE](../NOTICE). La recette d’un clone vierge, la sauvegarde/restauration et les tests avec les applications sociales restent à distinguer des contrôles unitaires et des builds locaux.

Références officielles : [avdmanager](https://developer.android.com/tools/avdmanager), [émulateur en ligne de commande](https://developer.android.com/studio/run/emulator-commandline), [outils Android](https://developer.android.com/studio#command-tools), [dépôt des outils SDK](https://dl.google.com/android/repository/repository2-3.xml), [dépôt Google APIs](https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml).
