# Préparation de la publication GitHub — 8 novembre 2026

Après la sélection des huit chantiers, le dépôt fournit un installateur et la recette de construction du runtime Android. Cette image a été reconstruite et démarrée sur un banc isolé. La recette complète depuis un clone vierge reste à effectuer ; la CI est fournie mais n’a pas encore été exécutée sur le GitHub de destination. Voir la [livraison produit](product-delivery-2026-11-08.md) et le [guide d’installation](installation-console.md).

Le contrôle initial de préparation à la publication a été effectué en lecture seule, sans suppression ni choix de licence. Le rapport distingue ses constats des corrections ensuite apportées pendant l’[audit fonctionnel](full-audit-2026-11-08.md). Aucune installation vierge n’a été lancée.

## Fichiers suivis et signatures de secrets

Le contrôle a parcouru **43 commits**, **281 fichiers suivis**, **298 chemins de travail non ignorés** et **733 blobs texte historiques uniques**. Les fichiers binaires et les contenus supérieurs à 2 Mo n’ont pas subi cette recherche textuelle.

Les signatures cherchées couvrent les blocs de clés privées, les formats usuels de clés OpenAI et GitHub, les identifiants AWS, les JWT littéraux et une affectation littérale de clé Fernet Emulytix. **Aucun match n’a été trouvé**, dans les fichiers courants ni dans les blobs historiques parcourus. Aucun nom `.env` privé, `auth.json`, `initial-access.json` ou fichier de clé/certificat n’est suivi, ni retrouvé dans la liste des chemins historiques. Ce résultat ciblé ne garantit pas l’absence de tous les formats de secrets ou de mots de passe arbitraires.

`git check-ignore` confirme l’exclusion de `.env.console`, du premier accès local, des fichiers de session de recette et du cache TypeScript. Le fichier `.env.example` est volontairement suivi. Les règles pertinentes se trouvent dans [`.gitignore`](../.gitignore). Les valeurs des identifiants n’ont pas été affichées ou copiées dans le rapport.

## Points à traiter

| Référence | Priorité | Constat et preuve | Correction minimale proposée |
|---|---|---|---|
| R1 | Recette fournie ; clone vierge à tester | **La dépendance à l’ancienne image locale 0.8.1 est remplacée par une recette suivie.** [`Dockerfile.console`](../android-runtime/Dockerfile.console) et les archives Google vérifiées construisent `emulytix/android-runtime:0.9.0`, Android API29 avec Chrome. L’installateur contrôle Docker/Compose/KVM et les ressources. Construction et démarrage KVM isolés réussis. | Rejouer l’installation complète depuis un clone et une machine sans cache ; conserver les preuves de première connexion et du premier parcours. Ne pas confondre cette recette Android10 avec une validation Android14. |
| R2 | Corrigé pendant l’audit | **Le build Python résolvait des versions variables.** `requirements.txt` conserve les dépendances directes, mais les images de production utilisent désormais [`requirements.lock`](../orchestrator-api/requirements.lock), avec 42 versions validées et leurs empreintes SHA-256. L’outil `pip` embarqué est mis à jour en 26.3. | Les builds API/ordonnanceur/worker installent avec `--require-hashes`. La régénération sans mise à jour des versions a été vérifiée. Les bases système Docker et l’image Android doivent encore être versionnées dans la procédure de release ; ce verrou ne valide pas à lui seul une installation complète vierge. |
| R3 | CI fournie ; exécution GitHub à vérifier | **Les workflows suivis vérifient API/PostgreSQL jetable, frontend, Go, Bash et Compose.** Un workflow manuel construit le runtime Android après acceptation explicite de ses conditions. Les actions sont épinglées par commit. | Déclencher la CI dans le dépôt GitHub choisi et vérifier ses résultats avant diffusion. Le workflow Android ne remplace pas une recette d’exécution KVM. Aucun secret d’exploitation n’est requis. |
| R4 | Résolu — Apache-2.0 | **Le propriétaire a choisi Apache-2.0 après l’audit.** Le texte officiel figure dans [LICENSE](../LICENSE), avec un [NOTICE](../NOTICE) distinguant les composants et ressources tiers. Les métadonnées npm du projet utilisent le même identifiant. | Conserver les licences des drapeaux, polices et dépendances ; cette décision ne remplace pas les conditions des composants téléchargés séparément. |

## Conditions pour une installation depuis un clone neuf

La procédure actuelle de console nécessite Bash, Python 3, Docker avec Compose, l’accès au démon Docker, les droits d’écriture du répertoire de travail et le téléchargement des images et dépendances. Le bootstrap utilise des primitives POSIX, dont `fcntl`, dans [`scripts/bootstrap-console.py`](../scripts/bootstrap-console.py), ligne 5. L’installation documentée ne constitue donc pas une validation native de toutes les plateformes.

Pour exécuter le parcours Android, il faut en plus un hôte disposant de `/dev/kvm`, l’image construite par la recette du dépôt et son image système API29. Le worker doit rejoindre le réseau privé du banc. Une console web démarrée sans ce worker et ce périphérique n’établit pas la réussite d’une automatisation.

Le premier accès doit être créé automatiquement sur base vierge, puis exiger le remplacement du mot de passe et l’activation du TOTP. Une seconde exécution de l’installation doit conserver comptes, secrets, données et historique. La sauvegarde doit porter ensemble sur la base, les preuves nécessaires et la clé de chiffrement existante ; cette clé ne doit pas être recréée lors d’un redémarrage ordinaire.

## Portée des preuves

Les tests et recettes déjà archivés valident des comportements sur des bases jetables et sur le banc local présent à l’époque de leur exécution. Leur existence ne remplace pas un essai de clone vierge, de build sans cache, de téléchargement d’image Android et de restauration de sauvegarde. Ces quatre essais n’ont pas été effectués dans ce contrôle ciblé.

Aucun scan de secrets ne dispense d’une nouvelle vérification du contenu exact de la release. Les fichiers encore non suivis ou modifiés dans l’intégration en cours doivent être relus et testés avant leur ajout à une version ; ils n’ont pas été supprimés ou validés pour publication par cet audit.
