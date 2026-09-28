# Recherche chronologique des sources officielles

Le planificateur peut fournir `search.chronology` dans une demande `legal`.
La recherche sélectionne alors des **documents**, avant de lire leurs passages.
Elle ne classe pas des passages contenant les mots « dernier décret ».

## Contrat

- `date_kind` : publication, décision, entrée en vigueur, mise à jour ou événement
  (veille mêlant plusieurs familles, avec la nature de date indiquée par résultat).
- `date_from`, `date_to`, `period_basis` : bornes explicites ou issues de
  l'historique. Sans période, les bornes restent nulles ; aucun délai de sept ou
  trente jours n'est ajouté. La date courante est fournie au planificateur.
- `source_types`, `jurisdiction`, `chamber` : filtres documentaires.
- `topic` : thème éventuel. Un type de document seul n'est pas un thème.
- `order`, `limit`, `offset` : tri et pagination, dix documents maximum par page.

Les dates de publication/décision/mise à jour sont plafonnées à la date de
consultation. Les dates d'entrée en vigueur peuvent être futures. « Le droit
actuel » reste une recherche juridique ordinaire, pas un classement chronologique.

Une période inversée, un type non supporté ou un paramètre invalide produit une
erreur technique. La proposition brute reste conservée ; aucun appel ne la répare.

## Exécution et couverture

`LegalCatalogueSearch` utilise PostgreSQL pour filtrer et trier. Les sources
supportées sont les lois, ordonnances, décrets, arrêtés, BOSS et les quatre familles
de jurisprudence déjà intégrées. Seuls les documents communs et indexés sont
consultables par cette opération. Les fichiers privés et les CCN restent dans
leurs parcours existants ; ce catalogue ne prétend pas les couvrir.

Sans thème, le tri est effectué sur tout le catalogue correspondant. Une page
compte des documents distincts, indépendamment du nombre de passages par document.
Les égalités de date sont départagées par l'identifiant du document.

Avec thème, les filtres et dates SQL s'appliquent **avant** la recherche de
passages. Celle-ci porte sur au plus 500 documents classés chronologiquement,
puis 80 passages et 40 documents classés par pertinence. Les documents retenus
sont ensuite remis dans l'ordre chronologique demandé. Ces plafonds sont
explicitement tracés : cette sélection thématique n'est pas exhaustive et ne
garantit pas de retrouver toutes les actualités du domaine.

La lecture fournit au plus six passages et 18 000 caractères par document,
sans découper les passages. Elle inclut le début du document et, pour un thème,
le voisinage du passage trouvé. La lecture partielle est signalée. Une source
indexée mais inaccessible dans Qdrant produit une erreur technique, jamais un
document de remplacement.

Le rapport contient les paramètres, le nombre de documents datés, le nombre de
documents de date inconnue, la page suivante, les documents sélectionnés et les
derniers états de collecte. Une collecte réussie n'atteste pas l'exhaustivité du
corpus. Les rapports alimentent la génération et sont conservés dans la trace,
ainsi que dans le contexte des échanges suivants pour la pagination.

## Dates et préparation d'une livraison

Migration `i8j9chronology01` : ajoute `publication_date`, `effective_date`,
`source_updated_date` et `source_url` au catalogue. La date de décision existante
n'est utilisée comme telle que pour la jurisprudence. Ni une date trouvée dans
le corps du texte ni la date d'ingestion ne sert à établir la chronologie.

Le collecteur JORF utilise `dateParution`/`datePublication`, **jamais `dateTexte`**
comme publication. Une entrée en vigueur est enregistrée seulement si une
métadonnée explicite `dateEntreeVigueur` est fournie. Sinon elle reste inconnue ;
le moteur ne prétend pas couvrir les dates d'effet inscrites uniquement dans les
articles ou les textes ayant plusieurs dates d'effet. BOSS utilise sa date de
mise à jour officielle.

Les anciennes dates JORF ne peuvent pas être recopiées automatiquement : elles
peuvent représenter la date du texte. Avant activation en production, prévoir la
migration et l'enrichissement des métadonnées existantes. Depuis `backend` :

```bash
python -m scripts.maintenance.hydrate_jorf_dates --limit 100
python -m scripts.maintenance.hydrate_jorf_dates --limit 100 --apply
```

La première commande affiche les métadonnées obtenues sans écrire. `--apply`
écrit seulement les dates explicites et le lien officiel, dans une transaction
par lot. `--after-id <UUID>` permet de poursuivre après le dernier identifiant
affiché, y compris si certains documents restent sans date connue. Aucun texte,
vecteur, historique de réponse ou date ambiguë n'est réécrit. Pas de réindexation
requise pour ce parcours : les métadonnées du catalogue sont jointes à la lecture.

Ces étapes sont préparées mais ne sont pas exécutées automatiquement. Toute
livraison suit `docs/exploitation/DEPLOIEMENT_PRODUCTION.md`, avec un plan de
migration spécifique. Le backend et le worker partagent les modèles concernés.

## Vérifications

Les tests vérifient les contrats d'opérations, les dates, les filtres, le tri,
la pagination, l'isolation des données et la transmission du contexte. Ils
n'évaluent pas la qualité rédactionnelle des réponses. Aucune génération n'est
nettoyée, réécrite, remplacée ou relancée sur un critère éditorial.

