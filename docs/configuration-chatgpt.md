# Configuration des fournisseurs IA

## Interface

L’entrée **Configuration**, dans le menu Administration, affiche l’état d’OpenAI, d’Ollama et de DeepSeek. Les raccourcis d’administration suivent les permissions de l’utilisateur. Le mot de passe et le 2FA se gèrent dans **Mon profil**.

Les parcours de référence Wikipédia et version Android utilisent des règles et modèles de parcours intégrés. Ils fonctionnent sans compte et sans modèle de langage. Pour un autre objectif pris en charge, choisissez un fournisseur configuré dans l’éditeur de parcours. Relisez le brouillon généré avant de le publier et de le tester sur un appareil.

## OpenAI

La connexion OpenAI appartient à l’utilisateur Emulytix courant. Dans **Configuration → OpenAI**, demandez un code d’appareil, ouvrez la page officielle, connectez-vous avec votre compte ChatGPT et saisissez le code. Attendez la confirmation dans la console. Le code expire et peut être annulé. La déconnexion retire le lien entre votre compte et cette installation.

### Fonctionnement de la connexion

Les routes personnelles sont `GET /console/account/chatgpt`, `POST /console/account/chatgpt/login`, `POST /console/account/chatgpt/cancel` et `DELETE /console/account/chatgpt`. Elles exigent une session complète, avec protection d’origine et CSRF pour les mutations. Les jetons OAuth restent côté serveur.

Pour cette connexion, l’API utilise le processus officiel Codex via stdio. Le binaire est épinglé dans un verrou npm séparé et les scripts d’installation sont désactivés. Le flux commence avec `account/login/start` et le type `chatgptDeviceCode`, puis attend `account/login/completed` et relit le compte.

Chaque tentative dispose d’un répertoire temporaire privé et d’un environnement isolé. L’API ne monte ni ne lit le répertoire Codex de l’opérateur. Les identifiants terminés sont chiffrés avec la clé de l’authentification Emulytix avant stockage PostgreSQL. Les tentatives sont bornées en durée et en nombre, idempotentes, liées à leur utilisateur et à leur session ; une réponse tardive après annulation ou déconnexion ne restaure pas l’accès. Les journaux gardent uniquement des métadonnées de sécurité autorisées.

## Ollama et DeepSeek

L’administrateur configure ces deux fournisseurs dans `.env.console`. Pour Ollama, démarrez le serveur sur l’hôte, installez le modèle avec `ollama pull <modèle>` et activez `OLLAMA_NO_CLOUD=1` pour une inférence locale. Le nom du modèle doit correspondre au tag installé.

```dotenv
EMULYTIX_OLLAMA_URL=http://host.docker.internal:11434
EMULYTIX_OLLAMA_MODEL=your-local-model-tag
```

En déploiement Docker, l’API utilise l’adresse de passerelle de l’hôte. Si Ollama écoute sur `127.0.0.1` uniquement, configurez `OLLAMA_HOST` sur une adresse accessible depuis Docker. Pour une API démarrée directement sur le même hôte, utilisez `http://127.0.0.1:11434`.

Pour DeepSeek, ajoutez une clé API et sélectionnez un modèle proposé par le fournisseur. L’API Emulytics envoie le texte de la demande à DeepSeek en HTTPS.

```dotenv
EMULYTIX_DEEPSEEK_API_KEY=your-deepseek-api-key
EMULYTIX_DEEPSEEK_MODEL=deepseek-flash
```

Après modification de `.env.console`, redémarrez la console avec `./scripts/start-console.sh`. Vérifiez l’état du fournisseur dans **Configuration**. Les deux fournisseurs reçoivent du texte et proposent des étapes que l’API vérifie avant de les afficher dans le brouillon.

Consultez la [documentation Ollama](https://docs.ollama.com/) et la [documentation DeepSeek](https://api-docs.deepseek.com/).

## Déploiement et périmètre

La console locale active `EMULYTIX_CHATGPT_ENABLED=true` sur l’API. Les workers n’ont pas accès à ces identifiants. Appliquer la migration dédiée avant de remplacer l’API et l’interface. La clé `EMULYTIX_AUTH_KEY` reste nécessaire pour relire les connexions chiffrées ; elle ne doit pas être régénérée lors d’un redémarrage ordinaire.

Cette intégration vise l’installation locale. La documentation officielle distingue l’authentification App Server pour les applications locales ou open source et **Sign in with ChatGPT** pour les services commerciaux ou hébergés. Une publication de ce type nécessite donc d’adapter l’intégration au parcours officiel correspondant ; la réussite d’un code local ne valide pas un déploiement SaaS.

Sources : [protocole App Server et authentification](https://learn.chatgpt.com/docs/app-server#auth-endpoints), [activation de la connexion par code dans ChatGPT](https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta), [Sign in with ChatGPT](https://developers.openai.com/siwc).

## Vérification

Les régressions PostgreSQL couvrent l’isolation entre utilisateurs, la révocation de session, les reprises idempotentes, les callbacks tardifs, le chiffrement, l’expiration et le refus des accès de service. Les tests de protocole utilisent un sous-processus local simulé ; l’initialisation du vrai binaire dans un répertoire vierge confirme qu’aucun compte de l’hôte n’est chargé.

La recette du 8 novembre 2026 a demandé un vrai code, vérifié sa conservation après rechargement et son isolation entre utilisateurs, puis annulé la demande. Aucun compte ChatGPT n’a été autorisé et aucune inférence n’a été effectuée. Les états connecté et déconnecté ont aussi été exercés avec des réponses simulées dans le navigateur. La confirmation complète nécessite l’intervention de l’utilisateur sur le site officiel ; le renouvellement des identifiants en usage réel et leur branchement au moteur restent à valider. Détails et preuves : [audit complet](full-audit-2026-11-08.md).
