# Carte interactive du monitoring

La carte doit permettre de repérer un composant à examiner, comprendre ses liaisons et ouvrir ses mesures. Elle utilise le flux de monitoring existant ; les tableaux et résultats restent accessibles sous la carte.

## Lecture de la carte

Huit blocs : interface web, API de contrôle Python, API Go, PostgreSQL et sa file persistée, ordonnanceur, workers Android, appareils Android, captures et preuves. Chaque bloc est un bouton accessible au clavier. Son dialogue affiche les valeurs courantes, leur date, les instances ou hôtes concernés et ses liaisons. Une mise à jour SSE actualise aussi le dialogue ouvert.

Les états distinguent disponibilité confirmée, activité, situation à vérifier et mesure inconnue. Une absence de signal n’est pas une panne démontrée. La lecture du répertoire des captures ne prouve pas sa capacité d’écriture ni l’intégrité de chaque image. CPU et RSS restent des mesures du processus, hors émulateurs et commandes enfants.

Les flèches représentent les liaisons de l’architecture. Leur mouvement désigne soit le flux SSE effectivement reçu, soit un traitement avec bail, worker et Android confirmés, soit un événement observé dans les quinze dernières secondes. Un heartbeat seul ne simule pas des échanges HTTP. Les lectures Go et les vérifications de session restent des liaisons de disponibilité tant que leur trafic n’est pas collecté.

## Contrat d’activité

L’extension optionnelle `topology` du snapshot apporte :

- Six compteurs avec dernier horodatage : commandes console confirmées, lancements planifiés, exécutions démarrées, actions confirmées, étapes publiées et captures publiées.
- Une fenêtre fixe de quinze secondes, indépendante de la période des résultats historiques.
- Un plafond de mille événements et mille exécutions examinées pour les métadonnées de capture, avec indicateurs de troncature.
- Le nombre exact d’exécutions avec bail valide, worker récent du même propriétaire/hôte et preuve ADB sur l’appareil concerné.
- La durée restante de ces preuves et l’âge de la collecte/du cache, calculés avec une horloge monotone pour ne pas prolonger un ancien bail à la réception.
- Une sonde de lecture du répertoire des captures, sans écriture ni chemin exposé au navigateur.

Les timestamps futurs ou invalides sont exclus. Les compteurs de captures portent sur les métadonnées publiées, sans lecture de tous les fichiers. Les événements ne publient ni arguments de commandes, ni identifiants de connexion, ni secrets. Les anciennes réponses sans extension restent compatibles et affichent les mesures indisponibles comme inconnues.

## Comportement et vérification

Les animations s’arrêtent si le flux devient périmé, si l’onglet est masqué, si l’utilisateur les met en pause ou si son système demande moins de mouvement. La pause visuelle ne suspend pas les mesures. Les traits sont recalculés à partir des positions réelles des blocs lors des changements de taille et de langue ; la carte s’adapte au mobile et au RTL.

Vérifications : règles d’activité et de péremption dans les tests Node ; compteurs, bornes et corrélation des baux dans PostgreSQL jetable ; recette Chromium sur données réelles et fixtures navigateur, avec clavier, dialogue actualisé, pause, réduction des mouvements, perte du flux et largeurs 320/768/1440 en français, allemand et arabe.

Repères officiels : [ResizeObserver](https://developer.mozilla.org/en-US/docs/Web/API/ResizeObserver), [préférence de réduction des mouvements](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion), [imports TypeScript dans un projet sans émission](https://www.typescriptlang.org/tsconfig/allowImportingTsExtensions.html). Les mesures et leurs limites générales restent décrites dans [l’étude du monitoring](monitoring-study.md).
