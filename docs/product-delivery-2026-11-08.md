# Livraison des huit chantiers sélectionnés

Le 8 novembre 2026, l’utilisateur a retenu les huit évolutions prioritaires issues de l’audit. Cette livraison conserve la file PostgreSQL, les baux et les versions immuables. Elle ne remplace aucun compte existant et ne publie pas le dépôt sur GitHub.

## Parcours en langage naturel et premier lancement

Le mode principal de création demande l’objectif, génère un nom et des étapes validées puis affiche leur résumé. Modifier le texte invalide cette génération ; enregistrer le brouillon, publier et lancer restent des actions explicites. Le mode avancé existant reste disponible pour les parcours techniques. L’assistant du tableau de bord accompagne préparation, objectif et vérification du résultat.

Les formulations françaises et anglaises du cas Wikipédia connu sont compilées localement depuis la définition validée, avec un sujet différent possible. Le compilateur reconnaît des intentions complètes : il n’ignore pas une action ajoutée. Les titres comme « La Rochelle » et « Football Club » conservent leur contenu. Une recherche ambiguë ou une redirection vers un autre titre peut échouer à la vérification ; l’utilisateur doit tester le résultat au lieu de recevoir une réussite supposée.

Le cas « ouvrir les paramètres et donner la version Android » est également compilé localement. Deux étapes ouvrent les paramètres puis relèvent la version et le niveau d’API sur l’appareil ; la galerie affiche le résultat observé avec ses captures. [Recette réelle et limites](android-version-goal.md).

Les objectifs libres utilisent le binaire officiel Codex de l’installation avec les identifiants ChatGPT du seul utilisateur connecté. Le processus temporaire est isolé du compte Codex de l’hôte, limité en durée, sortie et concurrence. Les outils shell/fichiers/navigation/MCP/multiagent sont désactivés ; un événement d’outil inattendu arrête la génération. Le modèle produit un brouillon JSON soumis aux modèles et au validateur Android existants. Les identifiants rafraîchis sont conservés chiffrés même si la génération échoue, uniquement si la session et la connexion sont encore les mêmes.

