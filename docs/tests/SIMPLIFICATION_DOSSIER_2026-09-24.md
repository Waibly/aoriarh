# Simplification du dossier — vérification locale du 24 septembre 2026

## Périmètre

Parcours activé du dossier conversationnel, planificateur `requests_v2`, stockage,
recherches et contexte de rédaction. Aucun déploiement de production. Le frontend
local utilise explicitement `127.0.0.1:8000`, sans résolution ambiguë de `localhost`.

## Changements

- Liste unique de demandes ; suppression des actions de génération du contrat LLM.
- Compilation explicite vers l'exécuteur existant, sans réparation des générations.
- Faits enregistrés avant les recherches, avec provenance et contrôle de version.
- Continuation différentielle, seulement après obtention de nouveau contenu utile
  au traitement (pièce lue, source pour calcul) ; pas de relance corrective.
- Découverte documentaire exclue du schéma de continuation. Les cas ambigus vont
  directement à la rédaction avec la liste des candidats, sans lecture automatique.
- Recherches indépendantes parallélisables ; résultats mutualisés par dépendances.
- Applicabilité du profil conventionnel explicitée ; une CCN incertaine n'impose
  pas le filtre conventionnel de l'organisation à la recherche.
- Dates structurées typées dans le schéma, précision partielle conservée en texte.
- Dossier distinct de la réponse ; consignes Markdown et de non-répétition dans le
  prompt. Texte final original intégral, sans validateur éditorial.
- Mesures des appels et erreurs techniques conservées dans les traces.

## Essais réels, distincts du rendu

Les essais ont été réalisés explicitement pendant le développement, pas sous
forme d'une boucle automatique relançant les générations des utilisateurs.

1. Premier appel isolé v2 : 18,74 s, contrat accepté. Revue manuelle : consultation
   documentaire superflue pour une demande de checklist. Instructions clarifiées.
2. Premier parcours PostgreSQL : rejet d'une date `2026-06` par le stockage. Le
   schéma acceptait une chaîne arbitraire. Correction du contrat des dates ; aucune
   réparation ni réapplication de la génération fautive.
3. Parcours complet `f9ab6d6b-1354-450d-b283-ae7fcef80e4b` : réponse initiale
   enregistrée en 77,2 s, puis correction salariale et e-mail en 17,2 s. Dossier
   conservé ; 3 200 € supersédé par 3 450 €. Aucun calcul exécuté au second tour.
4. Parcours complet `6ca872ae-4707-4a4b-811a-0995e271a3bf` : les deux échanges
   aboutissent, mais le premier prend 105,1 s avec consultations inutiles. Ce
   résultat ne constitue PAS une validation du gain de latence. Découverte en
   continuation retirée du schéma ; effort du même modèle porté de minimal à low.
5. Dernier appel isolé avec ces réglages : 25,92 s, une recherche juridique et
   trois livrables dépendants, aucune recherche de fichier ni calcul. Pas de
   passage de réparation. Cet appel teste le planificateur, pas le temps total
   de rédaction finale.

## Vérifications automatisées

Résultat final : **108 tests réussis**, 1 test payant ignoré (opt-in séparé),
6 avertissements de dépréciation préexistants. Contrôles de style des modules
modifiés et `git diff --check` réussis. Backend local redémarré, OpenAPI HTTP 200.

Suites : `test_conversation_requests`, `test_conversation_orchestrator`,
`test_chat_stream_timeouts`, `test_case_files`, `test_case_calculation`,
`test_chat_document_journey`, `test_conversation_documents`.

Couverture : contrat de sortie, erreurs indépendantes, conservation des sorties
brutes, faits conservés malgré une recherche échouée, dates imprécises non réparées,
CCN incertaine, parallélisation, continuation sans régénération, pièces ambiguës,
droits révoqués, correction/versionnement, arithmétique et flux lent.

Les anciennes simulations du contrat actions_v1 restent explicitement isolées
pour le parcours sans dossier. Les tests HTTP documentaires utilisent requests_v2.

## Limites

Ces essais ne certifient pas la justesse juridique ni l'exhaustivité sémantique des
réponses. Les faits restent éditables par l'utilisateur. La latence varie avec la
taille de la sortie et le modèle ; aucune promesse de gain moyen ne peut découler
de ces quelques essais. Le dernier réglage de raisonnement peut consommer plus de
tokens par appel ; les métriques doivent guider le suivi, pas un validateur de texte.

Les réponses des essais précédents ne sont ni réécrites ni supprimées. Leurs
conversations restent visibles localement sous les titres de vérification.
