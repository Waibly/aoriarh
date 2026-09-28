# Audit du prompt du post d’accompagnement LinkedIn

Date : 28 septembre 2026.

Périmètre : `LINKEDIN_CAROUSEL_POST_SYSTEM_PROMPT` dans
`backend/app/services/linkedin_post_service.py`, après la première correction
du hook. Cet audit porte sur les consignes du post d’accompagnement, pas sur le
prompt HTML des slides ni sur celui des posts LinkedIn autonomes.

## Constats et corrections

| Critère attendu | Tension dans le prompt audité | Correction appliquée |
| --- | --- | --- |
| Un angle facile à comprendre | Le choix d’un angle unique coexistait avec plusieurs structures demandant de couvrir situation, mécanisme, levier et promesse du document. | Une seule décision pratique ou difficulté ; uniquement les détails qui l’éclairent. |
| Une accroche courte et exacte | Les nuances étaient renvoyées au corps, même lorsqu’elles conditionnent la vérité du hook. | Une phrase visant 8 à 14 mots et 100 caractères maximum ; les conditions indispensables restent dans l’accroche. Si nécessaire, ouvrir sur une situation ou une question précise. |
| Un apport concret | L’interdiction de reprendre les explications et la promesse du carrousel pouvait pousser vers des généralités. | Autoriser une idée essentielle reformulée ; éviter la copie de la couverture et le résumé slide par slide. |
| Une lecture mobile aérée | Trois à cinq blocs de corps pouvaient imposer du remplissage dans un post court ; les règles de forme étaient dispersées. | Deux à quatre blocs comme repère, une phrase par paragraphe, lignes vides, listes courtes selon leur utilité. |
| Un français simple | Accumulation de formulations interdites et mécanisme de « question fermée réellement difficile ». | Mots courants, verbes concrets, une idée par phrase ; aucune devinette ni suspense artificiel. |
| Le bon point de vue métier | La cible éditoriale était déclarée comme donnée dont les instructions ne devaient pas être suivies, tout en demandant d’adapter le texte à cette cible. | Distinguer le paramètre métier fiable créé par l’application des contenus sources à transformer. |
| La fidélité à la réponse | Le rôle respectif de la réponse juridique et du carrousel généré n’était pas explicite. | La réponse fonde les affirmations ; le carrousel informe sur le contenu joint et le CTA, sans devenir une source juridique indépendante. |
| Une invitation utile | L’appel à « garder un repère » pouvait produire un objet abstrait ou annoncer une grille absente du PDF. | Nommer une action et son objet, présents dans le carrousel et liés à l’angle choisi. |
| La confidentialité | Interdiction générale présente mais moins explicite que dans les autres prompts de publication. | Préciser les informations internes exclues et distinguer les seuils juridiques généraux des caractéristiques de l’entreprise source. |

## Priorités retenues

La fidélité au fond et la confidentialité priment sur la longueur et le style.
Le post vise 70 à 110 mots, sans minimum à remplir artificiellement. Pour
raccourcir, il réduit le nombre d’idées plutôt que de supprimer une condition
juridique. Les repères de longueur et de mise en page sont des consignes de
rédaction, pas des validateurs de sortie.

La génération non vide reste affichée et copiée intégralement. Aucun filtre
éditorial, correcteur, contenu de remplacement ou nouvelle boucle de génération
n’est ajouté.

## Vérification

Les tests existants du service vérifient les consignes transmises, le retour
inchangé de la sortie simulée et l’absence de jugement éditorial dans les
avertissements du post carrousel. Ils ne mesurent pas la qualité rédactionnelle
d’une génération réelle.

Vérifications locales effectuées :

- `pytest tests/test_linkedin_post_service.py -q` : 16 tests réussis ; un
  avertissement de dépréciation FastAPI préexistant dans `admin_costs.py`.
- `ruff check app/services/linkedin_post_service.py tests/test_linkedin_post_service.py` : réussi.
- `git diff --check` : réussi.

Aucun appel LLM ni évaluation automatique de générations n’a été réalisé pour
cet audit. Le respect effectif des consignes reste à examiner sur les prochaines
générations. Aucune livraison en production n’est comprise dans cette modification.
