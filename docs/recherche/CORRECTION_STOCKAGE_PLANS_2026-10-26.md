# Compatibilité du stockage des plans — 26 octobre 2026

Le cas NUL observé pendant la comparaison du planificateur est maintenant signalé avant
l'exécution ou l'enregistrement de ses propositions. La sortie brute reste inchangée et
consultable dans les événements du dossier, avec une erreur technique précise.

## Défaut reproduit

La réponse archivée `H02.after.1.json` contient un échappement JSON `\u0000` dans le thème
de recherche. Le texte brut est enregistrable, mais son décodage produit un caractère NUL
dans une chaîne. Python accepte ce JSON ; PostgreSQL refuse de stocker cette chaîne en JSONB.

Avant correction, ce plan était compilé comme exécutable. L'erreur pouvait survenir lors
de l'écriture de l'observation, puis être présentée comme un échec d'enregistrement du dossier.
Le rejeu de cette même sortie avec le décodeur corrigé retourne `search_planner_error` et
le détail technique `planner_json_contains_nul`. Les octets UTF-8 de la sortie brute sont
identiques avant et après. Aucun nouvel appel au modèle n'est nécessaire à cette vérification.

## Changement

`decode_requests` vérifie la compatibilité NUL des structures compilées destinées à
l'exécution ou à l'enregistrement : plan, faits, requêtes et détails d'erreurs. Ce contrôle
intervient avant l'application des propositions du plan et les consultations externes.

Le contrôle porte sur ces structures, plutôt que sur toutes les valeurs du JSON d'entrée :
une valeur déjà rejetée par le contrat ne doit pas empêcher une opération indépendante
valide de continuer si rien d'incompatible ne subsiste dans les structures à enregistrer.
Les emplacements d'erreur de validation sont également vérifiés ; ils peuvent contenir le
nom d'une clé invalide et sont représentés par des tuples avant leur sérialisation JSON.

Lorsqu'une structure à enregistrer contient NUL :

- aucune proposition de ce plan n'est appliquée ;
- l'observation conserve le texte brut complet, sans structure décodée inexécutable ;
- l'erreur `planner_json_contains_nul` est conservée dans l'événement et la trace ;
- le flux HTTP expose une erreur technique dédiée, avec un accès à la sortie originale
  par le dossier ; aucune recherche ou génération de remplacement n'est lancée.

Le mot `null`, un véritable `null` JSON et le texte qui contient littéralement les caractères
`\u0000` restent acceptés lorsqu'ils ne produisent pas de NUL au décodage. Les accents,
émojis, espaces et sauts de ligne sont conservés. Aucune chaîne n'est nettoyée ou réécrite.
Ce contrôle ne juge ni la qualité juridique ni l'intention d'une réponse.

## Tests

La suite ciblée termine avec **126 tests réussis et 1 ignoré**, en 57,67 secondes. Elle
comprend les tests des requêtes, de l'orchestrateur, des dossiers, des capacités documentaires,
du parcours HTTP, du streaming et des lectures de sources. Le test ignoré est un parcours
payant qui nécessite son activation explicite.

Treize tests concernent spécifiquement ce changement, dont deux sur **PostgreSQL 16 réel**
dans un conteneur Docker jetable, avec un port aléatoire limité à localhost et un répertoire
de données en mémoire. Aucune base applicative existante n'est utilisée. Ils vérifient :

- le refus JSONB avec le code PostgreSQL `22P05`, et l'acceptation du texte littéral échappé ;
- le parcours HTTP complet jusqu'à l'erreur technique, avec conservation exacte du brut ;
- l'absence d'ajout de faits ou tâches et la version inchangée du dossier ;
- l'absence de recherche et de génération finale, avec un seul appel de planification simulé ;
- la consultation du brut par l'utilisateur autorisé et son refus à un autre utilisateur ;
- la conservation des demandes indépendantes valides lorsqu'une autre demande est invalide.

Pour exécuter les tests de stockage avec PostgreSQL local :

```sh
AORIA_LOCAL_POSTGRES_TESTS=1 backend/.venv/bin/python -m pytest -q \
  backend/tests/test_planner_storage_contract.py \
  backend/tests/test_planner_storage_postgres.py
```

Docker et l'image déjà présente `postgres:16-alpine` sont nécessaires. Les tests ne téléchargent
pas d'image et suppriment leur propre conteneur à la fin. Sans activation explicite, les deux
tests PostgreSQL sont ignorés. `ruff --select F,I` et `git diff --check` passent.

## Portée et preuves

La correction traite le défaut de stockage reproduit. Elle ne supprime pas la production
de caractères NUL par le modèle : elle permet d'en conserver le brut et de signaler la
sortie structurée inexécutable, au lieu d'échouer tardivement dans la transaction SQL.
Elle ne change ni le prompt, ni le modèle, ni les budgets, ni les règles de recherche.

Le rejeu privé est dans `tmp/planner-storage-20261026/`, avec la sortie avant/après,
le protocole, les empreintes et les sources conservées. Les fichiers `*_final.json`
correspondent au contrôle final. Les essais intermédiaires sont préservés. Aucun nouvel
appel payant n'a été effectué pour cette étape.

Les corrections précédentes et les travaux parallèles présents dans le dépôt sont préservés.
**Aucun commit, push ou déploiement** n'est effectué.
