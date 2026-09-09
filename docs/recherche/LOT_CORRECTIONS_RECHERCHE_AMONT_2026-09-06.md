# Lot de corrections — recherche documentaire en amont

Date : 6 septembre 2026.

Statut : premier chantier implémenté et vérifié techniquement en local, sans déploiement ni validation du contenu réel.

Suivi : voir `BILAN_CORRECTIONS_RECHERCHE_AMONT_2026-09-06.md`, section « État actuel — ancien pipeline retiré ». Les corrections A–C et les mutualisations D sont implémentées ; le pipeline historique a été retiré avec ses tests devenus obsolètes. Les propositions initiales d'évaluation de qualité ne sont plus à exécuter sans nouvelle demande explicite. La sélection documentaire et le reranking restent le second chantier.

## Rectification demandée par l'utilisateur

La consigne du 6 septembre « pas de fallback ou de post-traitement déterministe » prime sur les propositions initiales ci-dessous, notamment C2.

- Aucun remplacement du plan en cas d'échec du planificateur ou du classifieur : erreur visible, sortie brute conservée et pas de recherche de secours.
- Retrait de la recherche BOSS forcée par mots-clés et de la reconstruction automatique d'une relance à partir des messages précédents.
- Pas de nettoyage, troncature ou réécriture des champs produits par le planificateur ; pas de réinterprétation de sa question par le constructeur déterministe. Les contraintes sont exprimées dans le prompt.
- Les contrôles d'accès au corpus restent obligatoires. Le décodage JSON nécessaire à l'exécution ne remplace jamais l'affichage de la génération brute.
- L'ancien pipeline et ses replis ont depuis été supprimés. Les replis préexistants du reranking restent dans le second chantier et ne doivent pas être présentés comme supprimés.
- Les résultats des essais LLM déjà archivés décrivent des étapes intermédiaires, pas une validation de cette révision. Les omissions du modèle ne sont plus compensées par les deux règles retirées.

## Objectif et périmètre

Améliorer le passage de la question utilisateur aux candidats documentaires : routage, contexte conversationnel, références exactes, ciblage des corpus, temporalité et exécution des branches de recherche.

Le reranking, ses seuils, l'expansion des documents parents et la rédaction finale feront l'objet du second chantier. Le présent lot ne change pas les modèles, les droits d'accès, les conventions installées ou les paramètres de classement.

L'audit local a exécuté 137 tests ciblés existants avec succès. Des scénarios supplémentaires ont reproduit les défauts ci-dessous, mais leur fréquence et leur effet sur les réponses de production ne sont pas encore mesurés.

## Contraintes communes

- Conserver intégralement toute sortie LLM non vide et la rendre accessible à l'utilisateur conformément à `AGENTS.md`. Aucun nettoyage, remplacement ou rejet éditorial d'une génération. Placer les contraintes de forme et de contenu dans les prompts ; les contrôles éventuels produisent des avertissements visibles. Une représentation structurée destinée à l'exécution ne doit pas remplacer la sortie brute.
- Conserver la question originale séparément des données de recherche contextualisées.
- Faire respecter les autorisations dans chaque accès au corpus, y compris les références directes et les branches de secours.
- Ne jamais assimiler la présence d'un candidat à la preuve de son applicabilité ou à une validation juridique.
- Préserver les modifications locales existantes, étrangères à ce chantier.

## Ordre de réalisation

| Étape | Changements | Résultat attendu |
| --- | --- | --- |
| A | Routage et références exactes | Les vraies questions atteignent le RAG ; les références ne sont plus déformées. |
| B | Contexte conversationnel, sources et dates | Les recherches portent sur le bon sujet, les corpus demandés et la bonne période. |
| C | Couverture des branches et secours | Le plan exécuté respecte ses obligations et conserve les résultats disponibles. |
| D | Mutualisation et nettoyage | Supprimer les appels redondants après validation des comportements. |

Chaque étape doit être isolable dans un commit et accompagnée de ses tests de régression. Pas de suppression de l'ancien pipeline avant validation de son remplacement.

