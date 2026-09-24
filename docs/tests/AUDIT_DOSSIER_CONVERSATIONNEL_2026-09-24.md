# Audit du dossier conversationnel — 24 septembre 2026

**Suivi :** ce rapport conserve les constats de l’audit initial. Les correctifs
locaux apportés ensuite sont décrits en section 22 du
[plan d’intégration](../architecture/PLAN_DOSSIER_CONVERSATIONNEL.md).
Les contrôles PostgreSQL, navigateur et pilote restent nécessaires ; ce rapport
ne constitue pas une validation de production.

## Verdict et périmètre

Le socle est utile, mais l’intégration ne peut pas être déclarée terminée ni prête
pour une activation générale. Les mentions « implémenté » du plan décrivent la
présence du code, pas la satisfaction complète des exigences.

Audit local des lots 1 à 8 : plan d’intégration, modèles, services, orchestration,
génération, API, interface, isolation, export/suppression, activation et tests.
Aucune modification de l’implémentation ni action en production pendant cet audit.
Pas d’appel payant au LLM, de test navigateur réel, de migration PostgreSQL réelle
ou de mesure de performance en production. Les constats ci-dessous distinguent
la reproduction contrôlée de l’analyse statique.

## Vérifications exécutées

- Backend : 113 tests réussis, 1 ignoré dans 11 fichiers ciblant dossier, calculs,
  orchestration, chat, pièces, bibliothèque, sécurité, traces et administration.
- Frontend : 21 suites, 82 tests réussis.
- TypeScript : `npx tsc --noEmit` réussi.
- `git diff --check` réussi.
- Reproduction additionnelle sur SQLite en mémoire, avec sortie de planificateur
  simulée : salaire enregistré `3200.10`, variable proposée `9999`, expression
  `salary * 3`. Résultat réel : `29997`, statut `executed`. Aucun fichier applicatif
  ni donnée réelle modifiés par cette reproduction.
- Avertissements existants : dépréciations FastAPI/SWIG et avertissements React
  `act()` dans les tests organisation. Ils ne constituent pas la cause des défauts.

## Défauts prioritaires

### A1 — Valeurs calculées non liées techniquement aux faits (P1, reproduit)

`conversation_orchestrator.py:1075` vérifie l’existence de la clé du fait, pas que
la variable correspond à sa valeur/version. `case_calculation.py:37` emploie la
valeur textuelle proposée par le modèle. Une clé contestée est également disponible.
La formule est donc calculée exactement, mais sur des valeurs potentiellement
différentes du dossier. L’arithmétique seule ne sécurise pas le calcul métier.

Correction recommandée : références d’entrée/version et valeurs numériques
structurées avec unités ; résolution déterministe des variables référencées.
Les valeurs hypothétiques restent explicitement des scénarios. Une ambiguïté
technique doit être signalée, sans parser arbitrairement le texte libre ni réparer
la sortie du modèle.

### A2 — Cycle de vie des tâches incomplet entre les tours (P1, analyse statique)

`case_file_service.py:441` crée uniquement de nouvelles tâches.
`observation_context` ne transmet des anciennes tâches que leur identifiant,
type, question et statut, sans dépendances ni entrées/pièces associées.
Le contrat du plan ne propose pas de mise à jour d’une tâche existante ; les
dépendances ne visent que les tâches du nouveau plan.

Après une clarification ou la correction d’un fait, la nouvelle tâche peut être
exécutée alors que l’ancienne reste bloquée indéfiniment. Le dossier accumule des
questions devenues obsolètes. Il faut un contrat explicite de reprise, remplacement
ou clôture des tâches existantes, avec historique et contrôle de version.

### A3 — Des lectures documentaires écrasent les résultats précédents (P1, statique)

`conversation_orchestrator.py:824`, `:837`, `:878` réaffectent
`results = _document_results(current_documents)`. Une recherche juridique suivie
d’une lecture/recherche documentaire perd ses sources dans la liste finale.
Les branches peuvent encore contenir leurs textes : le prompt, les citations et
la disponibilité des sources pour les calculs ne sont alors plus cohérents.

