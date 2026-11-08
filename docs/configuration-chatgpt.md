# Configuration et connexion personnelle ChatGPT

## Interface

L’entrée **Configuration**, dans le menu Administration, est accessible après authentification. Elle rassemble la connexion ChatGPT personnelle et les accès aux réglages existants. Les raccourcis d’administration suivent les permissions de l’utilisateur. Le mot de passe et le 2FA restent dans **Mon profil**, conformément à la navigation existante.

ChatGPT est le seul compte externe proposé. La connexion appartient à l’utilisateur Emulytix courant ; elle ne remplace pas le compte des autres utilisateurs et ne configure pas une identité partagée pour les workers. Cette tranche ne transmet aucun parcours, capture ou demande d’inférence à ChatGPT.

Le bouton de connexion demande un code d’appareil. L’utilisateur ouvre la page officielle, s’authentifie chez OpenAI et saisit ce code. Emulytix attend la confirmation effective ; ouvrir le lien ne suffit pas à déclarer une connexion réussie. Le code disparaît après expiration, annulation ou succès. Une déconnexion retire la connexion de cette installation Emulytix ; elle ne déconnecte pas l’utilisateur du site ChatGPT.

## Frontières techniques

Les routes sont personnelles : `GET /console/account/chatgpt`, `POST /console/account/chatgpt/login`, `POST /console/account/chatgpt/cancel` et `DELETE /console/account/chatgpt`. Elles exigent une session complète, avec protection d’origine et CSRF pour les mutations ; le Bearer de service ne suffit pas. Les réponses publiques ne contiennent aucun jeton OAuth.

L’API utilise exclusivement les méthodes de compte du processus officiel **Codex 0.157.1**, via stdio. Le binaire est épinglé dans un verrou npm séparé ; les scripts d’installation sont désactivés. Node sert uniquement au build du binaire. Le flux commence avec `account/login/start` et le type `chatgptDeviceCode`, puis attend `account/login/completed` et relit le compte. Aucune route RPC générale, clé API ou autre fournisseur n’est proposée.

Chaque tentative dispose d’un répertoire temporaire privé et d’un environnement isolé. L’API ne monte ni ne lit le répertoire Codex de l’opérateur. Les identifiants terminés sont chiffrés avec la clé de l’authentification Emulytix avant stockage PostgreSQL. Les tentatives sont bornées en durée et en nombre, idempotentes, liées à leur utilisateur et à leur session ; une réponse tardive après annulation ou déconnexion ne restaure pas l’accès. Les journaux gardent uniquement des métadonnées de sécurité autorisées.

## Déploiement et périmètre

La console locale active `EMULYTIX_CHATGPT_ENABLED=true` sur l’API. Les workers n’ont pas accès à ces identifiants. Appliquer la migration dédiée avant de remplacer l’API et l’interface. La clé `EMULYTIX_AUTH_KEY` reste nécessaire pour relire les connexions chiffrées ; elle ne doit pas être régénérée lors d’un redémarrage ordinaire.

Cette intégration vise l’installation locale. La documentation officielle distingue l’authentification App Server pour les applications locales ou open source et **Sign in with ChatGPT** pour les services commerciaux ou hébergés. Une publication de ce type nécessite donc d’adapter l’intégration au parcours officiel correspondant ; la réussite d’un code local ne valide pas un déploiement SaaS.

Sources : [protocole App Server et authentification](https://learn.chatgpt.com/docs/app-server#auth-endpoints), [activation de la connexion par code dans ChatGPT](https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta), [Sign in with ChatGPT](https://developers.openai.com/siwc).

## Vérification

Les régressions PostgreSQL couvrent l’isolation entre utilisateurs, la révocation de session, les reprises idempotentes, les callbacks tardifs, le chiffrement, l’expiration et le refus des accès de service. Les tests de protocole utilisent un sous-processus local simulé ; l’initialisation du vrai binaire dans un répertoire vierge confirme qu’aucun compte de l’hôte n’est chargé.

La recette du 8 novembre 2026 a demandé un vrai code, vérifié sa conservation après rechargement et son isolation entre utilisateurs, puis annulé la demande. Aucun compte ChatGPT n’a été autorisé et aucune inférence n’a été effectuée. Les états connecté et déconnecté ont aussi été exercés avec des réponses simulées dans le navigateur. La confirmation complète nécessite l’intervention de l’utilisateur sur le site officiel ; le renouvellement des identifiants en usage réel et leur branchement au moteur restent à valider. Détails et preuves : [audit complet](full-audit-2026-11-08.md).