## A1 — Réduire les faux refus du routeur

Fichier principal : `backend/app/rag/intent_router.py`.

### Changements

- Remplacer les déclencheurs techniques fondés sur un mot isolé par des constructions qui portent explicitement sur AORIA, son modèle, son fournisseur ou ses instructions.
- Ne pas confondre le métier ou le statut déclaré de l'utilisateur avec une demande de contournement des autorisations.
- Retirer le raccourci qui classe automatiquement « peux-tu m'aider sur… » comme une demande de présentation du périmètre.
- Aligner le prompt du classifieur sur ces distinctions : corriger uniquement les regex laisserait le même faux refus possible au premier tour via le LLM.
- Maintenir les refus des demandes explicites de secrets, de données d'autres comptes et de contournement des contrôles d'accès.

### Acceptation

Les questions sur les frais de voyage, un modèle de lettre de licenciement, l'encadrement de ChatGPT au travail et l'aide au licenciement économique atteignent la recherche. Les demandes explicites de prompt système, de clés API et de données d'autres comptes restent traitées par les contrôles existants.

Tester avec et sans historique. Pour le classifieur LLM : vérifier le prompt et le branchement avec des réponses simulées ; mesurer séparément le comportement réel du modèle lors de l'évaluation, sans prétendre qu'un mock valide sa classification.

## A2 — Préserver l'identité complète des références

Fichiers principaux : `backend/app/rag/parent_expansion.py`, `backend/app/rag/article_chunker.py`, `backend/app/rag/search_plan.py`.

### Changements

- Reconnaître les suffixes multiples : `L. 1235-3-1` reste `L1235-3-1`.
- Supprimer les reconstructions ambiguës : `L1234` ne devient pas `L123-4`.
- Reconnaître les articles numériques lorsqu'ils sont explicitement introduits comme articles, sans convertir toute année ou tout nombre en référence juridique.
- Associer la référence à son Code lorsque celui-ci est explicitement établi. Pour plusieurs articles appartenant à plusieurs Codes, porter cette association par référence plutôt qu'appliquer un filtre global.
- Conserver la compatibilité des numéros de pourvoi déjà reconnus.
- Vérifier les métadonnées produites par l'indexation avant de décider si un rattrapage des données est nécessaire. Ne pas annoncer qu'une modification du parseur répare les données déjà indexées.

### Acceptation

Extraction correcte de `L. 1235-3-1`, `L. 242-1-4` et `article 1240 du Code civil`. Aucun article fabriqué à partir de `L1234`. Une recherche explicitement rattachée à un Code n'injecte pas un homonyme d'un autre Code. Les tests de cloisonnement passent pour chaque type de référence.

## B1 — Résoudre les relances indépendamment de la recherche exacte

Fichiers principaux : `backend/app/rag/search_plan.py`, `backend/app/rag/agent.py`.

### Changements

- Découpler la dépendance au contexte de la route documentaire : la présence d'un article ne doit pas désactiver la résolution d'une relance.
- Couvrir les formulations elliptiques reproduites : « Et les cadres ? », « Quelle durée ? », « Peux-tu détailler ? ».
- Permettre au planificateur d'identifier une dépendance à l'historique non reconnue par les règles déterministes. Le champ contextualisé est une sortie distincte ; il ne remplace pas la question originale.
- Utiliser les références des sources déjà citées pour résoudre les anaphores, sans considérer les affirmations précédentes de l'assistant comme des faits établis.
- Recalculer les besoins documentaires à partir du contexte résolu sans élargir les droits ou attribuer arbitrairement une convention.
- Traiter les questions longues sans rejeter une sortie parce qu'elle dépasse un seuil éditorial de 600 caractères. Préserver la génération brute et adapter le contrat de génération/exécution.

### Acceptation

Après une question sur le préavis, « Et les cadres ? » produit une recherche contextualisée sur ce préavis. Une relance contenant un article conserve également le contexte. Un changement explicite de sujet ne reprend pas l'ancien. Une question autonome longue ne déclenche pas l'ancien pipeline uniquement en raison de sa longueur.

