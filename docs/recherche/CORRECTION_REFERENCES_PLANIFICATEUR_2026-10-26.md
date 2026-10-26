# Références documentaires du planificateur — 26 octobre 2026

## Correction retenue

Le schéma envoyé au planificateur est désormais construit avec les références documentaires
réellement fournies pour le tour courant. La correction porte sur les paramètres des actions,
sans changement de prompt, de modèle, de budget de contexte ou de traitement des réponses.

Le problème observé était un décalage de contrat : le prompt exigeait des UUID déjà fournis,
mais le schéma acceptait n'importe quel UUID. Le modèle pouvait donc proposer un identifiant
inventé, ou utiliser l'identifiant d'un arrêt officiel pour une consultation de pièce privée.
Les contrôles d'exécution bloquaient ensuite ces opérations ; cela pouvait aussi bloquer
les tâches qui en dépendaient.

Dans `conversation_requests.py`, le schéma distingue maintenant :

- les pièces actives, issues de `active_documents` et `documents_read` ;
- les références de sources déjà fournies dans les champs structurés `history.sources`
  et `tool_results.sources`.

Sans pièce active, `document_checks` doit être vide et la recherche de passages dans ces
pièces n'est pas proposée. Sans référence de source fournie, la relecture directe d'une
source par UUID n'est pas proposée ; la recherche juridique reste disponible pour retrouver
un texte par sa référence. Avec des identifiants disponibles, les paramètres correspondants
utilisent un `enum` qui contient ces identifiants. La découverte de fichiers déposés, la
recherche juridique et les livrables à rédiger restent disponibles.

Les UUID présents seulement dans le texte libre ne deviennent pas des références applicatives.
Le schéma est reconstruit pour chaque appel, sans liste partagée entre conversations. Les
contrôles SQL, les filtres de l'index et les autorisations des pièces restent indépendants :
une référence proposée par le schéma ne constitue pas une autorisation d'accès.

Ces contraintes sont placées dans l'entrée de génération. Aucun validateur sémantique,
nettoyage de réponse, remplacement d'action, suppression de consultation en double ou
relance visant une meilleure sortie n'est ajouté. Une sortie inexécutable reste brute et
produit les erreurs techniques prévues par le parcours existant.

La documentation officielle confirme la prise en charge des `enum`, `anyOf` et contraintes
de taille des tableaux par les sorties structurées. Elle impose également des limites à
la taille des schémas et des énumérations ; les jeux de références testés restent dans ces
limites. [OpenAI — Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas).

## Comparaison avec le modèle réel

Le protocole est fixé avant les appels : **16 cas × 2 versions × 2 répétitions = 64 appels**.
Il reprend les 13 entrées de l'expérience précédente, puis ajoute trois cas : développer un
arrêt déjà cité, rechercher une clause dans une pièce active et rédiger un mail sans pièce.

La référence du schéma est `72ad715`. Les deux versions reçoivent les mêmes messages système
et utilisateur, le même modèle et les mêmes paramètres. Seul `response_format`, qui porte
le schéma, diffère. Cette identité est vérifiée sur les requêtes figées. Les résultats
historiques sont des reconstructions documentées, pas les appels HTTP exacts de production.

| Contrôle technique séparé du rendu | Avant, 32 appels | Après, 32 appels |
|---|---:|---:|
| Réponses API obtenues | 32 | 32 |
| Plans utilisant des identifiants hors du contexte de l'opération | 7 | 0 |
| Occurrences de ces identifiants | 12 | 0 |
| Plans avec erreur lors du décodage des contrats applicatifs | 7 | 0 |
| Sorties contenant un échappement NUL | 0 | 1 |

Les douze occurrences avant correction comprennent dix références de pièces non fournies
et deux utilisations d'une véritable source officielle dans le champ réservé aux pièces
actives. Ce ne sont donc pas douze documents inventés distincts. Sur un cas, une clé de fait
inconnue provoque également une erreur avant correction.

Le contrôle des UUID et du décodage est un contrôle technique hors application, sans score
de pertinence et sans conditionner l'affichage d'une réponse. Les 32 décodages sans erreur
après correction ne certifient pas que les questions proposées sont juridiquement correctes,
ni qu'elles pourront toutes être enregistrées : le cas NUL reste précisément une limite
technique de stockage PostgreSQL.

## Vérification des livrables et des lectures

Les plans ont été examinés manuellement. Dans cet échantillon, la rédaction de l'accord
reste demandée dans les deux répétitions après correction ; le mail sans pièce reste une
rédaction. Les bornes 2025 sont conservées pour la jurisprudence par pertinence, et les
demandes de listes chronologiques conservent leurs filtres de dates et de chambre.

Le corpus de recherche isolé contient les mêmes **84 points de 13 documents communs**
que l'expérience précédente. Les bases SQL et vectorielle sont en mémoire. Les modèles
réels d'embedding, de reranking et de génération sont utilisés ; les plans sont rejoués
depuis les sorties brutes, sans nouvel appel de planification ni correction du contenu.

