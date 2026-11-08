# Vérification de sécurité avant publication

Date : 8 novembre 2026. Périmètre : console React/Next.js, API Python et Go, worker Android, stockage des preuves, authentification locale, clés personnelles et connexion ChatGPT.

Le modèle retenu est une installation autonome avec une flotte partagée et des rôles locaux. Les permissions de rôle ne constituent pas une isolation entre plusieurs organisations. Les clés personnelles et les identifiants ChatGPT restent, eux, associés à leur propriétaire.

## Corrections effectuées

| Point vérifié | Constat et correction | Vérification |
|---|---|---|
| Ancienne API de démonstration | Les anciennes routes de sessions, agent distant et commandes directes Android/Docker restaient enregistrées, avec un fonctionnement sans authentification lorsque le réglage était absent. Ces routes et leur code ont été retirés. Les commandes Android passent désormais uniquement par les workers et leurs baux. | Avant correction, `POST /sessions` anonyme répondait `200`. Après correction, les anciennes routes répondent `404`, même si un ancien indicateur de configuration tente de les activer. Les routes de la console actuelle restent présentes. |
| Réglage d’authentification | Une variable absente ou mal écrite désactivait l’authentification. L’absence, une valeur vide ou invalide conserve désormais la protection. Seul `EMULYTIX_AUTH_ENABLED=false`, explicitement demandé pour les tests ou le développement isolé, la désactive. | Tests pour variable absente, vide, `typo` et `0` : le schéma API et la console refusent un visiteur anonyme. Les fixtures de tests déclarent leur mode de développement explicitement ; les tests d’authentification utilisent les vraies sessions PostgreSQL. |
| Surface publique et origines | La sonde `/health` ne renvoie que son état, sans inventaire Android, chemins ou environnement. L’API n’annonce plus de CORS avec origine `*` : seule l’origine configurée est admise. | Réponse de santé minimale et tests de routes protégées. La stack prise en charge ne publie que l’interface sur `127.0.0.1:3100` ; API, PostgreSQL, ADB et Go restent internes. |
| Chaîne Go | L’audit initial trouvait 14 avis distincts dans la bibliothèque standard du compilateur installé. Le minimum du module et l’image de construction ont été portés à Go 1.27.3. | Tests Go avec `-race`, `vet` et compilation réussis ; `govulncheck` 1.9.0 ne trouve plus de vulnérabilité. |

Les anciennes configurations qui exposaient directement API, VNC/ADB et socket Docker ont également été retirées du dépôt. Le worker de gestion conserve son accès Docker nécessaire à la création et à l’arrêt des émulateurs ; ce worker et son hôte restent des composants de confiance. L’API de console n’a pas ce montage.

## Contrôles réalisés

- Authentification : mots de passe Argon2, changement initial obligatoire, second facteur TOTP, codes de secours hachés, sessions et challenges expirants. Les opérations personnelles sensibles vérifient à nouveau le mot de passe et le second facteur.
- Autorisation : permissions vérifiées côté serveur, chemins de proxy autorisés explicitement, contrôle des clés à portée limitée et révocation. Les secrets des autres comptes ne sont pas exposés par les vues utilisateur.
- Entrées : modèles stricts et requêtes SQL paramétrées ; imports APK bornés et nommés par le serveur ; contrôle du manifeste avec un processus limité ; captures rattachées à l’exécution, chemins contrôlés et empreinte vérifiée.
- ChatGPT : répertoire de credentials privé, propriétaire vérifié, données chiffrées en base, processus limité et isolé du compte Codex de l’hôte. Les sorties du générateur restent des données validées ; aucune commande libre issue du modèle n’est exécutée.
- Publication : analyse Gitleaks de 62 commits sans secret réel détecté. Une seule exception précise couvre un UUID d’idempotence de test, reconnu à tort comme un jeton ; aucun dossier de données locales ou fichier de connexion n’est ajouté à la version publiée.
- Dépendances : audits npm de l’interface et du runtime Codex sans avis signalé ; `pip-audit` des 42 paquets Python verrouillés sans vulnérabilité connue ; contrôle Go corrigé comme indiqué ci-dessus.

La revue a exécuté **116 tests ciblés**, couvrant les contrôles de publication, l’API des runs, les opérations runtime actuelles, l’authentification et le premier accès. Les cinq régressions nouvelles échouaient avant les corrections puis passent. La suite complète, les constructions et la recette de déploiement font partie de la validation finale de publication.

## Limites de la vérification

Il s’agit d’une revue du code et des configurations, de tests automatisés et de contrôles de dépendances connues. Ce résultat ne constitue pas une preuve d’absence de toute vulnérabilité ni un test d’intrusion indépendant. Les paquets système Debian/Alpine, l’image Android, un déploiement Internet avec son propre reverse proxy et une flotte physique ne sont pas couverts par les audits applicatifs cités. Les données et secrets de l’installation locale ont été préservés.

Verdict : les expositions concrètes identifiées dans cette revue sont corrigées ; aucun blocage de publication n’est constaté dans les contrôles exécutés. Les étapes finales de test, de construction et de publication restent soumises à leurs propres résultats.