Conserver des résultats séparés par action, puis assembler les sources finales
sans écraser les branches précédentes. Tester les deux ordres d’exécution.

### A4 — L’échec d’une branche interrompt toute la réponse (P1, statique)

L’orchestrateur arrête l’exécution sur exception de recherche ou dépassement du
budget ; `conversations.py:1469` à `1498` retourne une erreur sans synthèse.
Cela contredit l’objectif de conserver les résultats obtenus et de signaler les
tâches non exécutées. Le dépassement du nombre de recherches est présenté comme
une erreur de planification plutôt que comme un budget atteint.

Distinguer les erreurs globales des erreurs par branche et décider explicitement
de la restitution des résultats partiels, sans inventer de contenu de remplacement.

### A5 — Prompt resté en mode observation (P1, statique)

`conversation_orchestrator.py:74` indique que `case_delta` et `case_tasks`
« ne pilotent jamais la réponse de ce tour ». Le code fait désormais l’inverse.
Le prompt demande une formule établie, mais n’explique pas clairement la
continuation après recherche juridique pour construire cette formule à partir
des passages reçus. Les possibilités ajoutées au schéma ne suffisent pas à
décrire ce processus au modèle.

Aligner les instructions sur les phases réelles. Une recherche réussie n’est
pas, à elle seule, une qualification juridique établie : préciser la distinction
entre récupération de sources, proposition de scénario et résultat arithmétique.

### A6 — Gestion des conflits et finalisation incomplètes (P1/P2, statique)

L’application du delta intercepte correctement ses erreurs. En revanche,
`record_task_execution` appelé à `conversation_orchestrator.py:1099` peut lever
un conflit de version sans traitement local équivalent. Une correction depuis
le panneau pendant la préparation peut ainsi empêcher la réponse de se terminer.

`conversations.py:1499` traite les réponses directes sans appeler
`link_task_answer`, contrairement à la génération normale. Les clarifications
peuvent rester `ready_for_generation` sans lien vers leur réponse.
`link_task_answer` incrémente la version sans événement d’audit correspondant.

Définir une finalisation commune aux différents chemins et un traitement explicite
des conflits, sans relancer ni réinterpréter silencieusement le plan.

## Écarts supplémentaires et optimisation

### A7 — Traçabilité documentaire incomplète (P2)

`observation_context` omet `source_document_id`, `source_extraction_id` et les
liens documentaires. Ces données existent en base et dans l’API mais ne sont pas
reprises dans le dossier envoyé au modèle aux tours suivants.
Dans l’interface, `documentsById` est indexé seulement par document : deux
extractions du même fichier peuvent afficher la mauvaise version de provenance.
Les liens déjà présents ne voient pas leur couverture de lecture actualisée.

Transmettre les références exactes ; utiliser la paire document/extraction pour
l’affichage ; conserver une couverture datée par lecture plutôt qu’une propriété
supposée définitive du document.

### A8 — Le feature flag ne couvre pas toute la modification (P2)

Le flag contrôle l’accès au dossier, son injection et son affichage. Il ne coupe
ni la création du dossier lors d’une nouvelle conversation, ni les champs du
schéma/prompt, ni la nouvelle exécution multi-recherches. Les organisations hors
pilote peuvent donc subir une partie des changements et du coût de planification.
Ce n’est pas un mécanisme complet de comparaison témoin/pilote ou de retour arrière.

Définir les capacités concernées et tester le parcours complet flag désactivé,
pas seulement le refus HTTP de lecture du dossier.

### A9 — Volume et latence non maîtrisés sur les longues conversations (P2)

- Toutes les entrées actives et tâches ouvertes sont réinjectées, sans budget global
  du dossier ; la limite d’import s’applique à chaque opération, pas au cumul.
- Les mêmes messages peuvent être réimportés, créant des doublons.
- Les sources sont présentes dans le contexte RAG et dans le JSON des branches ;
  elles sont encore répétées dans les résultats d’outils/traces.
