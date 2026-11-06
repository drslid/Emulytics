# MobileAgent : idées à reprendre pour la nouvelle console Emulytix

Audit du 6 novembre 2026, en lecture seule dans `/home/slid/apps/MobileAgent`. Les services existants n'ont pas été modifiés et aucune commande n'a été envoyée à un téléphone.

La référence Git observée est `dd567ff8147d82e949fb4cb9bd7477f7827def70`, mais l'arbre contient beaucoup de modifications et de fichiers non suivis, dont le serveur v2 et les composants actuels. Cette référence ne suffit donc pas à reproduire les sources auditées. L'étude porte sur les fichiers présents sur disque, pas sur une version publiée vérifiée.

## Deux générations à distinguer

| Ensemble | Architecture et statut observés | Conséquence pour la refonte |
|---|---|---|
| v1 historique | Python/FastAPI, worker, passerelle ADB Wi-Fi, Redis/PostgreSQL et modèle local. `docs/frontend-spec.md`, `docs/security.md`, `docs/status.md` se déclarent historiques. | Source de besoins et de mécanismes utiles, sans appliquer ses anciennes limites mono-téléphone ou son exclusion du 2FA. |
| v2 présente sur disque | Rust/Axum dans `apps/server`, Next.js exporté statiquement dans `apps/web`, PostgreSQL, NATS/JetStream, Codex et application Android compagnon connectée en WSS. Contrats dans `docs/v2-contract.md` et `docs/fleet-api.md`. | Reprendre les principes de flotte et d'exploitation. Ne pas importer cette seconde architecture pour refaire l'interface de l'API Python actuelle. |

Les piles locales aux ports 8080 et 8443 appartiennent à MobileAgent. La nouvelle console de ce dépôt doit garder son propre projet Compose et ses volumes. La licence du dépôt MobileAgent est MIT ; une copie de code devra conserver la notice applicable. L'étude ci-dessous propose surtout une reprise des concepts et des contrats, avec une implémentation adaptée aux contrats d'Emulytix.

## Ce qui mérite d'être repris

