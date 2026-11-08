# Audit fonctionnel et UX — 8 novembre 2026

Le socle local fonctionne pour le parcours Android déterministe vérifié : lancement depuis la console, Chrome, recherche Wikipédia « football », suivi en direct, onze étapes et captures conservées. Les accès, les planifications et les principales vues ont été testés. La création d’un parcours à partir d’une instruction naturelle libre et l’installation complète sur une machine vierge restent les deux principaux écarts avec le produit demandé.

Les corrections sont déployées sur la console locale. Le périmètre vérifié concerne la console Next.js/React, les API Python et Go, PostgreSQL, l’ordonnanceur et le worker Android existant. La pile historique facultative et les intégrations futures ne sont pas assimilées à des fonctionnalités validées.

## Résultats vérifiés

| Contrôle | Résultat | Portée |
|---|---|---|
| Tests API et moteur | **537 réussis** | PostgreSQL jetable, authentification, TOTP, rôles, publication, baux, annulation, planification, captures, émulateurs, APK et connexion ChatGPT. Neuf avertissements FastAPI/TestClient préexistants. |
| Tests frontend | **96 réussis** | Contrats, formulaires, demandes conservées, captures, affichage en direct, localisation et états. TypeScript et build Next.js réussis. |
| API Go | **Tests avec `-race` et `vet` réussis** | Contrats et logique de dates ; les vraies réponses synthèse/flotte ont aussi été comparées à Python. Les horodatages volatils des heartbeats sont exclus de cette égalité. |
| Navigation réelle | **50 cas, cinq rôles et dix pages** | Admin, Builder, Operator, Viewer, Auditor ; aucune exception JavaScript ni erreur API 5xx observée. |
| Responsive et localisation | **24 vues, 72 configurations de largeur** | Français, allemand et arabe ; huit pages à 320/768/1440 px. Aucun débordement global constaté. |
| Accessibilité automatique | **30 contrôles WCAG sans violation détectée** | Appareils, Parcours, Planifications, Monitoring et Configuration, dans trois langues et deux largeurs. Ce contrôle ne remplace pas un essai avec lecteur d’écran et utilisateurs. |
| Autorisations HTTP | **48 cas réussis** | Routes effectivement servies, trois lectures Go, accès refusés et corps invalides sans mutation métier. |
| Révocation | **15 accès anciens refusés avec 401** | Après retrait des comptes de recette, Python et Go refusent immédiatement leurs sessions. |
| Première connexion | **Trois groupes de vérifications réussis** | Mot de passe temporaire sans accès métier, changement obligatoire, TOTP, dix codes de secours ; ancien mot de passe ensuite refusé. |
| Android réel | **Deux parcours de onze étapes réussis** | Le second utilise les images finales à dépendances verrouillées. Chaque essai a montré sept sources d’images successives pendant l’observation, puis la fin du direct. Le résultat rouvert conserve onze captures. |
| Connexion ChatGPT réelle | **Demande de code, reprise après rechargement et annulation réussies** | Binaire officiel isolé, un code demandé puis annulé. Un autre utilisateur ne peut pas lire cette demande. Aucun compte ChatGPT n’a été autorisé et aucune inférence n’a été effectuée. |
| Erreurs simulées dans le navigateur | **Quatre groupes réussis** | Réponse de planning perdue, 101ᵉ parcours et erreur de pagination, expiration locale d’un code hors ligne, déconnexion ChatGPT. Réponses simulées explicitement ; aucun planning ou brouillon réel créé par ces fixtures. |
| Dépendances | **Aucune vulnérabilité connue signalée après correction** | `npm audit` pour le frontend et le binaire Codex ; `pip-audit` pour l’environnement de tests puis les paquets effectivement installés dans les images API et worker. Les bibliothèques système des images et les dépendances Go n’ont pas reçu de scan spécialisé. |
| Configuration et scripts | **Validés** | Compose console/worker et syntaxe Bash des scripts de démarrage et de comptes. Aucun essai de clone vierge ou de restauration. |

## Défauts corrigés