- Les recherches indépendantes sont attendues séquentiellement dans la boucle.
- La lecture publique du dossier charge les événements complets, dont les sorties
  brutes, alors que `public_payload` ne renvoie pas les événements.
- Le contrôle d’accès réutilise une lecture de conversation chargeant ses messages.

Optimiser les lectures et la sélection du contexte, séparer stockage intégral et
contexte transmis, avec limites explicites sans troncature des générations.
Paralléliser seulement après avoir isolé les états mutables et sessions nécessaires
à chaque recherche. Mesurer avant de promettre une baisse de coût.

### A10 — Transparence des erreurs et consultation du brut à compléter (P2)

Les observations sont conservées en base. L’interface utilisateur ne les expose
pas ; Admin Quality les retrouve depuis la trace d’un message assistant. En cas
d’échec avant ce message, ce chemin d’inspection ne suffit pas.

Le chemin de flux silencieux dans `conversations.py:1703` ajoute un avertissement
à la réponse brute sauvegardée. Ce comportement est déjà présent dans la chaîne
de chat, mais contrevient à la règle de ne pas compléter la génération : afficher
l’incident séparément du texte original.

### A11 — Exigences du plan non réalisées ou seulement partielles (P2/P3)

- Pas de finalisation créant un `legal_finding` lié à la réponse et à ses sources.
- Contestations conservées, mais sans relation explicite reliant les deux versions
  contradictoires (contrairement aux remplacements).
- Pas de vraie chronologie datée distincte, ni de synthèse/conclusions dédiées.
- Correction manuelle des calculs désactivée dans l’interface, mais pas interdite
  dans le service : l’API peut créer un résultat corrigé sans sa spécification.
- Mesures réelles de coût/latence, migration PostgreSQL, comportement mobile réel
  et validation pilote restent à réaliser.

## Ce qui est solide dans le périmètre testé

- Contrôle d’accès réutilisant propriétaire, appartenance et masquage de conversation.
- Profil organisationnel courant et instantanés historiques.
- Enregistrement du message avant la planification.
- Corrections append-only et contrôle optimiste de version.
- Conservation brute des plans, sans réparation ou boucle d’évaluation éditoriale.
- Évaluateur arithmétique borné sans `eval`, appels ou accès aux attributs.
- Export et effacement du dossier raccordés au cycle de vie existant.
- Panneau utilisateur, actions explicites et rafraîchissement SSE testés.

Ces contrôles ne constituent pas une certification de sécurité exhaustive.

## Exigences à ajuster plutôt qu’implémenter littéralement

- Les noms des statuts, événements SSE et fichiers de composants peuvent différer
  du plan si le contrat reste cohérent ; ce ne sont pas des défauts bloquants.
- Un second passage borné après consultation est pertinent : il ne doit pas être
  une réparation de génération et ses coûts doivent être explicites.
- Ne pas ajouter un appel LLM pour extraire automatiquement des conclusions de la
  réponse finale. Une référence à la réponse originale, ses sources et la version
  du dossier peut satisfaire le besoin de traçabilité sans réécriture.
- L’import historique intégral sur sélection explicite est raisonnable, mais n’est
  pas encore une extraction structurée des faits ; le présenter comme tel.
- Le statut `executed` doit rester technique et ne jamais certifier le droit.

## Ordre recommandé avant pilote

1. Corriger A1, A3, A4 et A5 ; ajouter leurs tests de non-régression.
2. Achever le cycle inter-tours et la finalisation (A2, A6).
3. Fiabiliser provenance, transparence et activation (A7, A8, A10).
4. Borner et mesurer le contexte, supprimer les charges inutiles (A9).
5. Mettre à jour le périmètre produit réel et le plan (A11).
6. Tester PostgreSQL, parcours navigateur, scénarios longs et corrections
   concurrentes ; puis pilote explicitement choisi et mesures de coût/latence.

Les tests actuels vérifient surtout des parcours heureux et des contrats locaux.
Ils n’établissent pas encore la robustesse du traitement complet d’une situation
complexe sur plusieurs tours. Leurs succès ne lèvent pas les défauts ci-dessus.