## B2 — Expliciter le rôle des sources demandées

Fichiers principaux : `backend/app/rag/source_intent.py`, `backend/app/rag/search_plan.py`, `backend/app/rag/agent.py`.

### Changements

- Corriger les déterminants élidés, dont « selon l'accord d'entreprise ».
- Distinguer mention, priorité, demande exclusive, exclusion et comparaison. Ne pas étendre mécaniquement les restrictions existantes à chaque nom de source rencontré.
- Prendre en charge les Codes présents dans le corpus, en commençant par le Code de la sécurité sociale et le Code civil.
- Ne pas transformer une négation en demande positive de la source ni propager cette source dans les branches auxiliaires qui doivent respecter l'exclusion.
- Distinguer « mon contrat » comme situation exposée de l'analyse d'un contrat identifié parmi les documents accessibles. Tracer l'absence de document identifiable.
- Pour une source demandée mais indisponible, rendre cette limite visible et distinguer les compléments généraux des résultats de la source demandée.

### Acceptation

« Selon l'accord… » et « selon notre accord… » sont reconnus. « Ne cherche pas dans la CCN » ne lance pas de branche CCN. Une comparaison conserve ses deux corpus. Une convention non installée ne devient jamais accessible du seul fait de la demande. La présence de plusieurs contrats ne conduit pas à déclarer arbitrairement l'un d'eux comme celui de l'utilisateur.

## B3 — Séparer les différentes dates

Fichiers principaux : `backend/app/rag/search_plan.py`, `backend/app/rag/agent.py`, `backend/app/rag/search.py`.

### Changements

- Distinguer période des faits, date d'application du droit recherchée et période de publication des sources.
- Donner priorité à une période explicite sur la période par défaut des actualités.
- Ne pas utiliser une date d'embauche comme filtre de publication documentaire.
- N'appliquer un filtre strict que lorsque le sens de la date et les métadonnées disponibles le permettent. Une date de publication ne prouve pas qu'une disposition était applicable ce jour-là.
- Tracer les demandes historiques que le corpus disponible ne permet pas de résoudre ; ne pas prétendre reconstituer une version juridique absente.

### Acceptation

« Nouveautés en droit social en 2024 » cible 2024. « Embauché en 2018, licencié aujourd'hui » ne cible pas les publications de 2018. « Règles applicables en 2024 » reste distinct de « textes publiés en 2024 ». Une période incertaine produit un signal explicite, pas un filtre inventé.

## C1 — Exécuter les obligations de couverture

Fichier principal : `backend/app/rag/agent.py`.

### Changements

- Construire une liste explicite de branches avec leur objet, requête, périmètre autorisé, contraintes de sources, période et budget de candidats.
- Ajouter la récupération exacte à cette liste au lieu de retourner avant l'exécution des compléments requis.
- Exécuter une branche BOSS lorsque le plan la recommande, sauf exclusion explicite ou recherche déjà équivalente.
- Respecter les exigences CCN, jurisprudence et documents internes sans les confondre avec des garanties de présence dans la réponse finale.
- Tracer pour chaque branche : prévue, exécutée, réussie, vide ou en erreur, et candidats uniques ajoutés.

### Acceptation

Une question combinant référence exacte et CCN exécute les deux recherches. Une recommandation BOSS déclenche la branche attendue. Aucune branche ne contourne les restrictions de source ou d'accès. Les budgets et les raisons d'absence de résultats sont consultables dans la trace.

## C2 — Conserver un secours cohérent et les résultats partiels

Fichiers principaux : `backend/app/rag/agent.py`, `backend/app/rag/search_plan.py`.

### Changements

- En cas de sortie vide, d'erreur de transport ou de délai expiré du planificateur, exécuter le plan minimal avec le même moteur, sans relancer automatiquement l'ancien ensemble condensation/expansion/ancre.
- Pour une sortie LLM non vide inexploitable, conserver et afficher la sortie brute avec l'avertissement technique approprié. Ne pas relancer une génération pour corriger son style ou son format. Un éventuel secours documentaire utilise les informations applicatives établies.
- Conserver les candidats des branches réussies lorsque les variantes principales échouent.
- Distinguer une absence de document d'une indisponibilité technique.
- Corriger les libellés de trace pour décrire le chemin réellement exécuté.

