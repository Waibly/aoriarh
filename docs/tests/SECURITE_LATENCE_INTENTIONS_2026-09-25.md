# Sécurité, latence et intentions — 25 septembre 2026

## Périmètre retenu

Les lots sécurité et instrumentation/optimisation technique sont retenus.
La variante de reformulation testée n'est **pas retenue pour livraison** : les
résultats ne permettent pas de conclure à une absence de régression. Le prompt
et l'alimentation de l'intention du planificateur restent inchangés.

Aucun changement de modèle, de limite de sortie, de timeout, de facturation,
de politique de cache ou de rendu des générations. Aucun validateur sémantique,
réécriture, filtre de réponse, fallback ni relance corrective ajouté.

## Lot 1 — Dépendances

- Next.js verrouillé en 15.5.24 ; Sharp en 0.35.4.
- Installation propre, audit npm sans vulnérabilité signalée au moment du test.
- 92 tests frontend réussis ; TypeScript, build Next.js et test de l'artefact
  standalone réussis (pages, session anonyme, assets, en-têtes, absence de
  dépendance de développement).
- Les avertissements de lint préexistants ne sont pas traités dans ce lot.

Références des mainteneurs :
[Next.js](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4),
[Sharp](https://github.com/lovell/sharp/security/advisories/GHSA-rgj7-g3m4-5g8c).

## Lot 2 — Mesures et travail redondant

### Serveur

Le chronomètre part à l'entrée du handler HTTP, après résolution des dépendances
FastAPI. Il inclut désormais les contrôles d'accès/quota, la lecture documentaire
initiale et la sauvegarde du message/lecture du profil avant le streaming.
Les traces distinguent ces opérations, le premier statut et le premier texte.
Les délais d'authentification en dépendance et le réseau ne sont pas couverts
par ce chronomètre serveur.

Le dossier expose les temps de chargement initial, d'enregistrement de
l'observation et d'application des faits. Lorsqu'aucun fait n'est appliqué,
une lecture de version remplace le rechargement complet intermédiaire des
faits/tâches/documents. Le contrôle des corrections concurrentes et la lecture
finale du dossier sont conservés. Tests dédiés : deux lectures complètes au lieu
de trois ; conflit de version toujours signalé.

`answer_and_case_save` mesure la sauvegarde réponse/dossier avant celle de la
trace. L'événement SSE `chat_done.timings` fournit `request_to_done_ms` et
`post_generation_ms`, comprenant aussi la fin des opérations quota/titre.
Ces deux dernières mesures ne sont pas persistées en base par un second commit.

### Navigateur

La timeline Performance contient `aoriarh.chat.headers`, `first_status`,
`first_text`, `done` et `error` (événement SSE d'erreur). Il s'agit de la réception
des événements, pas d'une mesure du rendu visuel effectif. Chaque jalon apparaît
une fois par appel. Aucune donnée de conversation ni télémétrie externe ajoutée.

### Usage des modèles

Les détails de tokens de cache et de raisonnement fournis par le fournisseur
sont conservés séparément dans les traces du planificateur et du générateur.
Un détail absent reste inconnu, jamais assimilé à zéro ; ces compteurs ne sont
pas additionnés aux totaux de tokens ni utilisés pour modifier la facturation.
Le skill OpenAI Docs a guidé la lecture des champs documentés de
[Chat Completions](https://developers.openai.com/api/docs/guides/predicted-outputs).

Cela permet de mesurer le coût des étapes ; cela ne démontre pas encore un gain
de latence bout en bout. Aucun objectif arbitraire de vingt secondes n'est garanti.

Validation après retrait de la variante de prompt : 115 tests backend réussis
(orchestrateur, demandes, streaming, dossier, bibliothèque, documents, prompts de
génération et compteurs de tokens). Ruff ciblé et `git diff --check` réussis.

## Lot 3 — Comparaison séparée, variante non retenue

`backend/scripts/compare_planner_intents.py` fige les appels puis exécute une
comparaison explicite payante, sans base applicative ni relance automatique.
Douze situations synthétiques, trois répétitions par variante : 72 appels réels,
sans erreur de transport. Sorties originales conservées localement dans :

- `/tmp/aoriarh-planner-20260925-before`
- `/tmp/aoriarh-planner-20260925-after`

Ces répertoires temporaires ne constituent pas une archive versionnée.

La variante retirait l'intention initialisée par mots-clés des contraintes
du planificateur et ajoutait au prompt : déterminer l'intention depuis la demande
originale ; traiter « que vérifier » comme une checklist ; rechercher les dates,
seuils et périodicités sans présupposer leurs valeurs.

| Mesure du planificateur seul | Avant | Variante |
| --- | ---: | ---: |
| Appels | 36 | 36 |
| Médiane du temps d'appel | 6,92 s | 9,14 s |
| Médiane des tokens totaux | 4 589 | 4 874 |

Les cohortes sont exécutées successivement, à concurrence de deux appels.
Charge du fournisseur, cache et variabilité ne sont pas contrôlés : ces chiffres
ne prouvent pas une causalité ni un effet sur la durée totale du chat.

La lecture manuelle montre des progrès mais aussi des problèmes :

- La checklist « entretiens professionnels » passe de `factual_rule` à
  `procedure` dans les trois répétitions.
- Les mails seuls et corrections de mail restent des tâches de rédaction.
- Certaines requêtes de checklist présupposent encore des périodicités ; une
  sortie contient une longue suite de guillemets. Elle n'a pas été nettoyée.
- Sur le cas complexe, une répétition réintroduit la convention du profil malgré
  la convention inconnue, et une référence `fact_keys` absente des faits proposés.
- Les primes peuvent encore être qualifiées d'exceptionnelles sans que leur
  nature soit établie ; ce défaut existe aussi dans les sorties avant modification.

La variante n'est donc pas livrée et ses modifications ont été retirées du code
actif. Aucun jugement automatique n'est ajouté à l'application. Ces essais
portent sur la préparation, pas sur la recherche exécutée ni sur une réponse
juridique finale : ils ne certifient pas la justesse juridique de bout en bout.

### Suite nécessaire

Reprendre la fidélité des reformulations au niveau du prompt : séparation nette
entre faits fournis, informations inconnues et règles à rechercher ; pas
d'élargissement implicite du livrable. Refaire une comparaison distincte avec les
mêmes cas et les sorties brutes, puis un parcours complet dossier → recherche →
réponse. Ne pas compenser ces défauts par des règles éditoriales post-traitement.