| Référence | Problème reproduit ou établi | Changement et preuve |
|---|---|---|
| F1 | Une réponse perdue après création d’un planning permettait de modifier son contenu en gardant la même clé, ou de repartir avec une nouvelle demande. | L’intention complète est conservée par utilisateur dans le stockage de session. Les champs restent verrouillés tant que le résultat est inconnu. La recette vérifie fermeture, rechargement et nouvel envoi strictement identique. |
| F2 | Vingt planifications en échec pouvaient occuper chaque sélection de l’ordonnanceur et empêcher la vingt-et-unième valide de démarrer. | Les échecs sont départagés par leur dernière tentative, sans modifier l’échéance ni les clés de rejeu. Régression PostgreSQL en échec avant la correction, réussie ensuite. |
| F3 | Les brouillons de parcours au-delà des cent premiers devenaient introuvables. | Pagination réelle, total, chargement, conservation de la dernière page en cas d’erreur et bouton Réessayer. Une fixture de 101 parcours vérifie également l’édition et le retour à la première page après sauvegarde. |
| F4 | Le backend ChatGPT acceptait des URL que le frontend rejetait. | URL officielle exacte, code et identifiant de connexion validés avant persistance ; régressions du protocole et demande réelle de code réussies. |
| F5 | Les nouvelles routes personnelles ChatGPT contournaient le contrôle d’activation de l’authentification utilisé par les autres routes personnelles. | Reprise de la dépendance d’authentification existante. Les anciens cookies et Bearer de service ne fournissent pas une identité personnelle valide lorsque l’accès est désactivé. |
| F6 | Un APK pouvait rester sur disque après un refus définitif de publication dans le catalogue. | Retrait du seul fichier nouvellement importé, avec vérification du nom généré, du propriétaire, de la taille, de l’empreinte et de l’absence de lien symbolique. Un commit incertain conserve le fichier pour éviter de supprimer un APK éventuellement référencé. |
| F7 | Les builds Python résolvaient leurs versions au moment de l’installation. | Verrou de 42 paquets de production et 1 079 empreintes SHA-256 ; installation `--require-hashes`. Toutes les versions applicatives restent identiques à celles de l’image validée ; API et worker utilisent le même ensemble. |
| F8 | L’image réellement déployée embarquait `pip` 25.0.1, avec des avis de sécurité connus liés à l’installation de paquets. | `pip` 26.3 épinglé dans les deux Dockerfiles, reconstruction et nouvel audit des images finales. Référence : [journal officiel pip](https://pip.pypa.io/en/stable/news/). Aucun endpoint Emulytix d’installation de paquets Python n’est exposé. |

Les fichiers concernés sont `schedules.tsx`, `schedule-draft.ts`, `workflows.tsx`, `automation_store.py`, les modules `chatgpt_*`, `apk_catalog.py`, `emulator_routes.py`, les Dockerfiles et leurs tests. Les textes ajoutés existent dans les dix catalogues de langue.

## Intuitivité : constats et direction

La séparation Appareils / Parcours / Exécutions / Planifications est conservée. Le direct et les captures restent dans la même exécution ; les opérations d’alimentation restent distinctes de l’installation des applications. La page Configuration fournit maintenant un point d’accès aux réglages existants et à la connexion ChatGPT personnelle. Mot de passe et 2FA restent dans Mon profil.

Le principal effort demandé à l’utilisateur demeure la construction technique d’un parcours : les instructions sont stockées comme description, tandis que les actions, sélecteurs et assertions doivent être préparés. Le moteur courant borne aussi la saisie Android à l’ASCII et les URL à Wikipédia. La priorité est donc une génération contrôlée d’actions à partir d’un objectif, avec résultat attendu, test sur un appareil et diagnostic compréhensible. Les détails techniques doivent devenir un volet facultatif une fois ce moteur présent.

Le parcours d’accueil recommandé est : **préparer un appareil → décrire l’objectif → tester → comprendre le résultat → planifier**. Un blocage doit proposer l’action qui le résout : allumer l’émulateur, importer l’APK manquant, confirmer la connexion ou examiner l’étape en échec. Ces recommandations sont une évaluation experte ; aucun test d’utilisabilité avec un utilisateur débutant n’a été mené pendant cet audit.

Les idées et priorités sont détaillées dans la [comparaison de sept projets GitHub](github-comparison-2026-11-08.md). Les capacités déjà présentes ne sont pas comptées comme de nouvelles fonctionnalités à construire.

## Données et nettoyage

Les **23 états d’exécution préexistants**, les empreintes des **cinq versions de workflow** et le profil d’émulateur avec ses applications sont préservés. Les deux nouveaux parcours réussis et leurs preuves restent dans l’historique. L’émulateur géré reste arrêté ; le banc historique reste allumé. Les baux sont libres et aucun planning de test n’a été laissé actif.

Le nettoyage final a retiré huit comptes de recette : six utilisés pendant cet audit et deux conservés avant la pause précédente. Leurs sessions, challenges et connexions ChatGPT sont supprimés. Les fichiers privés contenant les accès et cookies de recette sont retirés. Les accès d’utilisation existants et la clé de chiffrement de l’installation n’ont pas été remplacés.

Preuves locales, ignorées par Git : `storage/full-audit-2026-11-08/` et `storage/backend-audit-2026-11-08/backend-tests.log`. Les rapports et tests de régression sont suivis ; les sessions et captures de recette ne sont pas destinées à la publication.

## Limites et conditions de diffusion

- La génération de parcours en langage naturel, les réglages matériels d’émulateur, l’API publique/MCP et iOS restent à implémenter.
- Le compte ChatGPT est connecté à un profil ; son utilisation par un moteur d’inférence, le renouvellement en usage réel et ses limites ne sont pas validés par cet audit.
- Aucun téléphone physique, APK social fourni par l’utilisateur, lot de plusieurs appareils/plusieurs workers ou test de charge n’a été validé. Un processus worker continue à exécuter un parcours à la fois.
- Le diagnostic de quarantaine et la réconciliation des imports au résultat incertain restent des opérations à concevoir avec leurs preuves ; aucun rejeu automatique d’une action incertaine n’est ajouté.
- L’installation Android depuis une machine vierge exige encore une image reproductible ; la CI et le choix de licence du projet restent ouverts. Voir la [préparation de publication](release-readiness-2026-11-08.md).
- Aucun fichier source n’a été supprimé sur la seule supposition qu’il était inutilisé. Le scan de secrets est ciblé, pas une garantie exhaustive. Aucune publication GitHub n’a été effectuée.