### Acceptation

Simuler : timeout du planificateur, sortie vide, sortie non vide inexploitable, panne d'une variante, panne de toutes les variantes avec branche législative réussie, panne de toutes les branches. Les résultats disponibles sont conservés et la trace expose la dégradation. Aucun post-traitement ne masque une génération non vide.

## D — Mutualisations après stabilisation fonctionnelle

1. Fusionner la recherche CCN de plancher et la recherche CCN prioritaire lorsqu'elles portent exactement sur les mêmes requête et filtres. Exécuter une seule récupération au budget maximal utile.
2. Éviter la seconde récupération d'identifiants déjà effectuée dans la même requête, en conservant son diagnostic de présence ou d'absence.
3. Mutualiser les encodages dense et sparse d'une même requête pendant une seule préparation de contexte. Pas de cache global de résultats : le moteur est partagé et les contextes de coût et d'accès doivent rester propres à chaque requête.
4. Centraliser le filtre d'accès documentaire avec des tests de parité pour les recherches hybrides et directes. Préserver explicitement le comportement des usages administratifs autorisés.
5. Retirer l'ancien pipeline seulement après recherche de tous ses appelants et validation du nouveau secours. Supprimer alors les prompts, helpers et tests devenus effectivement obsolètes.
6. Donner un usage explicite à `missing_facts` ou réduire ce champ lors d'un chantier ultérieur. Ne pas ajouter automatiquement une étape de clarification utilisateur à toutes les questions.

Acceptation : une seule recherche pour chaque couple requête/périmètre équivalent, un seul encodage par texte identique dans une requête, aucune contamination entre requêtes simultanées et aucune perte de couverture documentaire.

## Validation et mesure de qualité

### Régressions techniques

Étendre les suites de routage, planification, références, condensation, intention de sources, cloisonnement et parité du pipeline. Ajouter les scénarios négatifs de cet audit et les erreurs partielles. Tester la préservation et l'exposition des sorties LLM brutes lorsqu'un contrôle produit un avertissement.

Les tests simulés vérifient le contrat et les filtres ; ils ne suffisent pas à établir que les bons passages seront retrouvés dans le corpus réel.

### Évaluation documentaire avant/après

Préparer un jeu initial de 40 à 60 questions : questions directes, suivis de conversation, références exactes, demandes de corpus, négations, comparaisons, dates et cas à plusieurs enjeux. Annoter les références ou familles de sources attendues avec une validation métier. Inclure des sources attendues absentes du corpus pour distinguer défaut de recherche et défaut de couverture.

Comparer sur un même instantané de corpus et des réglages de reranking inchangés :

- proportion de questions légitimes atteignant la recherche ;
- exactitude de l'identifiant et du Code résolus ;
- présence des sources attendues dans les candidats avant reranking ;
- couverture des enjeux demandés et respect des exclusions ;
- pertes de contexte sur les suivis ;
- recherches vides et branches indisponibles ;
- nombre d'appels, coûts et latence de préparation.

Ne pas fixer de gain chiffré avant la mesure de référence. Les corrections ne sont validées comme amélioration documentaire qu'après examen des gains et des régressions sur ce jeu.

## Hors du lot et livraison

- Ajustement du modèle de reranking, des seuils et des quotas de documents finaux.
- Modification de la génération finale, hormis les avertissements et l'accès aux sorties brutes nécessaires au respect d'AGENTS.md.
- Nouvelle ingestion massive ou réindexation : décision séparée si A2 révèle une incompatibilité des données existantes.
- Déploiement en production : non demandé. Lorsqu'il sera demandé, appliquer `docs/exploitation/DEPLOIEMENT_PRODUCTION.md` et `ACCES_PROD.md`.

Livrables attendus de l'implémentation : corrections par étape, tests de régression, jeu d'évaluation annoté, comparaison avant/après et liste explicite des limites restantes.
