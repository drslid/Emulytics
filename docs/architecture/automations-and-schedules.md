# Parcours et planifications

Les trois opérations sont distinctes : déclarer un appareil, rédiger et publier un parcours, puis lancer une version publiée immédiatement ou depuis un planning. Déclarer un appareil ne le connecte pas à Android. Une instruction libre décrit l'intention ; seules les étapes structurées validées constituent le programme exécuté. Aucun provider ne transforme actuellement cette prose en actions.

## Rédaction et publication

`/console/recipes` conserve un nom humain, des instructions et une définition d'étapes. L'identifiant technique est généré automatiquement, y compris pour les noms contenant des espaces ou des caractères non latins. Les changements exigent la révision lue : une modification concurrente reçoit `409` et ne remplace pas silencieusement le travail précédent.

`POST /console/recipes/{id}/publish` vérifie les actions, arguments, sélecteurs et assertions avec le driver Android avant d'insérer une version immuable dans le catalogue existant. Le nom et les instructions sont également figés pour cette version, et restent lisibles par les opérateurs. Publier deux fois la même révision renvoie la même version. Modifier un brouillon ne modifie aucun run ou planning déjà créé. Les rôles sans droit d'édition ne peuvent pas lire les définitions non publiées.

Le profil d'exécution courant ouvre Chrome et les pages HTTPS de Wikipédia, avec saisie ASCII et assertions explicites. Les actions de récupération qui exigeraient un provider sont refusées à la publication. Ces limites sont celles du moteur existant ; l'éditeur ne les présente pas comme des capacités générales Android ou iOS.

## Suppression d’une version publiée

Admin et Builder disposent de « Supprimer » dans **Parcours → Versions publiées**. La confirmation identifie le parcours et son numéro. `DELETE /workflows/{workflow_id}/versions/{version}` retire cette version du catalogue exécutable, sans effacer sa définition, son empreinte, ses publications ou les preuves historiques. Le stockage conserve une date `deleted_at` ; les consultations historiques restent autorisées. Les compteurs Python et Go ne comptent plus les versions supprimées.

Le serveur refuse la suppression tant qu’une planification référence la version, même en pause (`409 workflow_version_has_schedules`), ou qu’un lot ou une exécution est en attente ou actif (`409 workflow_version_in_use`). Les versions internes de gestion des émulateurs restent protégées. Le verrou exclusif de suppression et les verrous partagés des nouvelles soumissions/plannings empêchent qu’un lancement passe entre vérification et retrait. Les tests observent de vrais blocages PostgreSQL, conformément aux [verrous de lignes](https://www.postgresql.org/docs/17/explicit-locking.html#LOCKING-ROWS).

Une suppression confirmée peut être répétée sans effet supplémentaire ni nouvel événement métier (`204`), ce qui permet de récupérer une réponse perdue. Une version inconnue renvoie `404`. Les nouvelles soumissions, planifications, inscriptions de la même version et nouvelles relances d’une version retirée renvoient `410 workflow_version_deleted`. Une demande déjà acceptée conserve son résultat idempotent, même après suppression. Le journal garde l’acteur et le numéro de version.

Le brouillon reste modifiable. Supprimer sa dernière publication le remet à l’état brouillon ; publier à nouveau alloue un nouveau numéro, sans réutiliser ceux supprimés. Le redémarrage de la console respecte également le retrait du modèle Wikipédia fourni et ne le recrée pas.

Les fenêtres de lancement et de planification déjà ouvertes libèrent leur demande après un refus définitif `410` et permettent de choisir une autre version. Le diagnostic bloque la relance d’une version retirée et indique la raison. Les clés personnelles et le MCP suivent les mêmes contrôles de disponibilité ; aucun outil de suppression distant n’est ajouté.

## CRON persistant

`POST /console/schedules` accepte un `request_id` UUID optionnel : une tentative identique du même utilisateur retrouve la planification, y compris après réponse perdue ; un contenu différent reçoit `409`. La fenêtre de création conserve ce `request_id` pendant ses tentatives.

`/console/schedules` conserve le nom, une version publiée, les identifiants des appareils, la concurrence, une expression CRON à cinq champs et un fuseau IANA. `/console/schedules/preview` renvoie les cinq prochaines occurrences UTC. L'interface peut proposer jour/semaine/mois puis construire la même expression que le mode avancé.

Les horaires suivent l'heure locale du fuseau choisi. Au changement d'heure, un horaire inexistant est ignoré ; un horaire répété n'est exécuté qu'au premier passage. Une reprise après pause part de la prochaine occurrence future. Après une interruption du service, une occurrence en retard est soumise, puis le curseur passe à l'avenir ; il n'y a pas de rattrapage en rafale des occurrences manquées.

Le service `python -m app.scheduler` examine les échéances toutes les cinq secondes. Un verrou PostgreSQL `FOR UPDATE SKIP LOCKED` arbitre plusieurs instances. Chaque échéance possède une clé d'idempotence stable `schedule:<id>:<instant UTC>`. Le run est validé dans sa propre transaction avant d'avancer le curseur. Si le processus s'arrête entre les deux commits, le prochain passage retrouve le même run.

Le propriétaire doit rester actif, avoir terminé le changement de mot de passe et le TOTP, et conserver `runs.execute`. Le dispatcher recontrôle ces conditions sous verrou avant chaque soumission. Un propriétaire désactivé ou privé de ce droit suspend le planning avec `owner_not_authorized`. Les appels de service Bearer sans utilisateur ne créent pas de planning anonyme. Les journaux ne contiennent ni arguments des étapes, ni instructions libres, ni secrets.

La création du run signifie sa mise en file. Un worker et un appareil réellement disponibles restent nécessaires à son exécution. Un heartbeat indique la vie du processus de planification ; les erreurs et prochaines échéances restent consultables dans les plannings.

## Vérification

Les tests de cette tranche utilisent des schémas PostgreSQL jetables et ne commandent aucun appareil. Ils couvrent publication et révision, droits d'auteur et d'opérateur, calcul des fuseaux et changements d'heure, concurrence de dispatchers, interruption entre commits, suspension liée au propriétaire et pause/reprise.

La syntaxe de base et l'itération bornée proviennent de [croniter](https://github.com/pallets-eco/croniter). Le calcul local et la vérification aller-retour par `zoneinfo` fixent explicitement la politique de changement d'heure décrite ci-dessus.
