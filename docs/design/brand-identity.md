# Emulytix : identité visuelle et icônes

Étude du 6 novembre 2026. Objectif : donner à Emulytix un signe coloré reconnaissable dans l’interface, un onglet de navigateur et un raccourci sur l’écran d’accueil d’un téléphone. La marque doit pouvoir accompagner Android et le futur iOS, sans représenter un système particulier.

## Ce que le logo doit exprimer

Emulytix orchestre des appareils et des actions depuis un espace commun. Le signe doit évoquer une maîtrise simple, du mouvement coordonné et une interface accueillante. Un pictogramme de téléphone seul décrirait l’objet piloté, mais ne donnerait pas à la marque une silhouette propre. Une tour de contrôle littérale serait trop détaillée pour un favicon.

L’interface actuelle utilise des surfaces claires, du bleu, une typographie système et des formes arrondies. Son ancien carré bleu à quatre cases fonctionne comme icône de navigation ; il est trop générique pour devenir le logo définitif. Le nouveau signe peut rester proche de cette simplicité tout en ayant une structure distinctive.

## Trois directions examinées

| Direction | Idée visuelle | Atout | Limite à petite taille |
|---|---|---|---|
| **E en mouvement** | Un monogramme compact composé de trois segments ou rubans larges autour d’un vide central | Le nom est suggéré sans texte ; une silhouette compacte fonctionne dans un carré ou un cercle ; les couleurs peuvent distinguer les flux | Des rubans trop entrelacés deviennent illisibles ; limiter les pièces et garder un vide net |
| Constellation coordonnée | Plusieurs appareils ou modules convergent vers un centre | Exprime immédiatement le parc et son orchestration | Des écrans, points et connexions séparés disparaissent à 16 px ; silhouette plus générique |
| Orbite de commande | Une trajectoire dynamique entoure un noyau ou un geste de lancement | Abstraction compatible avec tous les OS, mouvement et continuité | Peut évoquer un lecteur vidéo, une planète ou un produit déjà connu ; nécessite un détail distinctif qui reste lisible |

**Direction retenue : E en mouvement.** Le signe comporte trois rubans épais et arrondis. Les ouvertures et la silhouette conservent le E lorsqu’il est réduit ; le bleu, le turquoise et le corail lui donnent sa personnalité. Les recouvrements suggèrent plusieurs flux coordonnés.

## Contrat graphique de création

- Un signe seul, sans le nom, dans l’icône. Le nom **Emulytix** reste du texte net dans l’interface.
- Deux ou trois masses principales, des arêtes arrondies, des ouvertures suffisamment larges pour survivre à une réduction en 16 px.
- Bleu dominant, turquoise et accent corail possibles. Éviter le découpage en quatre couleurs de Google, son G, les symboles Apple/Android et les silhouettes de concurrents.
- Préférer des aplats ou des transitions très discrètes. Ni volume, reflet ou ombre ne doit être nécessaire à la compréhension.
- Pas de bordure fine, de slogan, de circuit électronique détaillé ou de téléphone miniature dans le signe.
- Une version sombre en une seule couleur doit garder la même silhouette. Cette version sert à vérifier la structure, même si la version colorée est livrée en priorité.

Palette de travail proposée : bleu franc, turquoise et corail chaud, avec du blanc ou un bleu très pâle comme fond d’application. Les valeurs finales sont à relever sur le logo retenu et à noter avec les exports.

## Déclinaisons à livrer

| Usage | Livrable conseillé | Composition |
|---|---|---|
| Marque dans l’interface | Signe propre sur fond transparent, associé au nom en texte | Pas de carré bleu ajouté autour d’un dessin déjà complet |
| Favicon | PNG 16/32/48 px et ICO multitailles ; SVG si une véritable source vectorielle est disponible | Silhouette privilégiée, marges optiques réduites, sans mot ni slogan |
| Raccourci iPhone/iPad | `apple-touch-icon.png`, PNG opaque 180 × 180 | Fond carré complet ; laisser le système appliquer sa forme de masque |
| Icône web standard | PNG 192 × 192 et 512 × 512, `purpose: any` dans le manifeste | Logo plus présent que dans la variante maskable |
| Icône Android maskable | PNG opaque 512 × 512, entrée `purpose: maskable` distincte | Dessin essentiel contenu dans le cercle central de rayon 40 % de la largeur, fond jusqu’aux bords |
| Source réutilisable | Image maîtresse haute définition et, si réalisable, vrai SVG géométrique | Ne pas emballer simplement un bitmap dans un fichier `.svg` en le qualifiant de vectoriel |

Un favicon et une icône maskable n’ont pas les mêmes marges : les déclarer comme deux fichiers distincts évite un petit logo perdu au milieu d’un carré dans les onglets. Le signe de l’interface ne doit pas hériter du fond opaque nécessaire au raccourci mobile.

## Textes de marque

La signature générale devient **« Console de pilotage mobile »**. La description publiée est **« Votre tour de contrôle pour piloter et automatiser votre flotte d’appareils mobiles. »** Elle reste neutre quant au système.

Les textes techniques doivent continuer à dire Android lorsqu’ils parlent du worker ADB, d’un émulateur ou des preuves WF01 actuellement disponibles. Le logo et la signature peuvent préparer iOS ; ils ne constituent pas une annonce de prise en charge déjà livrée. Éviter donc « Pilotez Android et iOS » dans la promesse actuelle tant que les deux intégrations ne sont pas disponibles.

## Contrôles avant validation