| Élément observé | Source principale dans MobileAgent | Reprise proposée et adaptation |
|---|---|---|
| Navigation courte | `apps/web/src/components/application.tsx` | Conserver peu d'entrées stables : Vue d'ensemble, Téléphones, Exécutions, Workflows ; sécurité et compte en navigation secondaire. La console multi-appareils doit commencer par l'état de la flotte. |
| Identité de l'espace et compte | `application.tsx`, `workspace-team.tsx` | Compte identifiable et déconnexion toujours accessibles. Ne présenter les espaces clients que si leur isolation existe réellement ; ce dépôt n'a pas encore cette architecture. |
| Connexion et disponibilité distinctes | `apps/web/src/lib/fleet.ts`, `apps/server/src/fleet.rs` | Un appareil déclaré n'est pas nécessairement connecté ; un appareil connecté n'est pas nécessairement disponible. Afficher séparément connexion, occupation par une tâche et problème bloquant. |
| Diagnostic concret | `device-readiness.tsx`, `apps/server/src/readiness.rs` | Expliquer l'action attendue : reconnecter, déverrouiller ou activer une autorisation. Dans Emulytix, utiliser les mesures réellement disponibles ; ne pas inventer batterie, réseau, modèle ou activité en direct. |
| Fraîcheur des observations | `fleet.rs`, `screen.rs`, `phone-control-session.ts` | Horodater l'état et les captures. Un écran ancien reste une capture, pas un direct. MobileAgent considère notamment la télémétrie trop ancienne comme inconnue. Les seuils doivent être ceux du transport retenu, sans copier aveuglément ses 65 secondes. |
| Recherche et filtres | `phones.tsx`, `fleet-groups.tsx` | Recherche par nom/identifiant, filtre de disponibilité et sélection explicite. Pour plusieurs dizaines de téléphones, une liste/table compacte est préférable à une grande grille de cartes. |
| Groupes de téléphones | `fleet-groups.tsx`, `run-composer.tsx` | À terme, organiser par site ou usage. Un groupe doit produire une sélection explicite et figée au lancement ; son nom seul ne doit pas déterminer une cible mouvante. |
| Lancement guidé | `run-composer.tsx` | Retenir le chemin tâche → téléphones → vérification du lot → lancement. Les options avancées apparaissent à la demande. Dans Emulytix, choisir un workflow versionné et déterministe, sans imposer un modèle IA au parcours nominal. |
| Critère de réussite explicite | `run-composer.tsx`, `run-result.tsx` | Montrer le résultat attendu avant lancement et sa vérification dans le détail. Distinguer les assertions déterministes déjà disponibles de la vérification par le même modèle utilisée dans MobileAgent. |
| Séparation observation / intervention | `phone-control.tsx`, `phone-control-session.ts`, `fleet.rs` | « Voir l'écran » doit rester distinct de « Prendre la main ». Le contrôle manuel exige une autorité serveur commune avec le worker. Masquer un bouton ne garantit pas l'exclusivité. |
| Commandes confirmées | `phone-control-session.ts` | Un timeout navigateur ne prouve pas l'annulation d'une commande Android. Attendre la confirmation, conserver l'incertitude, ne pas renvoyer automatiquement une action. Ce principe rejoint les baux et le journal déjà présents dans Emulytix. |
| Captures dans les listes | `run-previews.tsx` | Miniatures horodatées facultatives, sans appeler le détail de chaque run pour remplir la liste. Le détail regroupe les preuves d'une exécution. |
| États des preuves | `run-previews.tsx` | Chargement, indisponibilité, nouvelle tentative et expiration ont chacun un texte clair. Pas d'image cassée silencieuse, pas de capture factice. |
| Reprise lisible | `run-recovery.tsx` | Expliquer obstacle, action proposée, nombre d'essais et date. Ne pas exposer les instructions internes du modèle. Pour Emulytix, ne proposer une reprise que lorsque le backend la prend réellement en charge. |
| Résultat et journal séparés | `runs.tsx`, `run-result.tsx` | Donner d'abord le résultat utile, puis les étapes et le journal à la demande. Les UUID, epochs et réponses JSON appartiennent aux détails techniques. |
| Annulation honnête | `runs.tsx`, `fleet-settings.tsx` | Dire « Annulation demandée » jusqu'à confirmation ; une action déjà transmise peut se terminer. Conserver les succès partiels du lot et l'état de chaque appareil. |
| Erreurs et états vides | `shared.tsx`, `lib/api.ts` | Message compréhensible, action « Réessayer » si applicable, états vides utiles et focus visible. Un échec d'API ne doit pas apparaître comme zéro téléphone. |
| Installation et appairage distincts | `companion-download.tsx`, `pair-phone.tsx` | Bonne distinction entre installer l'application et associer un appareil ; expiration visible des QR. Ce parcours ne doit pas être proposé dans Emulytix tant qu'il n'existe pas de compagnon compatible avec son backend. |
| Adresse réellement accessible au téléphone | `companion-download.tsx` | Éviter un QR pointant vers localhost : l'adresse doit être accessible depuis Android. Garder le téléchargement de l'APK indépendant des secrets d'appairage. |
| Téléchargements protégés | `lib/helpers.ts`, API artefacts | Ne construire que des routes d'artefacts connues et authentifiées ; jamais utiliser un chemin serveur arbitraire fourni par une preuve. |
| Actualisation bornée | `application.tsx`, `lib/data.ts` | MobileAgent combine SSE et polling de secours. Tant qu'Emulytix n'a pas de SSE, afficher honnêtement une actualisation périodique ; éviter une requête par appareil pour chaque tuile. |
| Équipes et rôles | `workspace-team.tsx`, `apps/server/src/auth.rs`, `tenancy.rs` | Le besoin multi-téléphones n'impose pas immédiatement le multi-tenant. Garder le premier périmètre explicite ; les rôles et espaces pourront suivre avec contrôles serveur et isolation des captures. |
| Déploiement progressif d'APK | `fleet-settings.tsx`, `apps/server/src/releases.rs` | Bonne idée future : lot pilote, signature, version et confirmation réelle d'installation. Hors du cœur de la refonte actuelle et non équivalent à l'installation d'une application métier comme Chrome. |

## Authentification : base utile, 2FA à créer

La v2 contient de vrais comptes avec Argon2, un jeton aléatoire de session stocké sous forme d'empreinte SHA-256 dans PostgreSQL, cookie HttpOnly / SameSite Strict, protection CSRF pour les mutations et contrôle d'origine. Le cookie reçoit Secure sauf lorsque le mode HTTP non sécurisé est explicitement configuré. Les permissions serveur distinguent propriétaire, opérateur et lecture seule. Sources : `apps/server/src/auth.rs`, `apps/server/src/fleet.rs`, `apps/web/src/lib/api.ts`.

Points à adapter :

