# Progression et préparation — vérification locale du 24 septembre 2026

## Livré localement

- Progression issue des opérations de l'orchestrateur, transmise pendant son exécution,
  et non après sa résolution : prise en compte, recherche de documents, consultation,
  recherche dans les documents, références utiles, éléments chiffrés, rédaction.
- Les étapes non exécutées ne sont pas annoncées. Les notifications de patience ne
  remplacent plus l'étape courante. Aucun pourcentage ni estimation de fin fictifs.
- Temps écoulé visible avant la première réponse ; indication de patience après
  20 secondes sur une même étape. Ce délai n'annule ni ne relance aucun appel.
- Premier fragment du modèle transmis immédiatement ; fragments suivants regroupés
  comme avant. Texte original intégral, espaces et retours à la ligne conservés.
- Mesures persistées : délai au premier texte depuis le début du traitement SSE,
  délai au premier texte depuis le lancement de la génération, tailles du contexte,
  nombre de sources, tokens d'entrée et de sortie. Les opérations précédant le SSE
  (authentification, droits, préparation initiale des pièces) ne sont pas incluses
  dans la mesure backend `first_text` ; le compteur visuel inclut l'attente réseau.
- L'inspecteur admin distingue préparation et génération sans compter deux fois les
  recherches incluses dans la préparation. Le premier texte est un jalon, pas une
  étape à additionner.

## Réduction du travail redondant

- Le prompt demande uniquement les faits nouveaux/corrections/réserves ; le profil
  reste disponible sans avoir à être recopié. Une question générale peut laisser
  le dossier inchangé. Aucun filtre sémantique n'est ajouté au stockage.
- Le contrat de recherche exprime la question autonome une seule fois. Le code la
  transmet à l'exécuteur existant ; les anciennes requêtes enregistrées restent
  lisibles et leurs reformulations distinctes ne sont pas écrasées.
- Le dossier est sérialisé sans espaces JSON superflus : mêmes valeurs, aucun fait
  supprimé. Seuls les blocs de sources strictement identiques du même document
  sont dédupliqués à l'assemblage ; dates, provenances et passages différents restent.
- Consigne de recherche neutre : ne pas présupposer une périodicité ou transformer
  une date de vérification en échéance légale. Aucune correction de sortie générée.

Modèles, effort de raisonnement, capacités, contrôles d'accès, plafonds existants et
délais techniques inchangés. Aucun nouveau routeur LLM, validateur éditorial,
fallback ou appel de réparation. Les continuations dépendantes des sources et la
parallélisation des recherches indépendantes sont conservées.

## Vérifications

Tests techniques : contrat compact et compatibilité ancienne, faits persistés avant
recherche, corrections versionnées, pièces autorisées, isolation, calculs sourcés,
continuations, erreurs séparées, sortie brute, premier fragment immédiat, SSE lent,
progression réelle, minuterie et nettoyage à la fin du flux.

Sept essais payants isolés de préparation ont été lancés avec
`backend/scripts/check_preparation_latency.py` : sorties originales imprimées pour
revue humaine, aucune notation automatique, aucun changement des conversations,
aucun appel de recherche/rédaction finale dans ce script. Tous les contrats étaient
exécutables. Temps : question simple 11,0 s ; question datée 11,9 s ; demandes
multiples 22,1 s ; correction 3,6 s ; contradiction 10,6 s ; pièce 18,7 s ; calcul
24,7 s. La correction cible l'ancien fait ; le cas multiple conserve montants et
périodes ; le calcul prévoit la recherche préalable ; la pièce distingue signature
et entrée effective. La contradiction conserve l'incertitude, mais recopie encore
une information de profil : une consigne ne garantit pas zéro répétition.

Une reformulation datée présupposait une périodicité. La consigne de recherche neutre
a été ajoutée après ces sept essais, avant l'essai complet ci-dessous. Les sept
sorties n'ont pas été réparées ni relancées pour satisfaire un validateur.

## Essai complet et comparaison limitée

Conversation locale : `b5d77c44-2b9d-457d-9571-64f4b5287a7a`, titre
« Vérification locale — progression réelle ». Appel direct de la route dans un
processus de test avec l'utilisateur local ; contrôles conversation et quota conservés.
Ce test n'est pas un test du login navigateur. Aucun mot de passe modifié.

Question : « Entretiens professionnels : que vérifier avant le 1er octobre 2026 ? »

| Mesure backend | Avant | Après |
| --- | ---: | ---: |
| Appel de préparation LLM | 14,32 s | 12,84 s |
| Sortie de préparation | 3 783 caractères | 1 591 caractères |
| Préparation totale, recherches incluses | 15,54 s | 14,52 s |
| Rédaction complète | 24,25 s | 27,33 s |
| Traitement total SSE | 39,79 s | 41,90 s |
| Premier texte | non mesuré | 20,60 s |

Après : une recherche, aucune nouvelle fiche factuelle ; réponse de 6 337 caractères
contre 4 885 auparavant. Parcours terminé avec `chat_done`, sans avertissement.
Le temps client du test direct est de 42,51 s, premier fragment à 21,06 s.

**Pas de gain total démontré.** La préparation est légèrement plus courte sur cet
essai, mais une rédaction plus longue absorbe ce gain. Pas de comparaison statistique
à charge identique, ni certification de justesse juridique/non-régression sémantique
universelle. L'évaluation est séparée de l'affichage et ne conditionne aucune réponse.

## Activation

Backend local redémarré avec PostgreSQL sur 5433 et dossier activé ; frontend local
en rechargement automatique. Aucun déploiement, commit ou push en production.
L'étape suivante est l'observation de plusieurs demandes réelles avec ces mesures,
avant toute décision de changement de modèle ou de réduction du contexte juridique.
