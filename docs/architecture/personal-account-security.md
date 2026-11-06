# Sécurité personnelle du compte

Les routes internes console/account utilisent exclusivement la session complète de l'utilisateur. Aucun identifiant utilisateur n'est accepté dans le corps et un Bearer de service ne donne pas accès à ces actions. L'origine et la protection CSRF restent vérifiées. Le mot de passe actuel et un facteur sont exigés avant une modification sensible.

Le changement de mot de passe préserve l'authentificateur et les codes encore valides. Le dernier code de secours ne peut servir à un simple changement de mot de passe. Le renouvellement des codes exige un TOTP ; une personne ayant perdu son application doit d'abord la remplacer avec un code de secours disponible. Chaque code consommé reste à usage unique, y compris après annulation d'une configuration.

La configuration TOTP temporaire est chiffrée et liée par clé étrangère à la session initiatrice, avec expiration de cinq minutes. Elle ne remplace le secret courant qu'après confirmation d'un code de la nouvelle application. Une modification confirmée révoque les anciennes sessions et challenges, supprime les configurations temporaires et émet un nouveau cookie courant. Les codes sont conservés uniquement sous empreinte et affichés une fois en clair ; ni les requêtes ni les secrets ne sont journalisés.

Les opérations verrouillent l'utilisateur avant de revalider sa session. Le verrou FOR NO KEY UPDATE conserve la sérialisation des changements tout en permettant les vérifications de clé étrangère du journal pendant une déconnexion concurrente. Les limites par compte et IP sont validées dans une transaction distincte avant la vérification des identifiants : une mauvaise confirmation n'annule pas le compteur.

Une réponse réseau perdue après commit peut rendre l'ancien cookie inutilisable. L'interface indique de se reconnecter avec les nouveaux identifiants au lieu de répéter aveuglément l'opération. Le démarrage d'une configuration conserve son cookie et permet de reprendre le QR existant par lecture tant qu'il n'est pas expiré. Les mots de passe et les codes ne sont pas conservés dans le stockage du navigateur.

Ces choix suivent les recommandations de réauthentification et de protection des changements de facteur de [OWASP MFA](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html), les recommandations d'[authentification OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) et l'exigence d'anti-rejeu des OTP décrite par [PyOTP](https://pyauth.github.io/pyotp/).
