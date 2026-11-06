# Revue responsive et adoption de Tailwind

Inspection du 6 novembre 2026 sur la console locale Emulytix.

## Constats avant correction

La première recette a inspecté neuf pages dans sept configurations de largeur/hauteur, soit 63 relevés. Aucun débordement horizontal de page n’a été observé. Les tableaux gardent leur défilement horizontal local, utile pour conserver les colonnes.

Les défauts concernent surtout l’usage tactile : plusieurs boutons mesurent de 30 à 40 px, les champs et filtres utilisent des caractères de 12 à 14 px, le menu horizontal cache certaines rubriques sans action d’ouverture et le lancement imbrique deux conteneurs de défilement. À 390 px, l’en-tête latéral transformé en bandeau occupe 241 px de hauteur.

## Corrections

- Sous 901 px, un bouton de navigation ouvre un dialogue regroupant les rubriques et leurs liens. Les cinq rôles et leurs permissions continuent de filtrer les mêmes entrées. Le dialogue conserve les couleurs par thème, les noms traduits, le lien courant, la navigation clavier et le retour du focus après Échap. Le passage au bureau ferme le dialogue.
- Les boutons d’action, liens de navigation et résumés interactifs disposent d’une hauteur minimale de 44 px sur pointeur tactile. Les champs utilisent au moins 16 px ; le champ OTP garde sa taille spécifique. Ces règles s’appliquent aussi aux formulaires de connexion.
- Au lancement, le titre et le filtre restent dans le formulaire ; seule la liste d’appareils défile. Les planifications, qui n’ont pas cette liste interne, conservent leur propre conteneur.
- Le cadre général est maintenant défini par les utilitaires Tailwind : une colonne jusqu’à 900 px, barre latérale de 214 px ensuite, puis 236 px à partir de 1 201 px. Le contenu principal garde une largeur minimale nulle pour permettre les grilles et tableaux adaptatifs.

## Intégration technique

React 19 et Next.js 15 étaient déjà utilisés. Tailwind CSS 4.3.5 et son plugin PostCSS officiel sont ajoutés avec des versions fixées. Le préfixe `tw:` évite les collisions de classes et les dossiers `app`, `components` et `lib` sont déclarés comme sources.

Le reset Preflight est omis pour conserver l’apparence des contrôles existants. Les utilitaires sont importés après les styles du produit. Cette étape migre le cadre et le menu mobile ; les autres styles existants restent en CSS et pourront être convertis par composant lors de leurs prochaines modifications.

Sources : [installation officielle pour Next.js](https://tailwindcss.com/docs/installation/framework-guides/nextjs), [désactivation de Preflight](https://tailwindcss.com/docs/preflight#disabling-preflight), [détection des classes et préfixe](https://tailwindcss.com/docs/detecting-classes-in-source-files).

Tailwind 4 cible les navigateurs récents : Chrome 111+, Safari 16.4+ et Firefox 128+. Cette compatibilité concerne le navigateur qui consulte la console. Le Chrome 74 du banc Android piloté ne charge pas la console et n’est pas mis à jour par cette modification. [Compatibilité officielle](https://tailwindcss.com/docs/compatibility).

## Vérification

Les preuves locales sont conservées dans `storage/responsive-review/` : relevés initiaux, captures avant/après, recette des pages et formulaires, navigation mobile et contrôles WCAG automatisés. La recette utilise des comptes temporaires, les parcours et captures déjà présents ; elle ne soumet aucune nouvelle exécution Android.

Les essais Chromium utilisent de vraies pages et sessions avec simulation de viewport, de tactile et de pointeur. Un contrôle WebKit vérifie également les graphiques, le menu, le retour du focus et la taille des champs. Ils ne remplacent pas une recette sur un iPhone physique et Safari. La migration de l’API Go et l’analyse de la file PostgreSQL sont séparées dans [la revue de stack](architecture-stack-review.md).
