# Préparation de la publication GitHub — 8 novembre 2026

La console locale possède une procédure de démarrage et un banc Android documentés. Le dépôt ne suffit toutefois pas encore à reproduire l’installation complète et sa première automatisation sur une machine vierge : l’image utilisée pour ce banc est un prérequis local. La publication du code et la promesse d’une installation complète en un clic sont deux jalons distincts.

Le contrôle initial de préparation à la publication a été effectué en lecture seule, sans suppression ni choix de licence. Le rapport distingue ses constats des corrections ensuite apportées pendant l’[audit fonctionnel](full-audit-2026-11-08.md). Aucune installation vierge n’a été lancée.

## Fichiers suivis et signatures de secrets

Le contrôle a parcouru **43 commits**, **281 fichiers suivis**, **298 chemins de travail non ignorés** et **733 blobs texte historiques uniques**. Les fichiers binaires et les contenus supérieurs à 2 Mo n’ont pas subi cette recherche textuelle.

Les signatures cherchées couvrent les blocs de clés privées, les formats usuels de clés OpenAI et GitHub, les identifiants AWS, les JWT littéraux et une affectation littérale de clé Fernet Emulytix. **Aucun match n’a été trouvé**, dans les fichiers courants ni dans les blobs historiques parcourus. Aucun nom `.env` privé, `auth.json`, `initial-access.json` ou fichier de clé/certificat n’est suivi, ni retrouvé dans la liste des chemins historiques. Ce résultat ciblé ne garantit pas l’absence de tous les formats de secrets ou de mots de passe arbitraires.

`git check-ignore` confirme l’exclusion de `.env.console`, du premier accès local, des fichiers de session de recette et du cache TypeScript. Le fichier `.env.example` est volontairement suivi. Les règles pertinentes se trouvent dans [`.gitignore`](../.gitignore). Les valeurs des identifiants n’ont pas été affichées ou copiées dans le rapport.

## Points à traiter

| Référence | Priorité | Constat et preuve | Correction minimale proposée |
|---|---|---|---|
| R1 | P0 pour l’installation complète | **Le clone vierge ne fournit pas l’image Android de validation.** [`start-bench.sh`](../android-runtime/scripts/start-bench.sh), lignes 5 et 15–29, attend `/dev/kvm`, inspecte une image déjà présente et vérifie Android API 29. Le [README](../README.md), lignes 85 et 306, annonce explicitement cette dépendance locale. [`android-runtime/Dockerfile`](../android-runtime/Dockerfile), ligne 1, cible une autre image Android 14 ; aucune recette suivie ne reconstruit l’image locale 0.8.1 attendue. | Fournir une recette de build versionnée ou une image distribuée avec révision vérifiable, puis tester depuis une machine sans cache. L’installateur doit expliquer le manque de virtualisation ou d’image et distinguer « console prête » de « appareil exécutable ». |
| R2 | Corrigé pendant l’audit | **Le build Python résolvait des versions variables.** `requirements.txt` conserve les dépendances directes, mais les images de production utilisent désormais [`requirements.lock`](../orchestrator-api/requirements.lock), avec 42 versions validées et leurs empreintes SHA-256. L’outil `pip` embarqué est mis à jour en 26.3. | Les builds API/ordonnanceur/worker installent avec `--require-hashes`. La régénération sans mise à jour des versions a été vérifiée. Les bases système Docker et l’image Android doivent encore être versionnées dans la procédure de release ; ce verrou ne valide pas à lui seul une installation complète vierge. |
| R3 | P1 | **La publication n’a pas de contrôle CI suivi.** La liste Git ne contient aucun fichier `.github/workflows/`. Les commandes et tests documentés sont utiles, mais ne prouvent pas qu’un commit ou une release les exécute automatiquement, ni qu’une installation neuve démarre. | Ajouter une pipeline reprenant les tests existants API, Go et frontend, le build et un contrôle de migrations sur base jetable. Ajouter une recette d’installation console sans cache ; réserver la validation KVM à un exécuteur adapté. Aucun accès de production n’est nécessaire pour ces vérifications. |
| R4 | Décision avant diffusion comme projet ouvert | **La licence du projet n’est pas définie à la racine.** Les seuls fichiers de licence suivis concernent les drapeaux et polices sous `web-ui/public/`. Ils ne définissent pas la licence du code Emulytix. | Faire choisir au propriétaire la licence du projet et conserver les notices tierces. Ne pas déduire une licence du simple fait que le dépôt est public ou qu’une dépendance utilise MIT/Apache. Aucun choix automatique n’a été effectué ici. |

## Conditions pour une installation depuis un clone neuf

La procédure actuelle de console nécessite Bash, Python 3, Docker avec Compose, l’accès au démon Docker, les droits d’écriture du répertoire de travail et le téléchargement des images et dépendances. Le bootstrap utilise des primitives POSIX, dont `fcntl`, dans [`scripts/bootstrap-console.py`](../scripts/bootstrap-console.py), ligne 5. L’installation documentée ne constitue donc pas une validation native de toutes les plateformes.

Pour exécuter le parcours Android, il faut en plus un hôte disposant de `/dev/kvm`, l’image compatible aujourd’hui absente de la recette du dépôt, ses outils Android et son image système API 29. Le worker doit rejoindre le réseau privé du banc. Une console web démarrée sans ce worker et ce périphérique n’établit pas la réussite d’une automatisation.

Le premier accès doit être créé automatiquement sur base vierge, puis exiger le remplacement du mot de passe et l’activation du TOTP. Une seconde exécution de l’installation doit conserver comptes, secrets, données et historique. La sauvegarde doit porter ensemble sur la base, les preuves nécessaires et la clé de chiffrement existante ; cette clé ne doit pas être recréée lors d’un redémarrage ordinaire.

## Portée des preuves

Les tests et recettes déjà archivés valident des comportements sur des bases jetables et sur le banc local présent à l’époque de leur exécution. Leur existence ne remplace pas un essai de clone vierge, de build sans cache, de téléchargement d’image Android et de restauration de sauvegarde. Ces quatre essais n’ont pas été effectués dans ce contrôle ciblé.

Aucun scan de secrets ne dispense d’une nouvelle vérification du contenu exact de la release. Les fichiers encore non suivis ou modifiés dans l’intégration en cours doivent être relus et testés avant leur ajout à une version ; ils n’ont pas été supprimés ou validés pour publication par cet audit.
