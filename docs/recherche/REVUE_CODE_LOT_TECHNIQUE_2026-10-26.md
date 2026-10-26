# Revue de code et périmètre du premier lot — 26 octobre 2026

## Décision

Préparer un lot de corrections techniques avec le modèle de planification actuel,
`gpt-5-mini`. La variante `gpt-5.6-terra`, sa configuration dédiée, les deux lignes de
prompt sur l'identité des conventions et son test de sélection de modèle sont
conservés séparément. Ils ne sont pas inclus dans le lot technique.

Cette revue ne vaut pas déploiement : aucun commit, push ou changement en production
n'est effectué dans ce travail. La couverture juridique générale reste un chantier
distinct.

## Périmètre examiné

Revue du diff applicatif, des tests et de l'outil de capture hors ligne, par rapport
à `0f01ab8c444c29ad84c5739cbd5eb729dc900ef9`. Les modifications commerciales, produit
et frontend présentes dans le répertoire ne font pas partie de ce lot.

Le lot contient :

- L'aiguillage des demandes concrètes formulées par « es-tu capable de… », tout en
  conservant les contrôles sur les demandes de secrets.
- Les capacités documentaires réellement disponibles dans le schéma fourni au
  planificateur. Ce schéma ne remplace pas les autorisations SQL et Qdrant.
- Le signalement des caractères NUL décodés dans les structures exécutables ou
  stockées, sans modifier la sortie originale ni appliquer partiellement les faits.
- La transmission des fragments déjà reçus avant de propager une erreur du flux.
- La disponibilité d'une tâche de revue lorsque les pièces autorisées sont déjà
  lues. Une dépendance explicitement échouée reste bloquante.
- L'outillage de capture des contrats HTTP avec transports simulés, sans appel
  payant ni jugement automatique du contenu des réponses.

La recherche par période est déjà présente dans le commit `72ad715` du socle :
elle est vérifiée par les tests, sans être présentée comme une nouvelle correction
de ce lot.

## Anomalie trouvée pendant la revue

**P1 — Relecture d'une source historique désactivée en présence d'une pièce.**

Le contexte documentaire remplaçait l'historique structuré par une chaîne contenant
le texte original de l'échange. Le nouveau schéma de capacités ne pouvait alors plus
retrouver les `document_id` des sources précédemment citées et retirait la demande
`read_legal_sources`. Une relance comme « développe cet arrêt » avec une pièce jointe
pouvait donc perdre cette possibilité de lecture.

Correction : transmettre séparément les références structurées de l'historique
autorisé au planificateur et au schéma. Le texte de continuité reste inchangé ;
aucune référence n'est extraite du texte généré et aucun nouveau droit n'est accordé.
Deux tests du parcours orchestrateur couvrent le cas avec et sans continuité
documentaire, la présence du nom et de l'identifiant source, ainsi que la conservation
du texte de la pièce et l'absence de relance.

Les 44 tests ciblés de ce correctif et des contrats voisins passent. Aucun autre
défaut bloquant n'a été identifié dans le périmètre revu ; cette conclusion reste
limitée aux parcours examinés et aux contrôles documentés ci-dessous.

**P2 — Empreinte périmée dans un test existant.**

La suite élargie a d'abord terminé avec 485 réussites, un échec et un test ignoré.
L'échec de `test_no_document_path_is_byte_identical` est reproduit dans un checkout
intact du commit de départ : son empreinte attendue précédait les changements
historiques du prompt partagé. La fonction d'assemblage du prompt, les constantes
et les imports du module sont inchangés entre le socle et le lot (comparaison AST).
La procédure de livraison impose de laisser les échecs préexistants hors périmètre
séparés. Après un essai temporaire de remise à jour de cette empreinte dans le
checkout de contrôle, le test du dépôt est conservé inchangé et exclu du lot.
Aucun prompt applicatif n'est modifié pour rendre le test passant. Cet échec
préexistant reste signalé dans le bilan ; il ne doit pas être présenté comme un
test ignoré ni comme une réussite.

## Vérification du lot exact

La suite élargie et les contrôles statiques sont exécutés après séparation de la
variante de modèle, sur le lot conservant le modèle actuel. Les tests utilisent des
bases isolées et des transports simulés ; deux tests utilisent un PostgreSQL 16
jetable exposé uniquement sur localhost. Aucun service applicatif de production
n'est utilisé.

Résultats :

- Suite élargie sur le lot avec le test d'empreinte original : **485 réussites,
  un échec préexistant, un test ignoré**, en 143,44 secondes. Le test ignoré est
  le parcours payant nécessitant une activation explicite ; les deux tests
  PostgreSQL sont exécutés et réussis.
- Contrôles complémentaires de la démo, de l'isolation et du bac à sable
  administrateur : **18 réussites**. Soit **503 réussites** au total, avec
  l'échec préexistant et le test ignoré signalés séparément.
- Checkout isolé sur lequel le patch de préparation est appliqué : **486
  réussites et un test ignoré**, en 135,63 secondes, avec l'empreinte temporairement
  mise à jour uniquement pour diagnostiquer cet échec. Cette modification de test
  est ensuite retirée du checkout et exclue du patch final. Ce résultat ne doit
  donc pas être présenté comme une suite entièrement verte sur le lot livré.
- `ruff --select F,I` et `git diff --check` passent. La variante de modèle
  archivée reste applicable séparément avec `git apply --check`.

Le checkout isolé vérifie les empreintes des fichiers du patch avant et après
l'exécution. Les journaux initiaux et de contrôle sont conservés séparément.
Les conteneurs PostgreSQL créés par les tests sont supprimés.

## Limites et suite

- Les tests de contrats et d'accès ne constituent pas une certification de la
  qualité juridique de toutes les réponses.
- Le lot ne réduit pas les budgets de contexte ni les sources transmises.
- Les présupposés juridiques dans les requêtes, les consultations redondantes et la
  couverture des versions historiques et des dispositions transitoires restent
  ouverts.
- La variante de modèle garde ses résultats expérimentaux, son surcoût et ses
  contre-exemples dans le rapport de comparaison. Son activation est différée.
- Une livraison ultérieure doit suivre `docs/exploitation/DEPLOIEMENT_PRODUCTION.md`
  et `ACCES_PROD.md`, puis les contrôles après déploiement.

Les changements exécutables de ce lot concernent le service `backend`. La méthode
de flux est aussi utilisée par la démo et le bac à sable administrateur ; leurs
tests de contrats sont inclus dans les contrôles complémentaires. Le lot ne
contient ni migration, ni nouvelle variable d'environnement, ni modification de
Compose. La reconstruction prévue est limitée à `backend` avec `--no-deps`, puis
vérification du commit et du code présents dans le conteneur, de la santé et de
ses dépendances, des logs et de l'absence de redémarrages.

Les artefacts locaux de préparation se trouvent dans `tmp/revue-code-20261026/`.
Ils séparent le lot technique et la variante modèle ; les traces et exports privés
de production ne font pas partie des fichiers à livrer.
