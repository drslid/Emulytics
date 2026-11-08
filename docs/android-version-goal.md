# Lire la version Android depuis un objectif

La phrase « ouvre les parametres du telephone et donne moi la version d'android » est désormais reconnue localement, avec ses variantes accentuées et des formulations anglaises. Elle prépare deux étapes : ouvrir les paramètres principaux, puis lire la version Android. La génération ne lance aucune commande et ne prédit pas la version ; enregistrement, publication et lancement restent explicites.

Le refus initial venait des capacités déclarées au générateur, limitées à Chrome, Wikipédia et l’ouverture d’applications. Les actions `open_settings` et `read_device_info` sont maintenant acceptées dans le contrat, le validateur, le générateur et l’éditeur. Leurs arguments restent bornés : pages `main`/`about` et seul champ `android_version`. Aucune commande, propriété système ou intention Android arbitraire n’est acceptée.

Le worker lit `ro.build.version.release` et `ro.build.version.sdk` sur l’appareil sélectionné, avec les mêmes contrôles de bail, annulation et délai que les autres commandes. Le résultat est conservé dans les preuves de l’étape après assertion, capture PNG et relevé XML réussis. La galerie affiche la version observée même lorsque la première capture est sélectionnée. Un résultat ignoré, non confirmé ou invalide n’est pas présenté comme une réussite.

## Recette réelle du 8 novembre 2026

La saisie de la phrase exacte dans le navigateur a permis de créer, publier et exécuter le parcours sur `local-emulator`. L’exécution `e39b74fb-4a26-4e0c-87f3-d4a4b7c8f344` a réussi ses deux étapes et remonté **Android 10 / API 29**, valeurs également vérifiées par une lecture ADB indépendante. Le parcours publié est `version-android-61ee87d3cf44`, version 1. Deux captures privées et deux relevés XML sont conservés. La valeur affichée vient des propriétés Android, pas d’une reconnaissance de caractères dans la capture.

Le premier essai a ouvert la page « À propos » mais échoué pendant le relevé XML : sur le banc actuel, cette page émet continuellement des événements et `uiautomator` n’atteint pas l’état inactif attendu. Les paramètres principaux permettent un relevé complet. Cette page est donc utilisée pour l’objectif de référence ; « À propos » reste une option explicite de l’éditeur avancé, soumise aux mêmes exigences de preuve. L’échec initial `8c19e80d-8489-4c89-90da-0c913a50ce7a` reste dans l’historique, sans résultat inventé.

Le pilote exige aussi la confirmation du nouveau dump avant de lire son XML : Android peut terminer la commande avec un code zéro malgré une erreur d’inactivité. Un ancien fichier ne doit jamais devenir la preuve d’une nouvelle étape.

La recette navigateur vérifie le résultat et les captures à 1440 et 320 px, sans erreur JavaScript, débordement horizontal du document ou violation WCAG A/AA détectée. Les tests ciblés couvrent notamment les actions supplémentaires refusées, les cinq rôles, les sorties du modèle, les propriétés invalides, la persistance PostgreSQL et le refus d’un ancien XML. La suite backend complète passe 754 tests, dont les 95 cas du pilote et de ce nouvel objectif ; les tests frontend passent 117 cas, avec TypeScript et build validés. La dernière interface déployée est vérifiée dans cinq vues en français, anglais et arabe, de 320 à 1440 px. Le compte QA, ses sessions et les fichiers privés de connexion sont retirés ; les comptes et facteurs existants restent inchangés.

Preuves locales ignorées par Git : `storage/android-version-fix-2026-11-08/`.

## Portée

Cet ajout n’implémente pas la modification des réglages, la réinitialisation d’un téléphone ou la lecture arbitraire de ses informations personnelles. Les autres objectifs libres passent toujours par la connexion ChatGPT personnelle et les capacités vérifiées du moteur.

Sources Android : [ouverture des paramètres](https://developer.android.com/reference/android/provider/Settings#ACTION_SETTINGS), [valeur opaque de RELEASE](https://developer.android.com/reference/android/os/Build.VERSION#RELEASE), [comportement du dump et attente d’inactivité](https://android.googlesource.com/platform/prebuilts/fullsdk/sources/android-30/+/refs/heads/main/com/android/commands/uiautomator/DumpCommand.java).
