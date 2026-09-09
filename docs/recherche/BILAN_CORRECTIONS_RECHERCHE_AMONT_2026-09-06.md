# Recherche amont — bilan local du 6 septembre 2026

## État actuel — ancien pipeline retiré

Le retrait du chemin de compatibilité est terminé localement. `prepare_context` construit le plan compact quand aucun plan n'est fourni ; le paramètre `adaptive_search` a été supprimé, ainsi que son usage dans le point d'entrée commun. Les recherches exactes qui n'exigent pas de planification LLM restent prises en charge.

Supprimés : anciens prompts de condensation, expansion et ancre législative ; fonctions correspondantes ; reconstruction du sujet courant ; nettoyage/déduplication des variantes textuelles ; recherche de remplacement sans filtre ; configuration du modèle de condensation devenue inutilisée. Le marqueur textuel `[HORS_SCOPE]` ne déclenche plus de refus de remplacement dans la recherche, les chats ou le sandbox. Le routeur dédié reste en place. L'ancienne constante de réponse hors-sujet est conservée uniquement pour les rapports portant sur les messages historiques.

Les tests de comportements supprimés ont été retirés avec leur code ; les tests de fusion documentaire et de construction des messages restent conservés. Des tests du point d'entrée par défaut vérifient une seule tentative du planificateur et aucune recherche de remplacement en cas de sortie vide, JSON inexploitable ou erreur de transport. Des tests de streaming couvrent aussi une sortie contenant l'ancien marqueur.

**Validation actuelle : 300 tests réussis**, deux avertissements de dépréciation existants, Ruff (`I,F`) réussi et `git diff --check` réussi. Aucun appel à un LLM ni évaluation automatique du contenu lors de cette étape. La baisse du nombre de tests par rapport aux bilans précédents vient du retrait des comportements obsolètes, avec ajout de tests de migration.

Le nettoyage du premier chantier est implémenté localement. Le rendu sur le corpus réel reste à examiner par l'utilisateur ; aucune amélioration de contenu n'est affirmée. Le second chantier (sélection et reranking) n'est pas commencé. Pas de commit, push, déploiement ou réindexage.

## Suite du nettoyage après adoption des règles globales

Modifications locales supplémentaires :

- Suppression du jugement automatique de la reformulation par comparaison avec la question originale, dans le plan et dans les avertissements affichés.
- Suppression de la requête auxiliaire construite par concaténation des thèmes LLM : utilisation de la question telle quelle.
- Conservation intégrale du texte des messages sélectionnés pour l'historique du planificateur (la fenêtre de six messages reste inchangée).
- Retrait des paramètres inutilisés de longueur et de nombre dans le décodage des listes du planificateur.
- Correction technique du filtre : une liste explicite de sources vide n'est jamais élargie.
- Distinction entre panne de toutes les recherches et absence de documents, avec erreur technique dédiée dans le chat authentifié et la démo.

Vérifications sans appel LLM ni évaluation du contenu : **85 tests ciblés réussis**, puis **6 tests du flux de chat réussis**, dont deux nouveaux cas vérifiant que la sortie brute précède l'erreur technique. Ruff (`I,F`) et `git diff --check` réussis.

À cette étape intermédiaire, l'ancien chemin de compatibilité restait à retirer. Ce retrait est maintenant terminé (voir l'état actuel ci-dessus). Les mécanismes de sélection et de reranking restent dans le second chantier. Aucune évaluation automatique de qualité n'est prévue sans nouvelle demande explicite.

## Consigne appliquée pendant l'implémentation

Pas de fallback sémantique ni de correction déterministe des générations dans le planificateur adaptatif. Les sorties brutes restent affichables, y compris lorsqu'elles sont inexécutables.

Retraits effectués après la précision de l'utilisateur : branche BOSS forcée par mots-clés, reconstruction d'une relance avec l'historique, réinterprétation déterministe de la question générée, nettoyage/troncature/déduplication des champs du plan et remplacement automatique d'un plan en erreur. Le classifieur ne remplace plus une sortie inexploitable par `legal_question`. Les erreurs de planification sont distinguées de l'absence de documents dans les flux de chat.

La branche BOSS reste possible lorsqu'elle est demandée par le plan. Les filtres d'accès, le rapprochement technique des identifiants avec l'index et les mécanismes existants de sélection documentaire ne sont pas des corrections de la génération brute.

## Vérifications des étapes précédentes

- Suite backend ciblée : **315 tests réussis**, avec deux avertissements de dépréciation existants.
- Après suppression du helper de réécriture devenu inutilisé et distinction des erreurs dans les API : **80 tests ciblés réussis**.
- Imports et erreurs Python vérifiés avec Ruff (`I,F`) ; `git diff --check` réussi.
- Les nouveaux tests vérifient notamment : pas de recherche après échec du planificateur, erreur de routage sans intention de remplacement, pas de BOSS forcé, pas de contexte reconstruit, conservation exacte des champs et des requêtes générées.

Le jeu technique de 50 régressions issu de l'audit passait de **25/50 avant à 50/50 après** ; il reste inclus dans la suite ci-dessus. Ce sont des cas de routage, références, sources, dates et contexte, pas 50 réponses juridiques validées sur le corpus de production.

## Qualité : ce qui reste non démontré

Les appels LLM réels archivés dans `RESULTATS_RECHERCHE_LLM_FINAL_2026-09-06.json` ont montré des classifications RH correctes mais aussi une relance laissée inchangée et un indice BOSS omis. Cette archive correspond à une étape antérieure à la rectification ; elle n'est pas une évaluation de bout en bout de la version actuelle. Ces omissions ne sont plus compensées par les règles retirées.

Le corpus Qdrant local n'était pas accessible. L'amélioration de la pertinence sur les documents réels, de la qualité juridique des réponses, de la latence et du coût global reste à mesurer. Les tests sur index en mémoire ne suffisent pas à la démontrer.

Les replis préexistants du reranking restent à traiter dans le second chantier ; ceux du pipeline historique ont été retirés. Ce bilan ne prétend pas avoir supprimé tous les fallbacks du dépôt. Aucun déploiement, commit, push ou réindexage n'a été effectué.