- Examiner le logo réellement réduit à 16, 32, 48, 180 et 512 px, pas seulement son grand aperçu.
- Identifier la même silhouette en couleur, en niveaux de gris et sur un fond clair ou sombre.
- Vérifier que les ouvertures ne se bouchent pas et que les petits segments ne deviennent pas des pixels isolés.
- Contrôler le centrage optique et non seulement la boîte géométrique.
- Masquer l’icône mobile sous un cercle et un carré arrondi : aucun élément essentiel ne doit être rogné.
- Contrôler l’opacité complète des images de raccourci et les dimensions des fichiers exportés.
- Vérifier dans le HTML final les références favicon et Apple, puis les entrées `any` et `maskable` du manifeste.
- Charger les assets sans authentification : le navigateur doit pouvoir afficher le logo avant connexion, sans exposer les données privées de la console.
- Vérifier l’apparence dans la page de connexion et la navigation, puis le favicon d’un vrai navigateur.
- Ne pas annoncer un test sur un écran d’accueil iOS ou Android physique si seuls les fichiers et les masques ont été contrôlés sur ordinateur.

L’étude examine la structure et l’adaptation du signe ; elle ne constitue pas une recherche d’antériorité de marque.

## Références techniques

- [web.dev : icônes maskable](https://web.dev/articles/maskable-icon) : fond opaque, zone sûre circulaire de rayon 40 %, distinction des usages `any` et `maskable`.
- [Apple : configuration d’un raccourci web](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html) : déclaration `apple-touch-icon`, PNG et variante 180 × 180. Ce guide est archivé ; il sert ici au mécanisme Web Clip, pas à prétendre satisfaire toutes les règles des applications natives actuelles.
- [Apple : app icons](https://developer.apple.com/design/human-interface-guidelines/app-icons) : référence générale de conception d’icônes d’applications.
- [Google Search Central : favicon](https://developers.google.com/search/docs/appearance/favicon-in-search) : rapport carré et cohérence avec la marque. L’icône d’une console authentifiée n’est pas une promesse d’apparition dans les résultats de recherche.

## Source et livrables retenus

Création réalisée avec l’outil intégré **imagegen**, sans CLI d’inférence ni clé API ajoutée au projet. Le [prompt exact](../../design/brand/prompt.txt) décrit un monogramme E en mouvement, trois rubans bleu/turquoise/corail, une transparence réelle et une lisibilité en favicon. Les ancrages créatifs sont `#2563EB`, `#14B8A6` et `#FF6B4A` ; la source générée conserve des nuances discrètes dans les recouvrements. Le fond des icônes d’application est précisément `#F8FAFD`.

| Fichier | Usage et format réel |
|---|---|
| `design/brand/emulytix-master.png` | Source générée de 1254 × 1254, avec transparence |
| `web-ui/public/brand/emulytix-mark.png` | Signe transparent 256 × 256 dans l’interface |
| `web-ui/public/favicon.ico` | Trois images embarquées : 16, 32 et 48 px |
| `web-ui/public/icons/favicon-{16,32,48}.png` | Déclinaisons transparentes pour les onglets |
| `web-ui/public/apple-touch-icon.png` | PNG opaque 180 × 180 pour les raccourcis Apple |
| `web-ui/public/icons/icon-{192,512}.png` | Icônes opaques standard, `purpose: any` |
| `web-ui/public/icons/maskable-512.png` | Icône opaque adaptative, `purpose: maskable` |
| `web-ui/app/manifest.ts` | Identité stable Emulytix, démarrage à `/`, affichage autonome |
| `scripts/export-brand.mjs` | Exports techniques reproductibles par ImageMagick : cadrage, tailles, marges et formats |

La création artistique reste celle de l’image générée. Les exports ajustent seulement son cadrage, ses dimensions et les fonds requis selon l’usage ; aucun bitmap n’est présenté comme une source vectorielle. Le composant `BrandMark` réutilise la même image dans la connexion et la navigation. Les images sont décoratives lorsque le nom Emulytix est déjà présent et les liens gardent leur libellé accessible.

## Contrôles réalisés

- Dimensions binaires et contenu des trois images ICO contrôlés ; PNG de lancement entièrement opaques, signe de marque transparent.
- Variante adaptative : marque dimensionnée à 312 px dans le canevas de 512 px. Le script vérifie qu’aucun pixel essentiel n’est hors du cercle central de rayon 204,8 px. Cette marge est propre à la silhouette choisie.
- Planche examinée avec les favicons à leurs tailles réelles sur fonds clair/sombre et les icônes de lancement sous masques rond et carré arrondi : `storage/brand-review/brand-board.png`.
- Build Next.js de production et 13 tests frontend réussis. Chargement anonyme des huit PNG, du favicon et du manifeste vérifié ; les API métier et captures privées continuent de refuser un accès sans session.
- Chromium : références HTML, type du manifeste, noms et tailles vérifiés ; aucune erreur de manifeste remontée par DevTools. Vue de connexion contrôlée à 320, 390, 768 et 1440 px.
- WebKit : affichage mobile à 390 × 844, facteur de pixels 3, logo chargé et déclaration Apple Touch Icon vérifiée sans erreur JavaScript. Il s’agit d’une émulation de moteur, pas d’un ajout sur un iPhone physique.

Rapports et captures : `storage/brand-review/`. Le logo et le manifeste sont prêts pour les raccourcis ; l’essai d’ajout réel sur appareil dépendra d’une URL HTTPS accessible. Le déploiement local n’a pas été ouvert au réseau et aucun service worker de cache privé n’a été ajouté.