Ce moteur n’est pas un agent universel pour toutes les applications : il autorise la navigation HTTPS Wikipédia, Chrome, l’ouverture d’applications installées et la lecture vérifiée de la version Android dans les paramètres. Il refuse les sélecteurs inventés, les URL arbitraires, l’installation d’un chemin APK produit par le modèle, les publications sociales et les opérations financières. L’intégration réelle avec un compte ChatGPT autorisé et les usages hors parcours de référence restent à valider avec l’utilisateur. Références : [protocole officiel App Server](https://learn.chatgpt.com/docs/app-server) et [connexion locale ChatGPT](configuration-chatgpt.md).

## Installation et dépôt reproductible

`scripts/install.sh --accept-android-license` contrôle les prérequis, crée une configuration privée uniquement si elle manque, construit l’image Android vérifiée et démarre console et worker. Le runtime Android 10/API29 est construit depuis une base identifiée par digest et quatre archives Google avec SHA-256 ; Chrome est inclus dans l’image système. Les deux workflows GitHub vérifient l’application et permettent une construction Android manuelle sans publier d’image Google.

La construction et le démarrage KVM de cette image ont été vérifiés localement dans des ressources éphémères. L’installation complète d’un clone vierge et la CI exécutée sur GitHub restent des recettes séparées. Les paquets APT et les bases applicatives non fixées par digest empêchent de promettre une identité binaire de toutes les images. Le propriétaire a choisi [Apache-2.0](../LICENSE), avec maintien des licences tierces. [Guide d’installation](installation-console.md).

## Matériel et groupes d’appareils

Les profils proposent écran/densité/RAM/CPU/disque initial et des préréglages. Seuls les émulateurs arrêtés et sans file ou bail actif sont modifiables. Le conteneur peut être recréé avec le même volume de données ; un arrêt connecté synchronise Android avant la terminaison. Les paramètres appliqués sont vérifiés et distingués de ceux en attente. Après initialisation, le stockage reste fixe : aucun agrandissement ou rétrécissement non vérifié n’est proposé. [Réglages matériels](emulator-hardware.md).

Les groupes conservent jusqu’à 100 appareils, avec nom unique, édition protégée par révision et sélection paginée. Leur suppression conserve les appareils et l’historique. La capacité vient des heartbeats récents et des baux : un worker actif représente un emplacement, limité par les appareils réellement prêts. Il ne s’agit pas d’une recommandation de charge CPU/RAM pour une grande flotte.

Allumer, préparer et éteindre en groupe ne vise que les émulateurs gérés explicitement affichés. La demande fige identifiant, action et liste ; les résultats sont enregistrés individuellement et repris après une réponse perdue. Un refus définitif reste un refus lors du rejeu. Un appareil physique n’acquiert aucun contrôle Docker par appartenance à un groupe.

## Diagnostic et relance contrôlée

Le diagnostic utilise l’erreur, l’étape en échec, le journal des actions et la dernière capture. La relance crée un nouveau lot lié à la source et conserve version et paramètres. Elle sélectionne uniquement des échecs admissibles, exclut les succès, les exécutions actives, la quarantaine, les intentions inachevées, effets incertains et parcours marqués non idempotents. Elle recommence le parcours sur ces appareils ; elle ne prétend pas reprendre exactement à la dernière étape.

La confirmation fige les appareils. Sa clé est conservée par utilisateur et source dans le navigateur en cas d’incertitude ; PostgreSQL empêche les doubles créations et vérifie à nouveau les droits dans la transaction. Les préfixes réservés et une provenance atomique empêchent qu’un ancien lancement ordinaire soit réutilisé comme relance ou lancement API.

## API et MCP personnels

Le profil permet de créer une clé à durée limitée après mot de passe et TOTP frais, avec secret affiché une fois et empreinte en base. Les permissions sont limitées par la clé et le rôle actif. Révocation, désactivation, modification du rôle et des facteurs retirent les accès. Les mutations revérifient utilisateur, clé et permissions sous verrou.

L’API `/api/v1` expose inventaire, parcours, lancement, suivi, événements et annulation. L’adaptateur MCP stdio appelle cette API ; aucun port MCP anonyme, shell distant ou OAuth supplémentaire n’est ouvert. Les opérations d’administration des comptes et du runtime restent dans leurs interfaces dédiées. [Documentation et configuration](api-mcp.md).

## Recette intégrée

La console est déployée sur `http://localhost:3100`. Le parcours **Wikipédia · football**, créé uniquement depuis son objectif, est publié sous `wikipedia-football-e759dd517620`, version 1. Son exécution **7b4804be-a74a-46e8-85e4-464ea607fd88** a réussi ses onze étapes ; le direct s’est actualisé puis arrêté et les onze captures restent dans l’historique.

| Contrôle | Preuve et résultat |
|---|---|
| Backend, moteur et scripts | **704 tests réussis** dans la dernière suite complète, incluant les 42 tests installation/accès initial/helper. Journal `backend-final-installer.log` ; dix avertissements de dépréciation, aucune erreur. |
| Frontend | **113 tests réussis**, TypeScript et build Next réussis, y compris la sélection d’une page sans perdre les membres des autres pages. |
| Go | Tests `-race` et `go vet` réussis. Les nouveaux services métier réutilisent encore l’API Python pendant la migration progressive. |
| Objectif naturel réel | Saisie, génération sans publication, invalidation après modification, brouillon, publication explicite, choix d’un appareil prêt et onze étapes Android réussies. Une action supplémentaire non prise en charge n’est pas ignorée. |
| Profil et API réels | Clé créée avec mot de passe/TOTP, secret affiché une fois et absent du stockage navigateur, inventaire accessible par Bearer, lancement interdit à la clé de lecture, révocation immédiatement effective. |
| MCP | Vrai transport HTTP local entre l’adaptateur stdio, l’API et PostgreSQL jetable : découverte, inventaire, lancement, rejeu identique, annulation et révocation. |
| Groupes et erreurs réseau | Groupe créé puis supprimé depuis le navigateur. Une réponse groupée perdue simulée conserve la même action, liste et clé après rechargement ; résultat individuel affiché. Aucun ordre groupé n’est envoyé à la flotte réelle par cette fixture. |
| Relance et erreurs réseau | Trois groupes de vérifications simulées : sélection figée malgré un diagnostic actualisé, même demande après réponse perdue, conflit définitif permettant de revenir et modifier. Aucun échec historique n’est rejoué sur un appareil réel. |
| Responsive et accessibilité finale | **27 configurations** en français, allemand et arabe, largeurs 320/768/1440 ; aucun débordement global. **19 contrôles WCAG automatiques** sans violation détectée, dont le formulaire matériel avancé. Aucune exception JavaScript observée. |
| Matériel et conservation | Tests KVM isolés : deux résolutions et configurations RAM, disque initial de 8 Gio et fichier utilisateur conservé après remplacement du conteneur. Autre recette : ancien volume de 6 Gio, demande nominale de 8 Gio, capacité observée inchangée et fichier conservé. Aucun redimensionnement silencieux. |
| Reprise d’installation | Deux démarrages réels du même nouveau banc conservent fichier Android et empreinte AVD ; commande de création protégée sans `--force`. Un ancien banc arrêté dont la commande peut recréer ses données est refusé avant mutation. Le banc historique déjà actif est préservé. |
| Révocation et nettoyage | Deux comptes de recette et leurs trois clés retirés ; douze accès avec les anciennes sessions refusés avec `401`, dont les lectures Go. Les cinq fichiers privés de mots de passe/facteurs/cookies ont été supprimés. |

Les **25 états d’exécution antérieurs**, les empreintes des **cinq versions existantes**, le profil géré et ses applications ainsi que le compte d’utilisation d’origine sont préservés. Un nouveau parcours publié et son exécution réussie restent comme exemple fonctionnel. Aucun planning de test ni groupe temporaire n’est conservé ; les baux sont libres. L’émulateur géré d’origine reste arrêté et le banc historique reste allumé.

Les preuves techniques privées restent dans `storage/product-delivery-2026-11-08/`, exclu de Git ; aucun mot de passe, cookie, code 2FA ou clé personnelle n’est destiné au dépôt. Les recettes Android complémentaires sont dans `storage/hardware-review-2026-11-08/` et `storage/install-build-cache/`. Les contrôles d’accessibilité automatiques ne remplacent pas une étude d’usage ou un essai avec lecteur d’écran. Aucun test de charge multi-appareils, téléphone physique, iOS, APK social ou restauration complète n’est ajouté à ces preuves.

Les fonctionnalités sont enregistrées en commits séparés. Aucune publication GitHub n’a été effectuée. Après explication des options, le propriétaire a explicitement choisi Apache-2.0 ; le texte officiel, les métadonnées npm et la documentation sont alignés. Les licences et conditions tierces sont conservées.