- Aucun flux TOTP, secret de second facteur ou code de secours n'a été trouvé dans les sources d'authentification parcourues. Copier le formulaire de connexion n'ajouterait pas le 2FA.
- La v2 ouvre une session immédiatement après mot de passe et lui donne 30 jours. La console demandée doit exiger le second facteur avant de donner accès aux téléphones, aux preuves et à toute mutation. Une étape d'enrôlement ne doit donner qu'un droit limité à terminer cet enrôlement.
- La limitation de la v2 utilise un vecteur d'horodatages en mémoire du processus, partagé globalement ; elle ne fournit pas une protection distribuée par compte. La v1 dispose d'une limitation par IP et identifiant adossée à Redis, qui constitue une meilleure idée de contrat. Le nouveau backend peut obtenir le même caractère partagé avec PostgreSQL, déjà présent.
- La fonction v2 de contrôle d'origine rejette une origine présente mais non autorisée ; elle accepte une origine absente. Pour les mutations de la nouvelle interface, fixer et tester le contrat BFF / cookie / CSRF de bout en bout, y compris les requêtes sans origine.
- Prévoir des secrets TOTP chiffrés au repos, l'absence de replay d'un code déjà consommé, des codes de secours à usage unique, l'expiration des challenges et la révocation des sessions. Une simple saisie de six chiffres côté client ne suffit pas.
- Les erreurs ne doivent pas révéler l'existence d'un identifiant. Pas de compte de démonstration, mot de passe connu ou secret 2FA intégré au code.

La création publique du premier administrateur de MobileAgent ne doit pas être exposée telle quelle sur un service ouvert. Pour ce dépôt, un bootstrap local contrôlé ou un secret d'installation à usage unique évite qu'un visiteur revendique le premier compte.

## Ce que la nouvelle interface doit améliorer

1. **Une vraie vue de contrôle.** La v2 arrive directement sur les Runs. La nouvelle page d'accueil doit répondre à « combien d'appareils puis-je utiliser, que se passe-t-il, où faut-il intervenir ? » Les alertes de flotte ne doivent pas rester cachées dans Réglages.
2. **Un centre de gravité par écran.** Le compositeur permanent à côté de l'historique multiplie les options visibles. Une action principale « Nouvelle exécution » peut ouvrir un parcours bref, puis ramener vers son suivi.
3. **Une densité adaptée à la flotte.** Préférer lignes alignées, filtres, sélection multiple et action de lot persistante. Ouvrir un volet appareil au lieu de répéter tout son diagnostic et ses contrôles dans chaque carte.
4. **Un vocabulaire opérateur.** Utiliser « Téléphones », « Exécutions », « Workflows », « Résultat », « À vérifier ». Garder les diagnostics ADB, tokens, epochs, noms de conteneurs et choix de modèle dans un niveau technique facultatif.
5. **Une inspiration Google cohérente.** Fond clair neutre, surfaces blanches, texte sombre, accent bleu, séparateurs légers, espace régulier, recherche facile à trouver, navigation stable et états sélectionnés lisibles. Ne pas reproduire la palette violette ou tous les blocs de MobileAgent simplement parce qu'ils existent.
6. **Aucune simulation implicite.** Des données absentes restent « Non mesuré » ou « Aucun appareil déclaré ». Le succès historique de WF01 reste une archive horodatée, même quand il apparaît dans la nouvelle console.

## Contrat conseillé pour la première livraison

- Connexion identifiant / mot de passe, puis second facteur TOTP obligatoire ; enrôlement guidé au premier accès et codes de secours montrés une seule fois.
- Console accessible uniquement après session complète ; téléchargements et API protégés de la même manière.
- Vue d'ensemble calculée à partir des appareils et exécutions réellement persistés. Distinguer les baux actifs des mesures de connectivité qui ne sont pas encore disponibles.
- Liste des appareils avec recherche, sélection et détail ; création d'un lot avec workflow versionné, liste figée et concurrence explicitement bornée.
- Liste et détail des exécutions : états réels, annulation demandée / confirmée, étapes, erreurs et preuves protégées.
- Vue de résultats WF01 conservée mais intégrée à la navigation et identifiée comme historique.
- Configuration et compte : état du 2FA, déconnexion et documentation d'accès ; pas de paramètres factices.

Cette livraison ne peut pas revendiquer un direct Android, des groupes persistés, la télémétrie batterie ou une capacité physique de 100 téléphones tant que leurs contrats et essais ne sont pas réalisés.

## Limites de cet audit

Inspection des documents, de l'architecture, des contrats TypeScript, des composants de connexion / flotte / lancement / résultats / contrôle / paramètres, des mécanismes serveur d'authentification / flotte / écran et des tests présents. Aucun test matériel, aucune migration, aucune reprise de session utilisateur ni audit de chaque ligne du compagnon Kotlin n'a été effectué. Les chiffres historiques de validation de MobileAgent ne sont pas des résultats reproduits par cet audit et ne doivent pas servir de preuve de la nouvelle console.