| Cas | Vérification manuelle de la réponse et des sources |
|---|---|
| C04 — pièces à réunir, traitement des primes et mail sans calcul | Les deux versions produisent ces trois livrables. Après correction, la réponse conserve l'effectif, l'ancienneté, le salaire, le 13e mois, le montant de la prime et sa période de mission, ainsi que les incertitudes sur la CCN et la prime. Aucun montant d'indemnité n'est calculé. |
| C09 — accord sur une majoration à 10 % | Les deux versions produisent un projet d'accord avec des articles, des champs à compléter et des questions sur la conclusion de l'accord. La sortie après correction compte 9 694 caractères. Ce contrôle ne certifie pas la validité juridique du projet. |
| C06 — dernières décisions de la chambre sociale | Cinq sources sont effectivement transmises au générateur après correction du banc ; la réponse liste les cinq références attendues dans le corpus figé, datées des 7 et 14 octobre 2026. |
| F01 — développer l'arrêt déjà cité | L'identifiant fourni est utilisé pour relire les sept passages indexés de l'arrêt du 10 septembre 2025, n° 23-14.455. Ils sont intégralement transmis dans le groupe de source ; la réponse en expose l'objet, la règle et la portée. |

Le premier banc RAG avait deux raccordements incomplets : le lecteur explicite utilisait
encore le client Qdrant local par défaut, et le catalogue conservait sa fabrique de sessions
par défaut capturée à la définition de son constructeur. Ces deux essais ont donc échoué
avec zéro source. Ils sont conservés et ne sont pas comptés comme des lectures réussies.

Seuls ces deux cas ont été rejoués, une fois chacun, après correction des raccordements
du banc. Une lecture SQL/index sans génération payante a d'abord vérifié les cinq résultats
du catalogue et les sept passages de l'arrêt. Les sorties initiales n'ont pas été remplacées.
Ces deux reprises corrigent le montage technique du test ; elles ne constituent pas une
boucle de réparation ou de sélection du contenu généré.

Au total : six exécutions RAG initiales et deux reprises techniques. Les écritures de
conversations et dossiers restent dans SQLite en mémoire ; les événements de coût sont
collectés localement. Aucune modification ni écriture applicative n'est effectuée en
production. Les accès autorisés sont utilisés en mémoire du processus ; les clés ne sont
pas enregistrées dans les artefacts.

## Limites observées

La correction empêche les identifiants hors contexte dans le schéma, mais ne choisit pas
la bonne source à la place du modèle. Un identifiant valide peut encore être mal choisi.

Un plan après correction contient un NUL dans son thème de recherche. Le défaut avait
déjà été observé dans la référence d'expériences antérieures ; cette nouvelle série ne
permet pas d'en attribuer la cause au schéma. La sortie est conservée intégralement et
n'est pas déclarée exploitable en PostgreSQL.

La consultation de la clause de non-concurrence est parfois demandée à la fois dans
`document_checks` et dans `requests`, avant comme après correction. Aucun dédoublonnage
sémantique n'est ajouté. Les plans d'entretiens professionnels présupposent parfois une
périodicité non fournie, également avant comme après. Ce problème reste à traiter dans
la préparation de la recherche ; le schéma d'identifiants ne le résout pas.

Le rapport long C07 n'est pas régénéré intégralement dans cette série. Sa planification
conserve le livrable et les pièces accessibles, mais cela ne prouve pas la qualité d'un
nouveau rapport. Les tests du code couvrent aussi le stockage, les droits et la conservation
des sorties ; ils ne constituent pas une évaluation éditoriale du modèle.

L'estimation selon les tarifs inscrits dans le dépôt est de **0,85 USD** pour l'ensemble
des 64 planifications et des huit exécutions RAG, y compris les essais dont le banc était
mal raccordé. Elle comprend embeddings et reranking et ne déduit pas les remises de cache.
Ce n'est pas une facture fournisseur. Les différences de temps et de coût de ces quelques
essais ne démontrent pas un gain en production. Les schémas varient selon le contexte ;
leur incidence sur les caches et la latence reste à mesurer à plus grande échelle.

## Code, tests et preuves

Le code modifié pour cette étape est limité à `conversation_requests.py` et à la
construction du schéma dans `conversation_orchestrator.py`. Les tests ajoutés sont dans
`backend/tests/test_planner_document_capabilities.py` : absence de références, lectures
connues, périmètre des pièces, continuation, isolation entre appels et conservation brute
d'une sortie inexécutable sans relance. Les tests d'autorisation et de lecture des sources
existants sont également exécutés.

La première suite étendue termine avec **109 tests réussis et 1 ignoré**, en 32,43 secondes.
La suite complémentaire, sans recouvrement avec celle-ci, ajoute **201 tests réussis** en
51,50 secondes : routage, sécurité, périodes de décisions, plans de recherche, prompts,
erreurs, conservation du streaming et expansion des sources. Cela donne **310 tests
distincts réussis et 1 ignoré**. Le test ignoré nécessite l'activation explicite d'un
parcours payant. Les neuf scénarios HTTP de référence utilisent des transports simulés
pour vérifier les contrats techniques. `ruff --select F,I` et `git diff --check` passent.
Les résultats sont également consignés dans `validation_summary.json` avec les preuves privées.

Les preuves sont dans `tmp/planner-capabilities-20261026/` : entrées et requêtes figées,
64 réponses complètes, protocoles, huit résultats RAG, validation du banc corrigé,
analyse des contrats et revue manuelle. Le manifeste SHA-256 permet de vérifier ces
fichiers et les sources conservées. Les données de conversations ne doivent pas être
versionnées. Le présent rapport ne reproduit pas les noms des personnes des dossiers.

Les modifications des étapes précédentes sont préservées. Aucune des variantes de prompt
chronologique rejetées n'est réintroduite. **Aucun commit, push ou déploiement** n'est effectué.