Validation locale du 28 septembre 2026 : **217 tests passent, 1 est ignoré**
(suites catalogue, planification, orchestration, documents, JORF, streaming,
sécurité, parcours chat, parité sandbox et exécution de recherche).
Les contrôles Ruff des nouveaux modules et des imports/erreurs Python des
fichiers modifiés passent ; `git diff --check` est propre. La migration a été
testée à la montée et à la descente sur SQLite, sans toucher la production.

Deux tests d'exécution anciens échouent également après chargement du module
`agent.py` de `HEAD`, avant cette modification :

- `test_successful_floor_survives_failed_main_branches` ;
- `test_timeout_of_main_search_keeps_successful_floor`.

Ils attendent des résultats partiels malgré une branche en erreur, alors que
le moteur existant lève `RetrievalError`. Ils sont laissés inchangés et exclus
du dernier ensemble de vérification. Aucun test éditorial ni appel réel de
qualification des générations n'a été ajouté.

## Plan de livraison du 28 septembre 2026

L'état contrôlé avant livraison comporte 18 740 documents JORF, dont des dates
historiques à 2999. La consultation officielle confirme que `dateParution` est
renseignée alors que `dateTexte` peut contenir cette valeur technique.

1. Sauvegarder les tables `documents` et `alembic_version` sur le serveur,
   dans `backups/`, avec des permissions privées. Conserver les anciens champs.
2. Publier seulement les fichiers de ce changement, puis `git pull --ff-only`.
3. Construire uniquement les images `backend worker`, sans arrêter les anciens
   conteneurs. Appliquer la migration avec un conteneur ponctuel `backend`,
   `run --rm --no-deps`, avant de démarrer le nouveau code. La migration est
   additive et compatible avec les conteneurs encore en fonctionnement.
4. Enrichir les dates par pages de recherche officielles pour les années
   2014 à 2026, en associant uniquement les CID exacts déjà présents. Exemple :
   `python -m scripts.maintenance.hydrate_jorf_dates --publication-year 2026 --apply`.
   Sans `--apply`, la commande prévisualise les correspondances. Chaque page est
   une transaction ; `--max-pages` borne les appels et un dépassement est signalé.
   Par défaut, ce mode couvre les lois, ordonnances et décrets. Les dates sont
   celles de `datePublication`, jamais les dates du titre ou la fenêtre demandée.
   Compléter les documents restants par la consultation individuelle bornée.
5. Déployer `backend worker` par `up -d --build --no-deps backend worker`.
6. Vérifier version Alembic, métadonnées disponibles, sélection chronologique
   et lecture de passages sans génération LLM, santé API, état des deux
   conteneurs, redémarrages et logs récents. Les autres services restent en place.

En cas d'échec, arrêter l'étape concernée et diagnostiquer. Aucun rollback ni
remplacement de données n'est automatique. Une date absente dans la source
reste inconnue et est comptabilisée dans les limites du catalogue.

## Suivi d'une source citée — correctif du 28 septembre 2026

Une liste chronologique pouvait être suivie d'une demande de lecture utilisant
un `document_id` comme `source_request_id`. Ce dernier désigne exclusivement une
opération de découverte de pièce privée ; le contrat rejetait donc la lecture
et ses dépendances (`invalid_request_dependency`). L'arrêt était pourtant indexé.

Le planificateur dispose désormais de `read_legal_sources`, avec une liste explicite
de 1 à 10 `document_ids`. L'historique conserve les identifiants et types des
sources citées, dans le chat et dans la relecture administrative. Sans identifiant
disponible, le prompt demande une recherche juridique par référence exacte.
Les anciens plans invalides restent invalides et consultables : aucune conversion
implicite d'un identifiant ni relance corrective n'est ajoutée.

La lecture contrôle les documents communs indexés des familles du catalogue
chronologique dans PostgreSQL, puis leur identifiant, origine commune et type dans
Qdrant. Les pièces privées et les conventions collectives gardent leurs parcours
existants. Les exclusions explicites restent appliquées. Chaque lecture fournit
tous les passages indexés, ordonnés, sans découper leur texte ; cela n'atteste pas
que l'index contient toutes les annexes de la source originale. Le plafond est de
200 passages par document et 150 000 caractères par opération. Un index incomplet,
une indisponibilité ou un dépassement produit une erreur technique explicite.

Les résultats de lecture alimentent les sources de la réponse, les tâches
dépendantes et les traces. Une lecture en échec bloque ses dépendances. Le prompt
de génération distingue cet échec d'une absence du texte dans la base. Le bandeau
ne prétend plus que des opérations indépendantes ont nécessairement réussi.
Les générations originales restent intactes.

Validation : 181 tests passent sur les contrats, l'orchestration, le catalogue,
les documents, le streaming, la parité administrative et les sources. Le scénario
liste → objet → détail exécute trois plans déterministes et vérifie le transfert
des identifiants et des sept passages jusqu'au contexte de génération. Aucun
jugement automatique de qualité rédactionnelle ni appel LLM d'évaluation.
La lecture seule des dix arrêts du tableau de l'incident en production a également
réussi (98 076 caractères de passages indexés). Livraison backend et worker,
sans migration ni réindexation.
