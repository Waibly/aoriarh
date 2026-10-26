# Modèle de planification du chat : comparaison et limites — 26 octobre 2026

État après revue de code : la variante modèle/configuration/prompt décrite ici est
archivée séparément et exclue du premier lot technique. Le code de ce lot conserve
`EXPAND_MODEL=gpt-5-mini` pour le chat. Les résultats ci-dessous décrivent
l'expérience réalisée ; ils ne décrivent pas un déploiement. Voir la
[revue du premier lot](REVUE_CODE_LOT_TECHNIQUE_2026-10-26.md).

## Résultat retenu localement

La planification du chat utilise désormais un réglage propre, `CONVERSATION_PLANNER_MODEL`,
avec `gpt-5.6-terra` comme valeur par défaut, à la place de `gpt-5-mini` pour cette étape.
Le modèle de rédaction finale était déjà `gpt-5.6-terra` et reste inchangé. La recherche
compacte conserve `EXPAND_MODEL=gpt-5-mini`.

Deux lignes du prompt demandent également de reprendre exactement l'intitulé et l'IDCC
fournis pour une convention collective, sans développer son nom de mémoire. Les variantes
plus larges de formulation des recherches ne sont pas retenues.

Une correction technique accompagne ce réglage : un livrable `document_review` peut être
préparé lorsque ses pièces autorisées sont déjà lues, sans exiger une nouvelle action de
lecture. L'absence de pièce et l'échec d'une consultation explicitement demandée restent
bloquants. Le type de tâche et la sortie brute du planificateur ne sont pas modifiés.

Cette sélection améliore les cas initiaux vérifiés, mais **ne supprime pas tous les
présupposés juridiques**. Les contre-exemples restants figurent ci-dessous. Aucun contrôle
sémantique automatique, correction de plan, remplacement de réponse, bascule conditionnelle
de modèle ou relance de qualité n'est ajouté dans l'application.

## Défaut et méthode

Le planificateur pouvait transformer « que vérifier pour les entretiens professionnels ? »
en une recherche présupposant un bilan à six ans. Le défaut apparaissait parfois seulement
dans `search_queries`, alors que la question principale restait neutre. Une instruction
générale existait déjà dans le prompt ; sa présence ne suffisait pas à garantir ce comportement.

La comparaison reprend 17 cas figés : dix conversations de l'audit de production, trois
cas de dates et quatre contrôles contrastés. Ces derniers vérifient notamment que les
chiffres explicitement fournis restent présents avec leur statut : ancien tableau à
vérifier, clause de CDD de 18 mois, informations d'embauche inconnues et taux issus d'un
passage déjà consulté.

Chaque variante reçoit deux répétitions par cas. Les réponses de référence sont réutilisées
sans modification pour les comparaisons suivantes ; elles ne sont pas recomptées comme de
nouveaux appels. Les requêtes, réponses et échecs sont conservés intégralement. La revue
du contenu est séparée de l'application, sans score automatique ni condition sur le rendu.
Les vérifications automatisées portent sur les contrats techniques et l'identité des entrées.

Cette démarche compare les rôles avec les mêmes entrées et contrats, sans remplacer tous
les modèles de l'application par un seul. La documentation officielle décrit cette approche
par étape. [OpenAI — optimisation par sélection du modèle](https://developers.openai.com/cookbook/examples/agent_optimization/optimizing_agents_for_cost_and_quality#optimization-round-2-model-selection).

## Variantes et décisions

| Variante | Constat | Décision |
|---|---|---|
| Référence : `gpt-5-mini`, prompt initial | Les deux plans C03 introduisent un bilan à six ans ; une autre sortie contient NUL. | Référence conservée dans les preuves. |
| Même modèle, paragraphe général renforcé | Un des deux plans C03 contient encore cette périodicité. Six sorties présentent des erreurs de contrat, dont des références de faits inexistantes et des NUL. | Écartée. |
| Même modèle, descriptions de deux champs de recherche renforcées | Les contrats passent, mais les deux requêtes C03 contiennent encore six ans. | Écartée. |
| `gpt-5.6-terra`, prompt et schéma initiaux | Les deux plans C03 restent neutres et les 34 contrats passent. Un plan C08 invente cependant un nom de convention de propreté associé à l'IDCC 0413. | Non retenue en l'état. |
| Même modèle, deux lignes de reprise exacte des conventions | Les deux plans C03 restent neutres ; les deux plans C08 conservent l'IDCC sans inventer de branche. Les 34 contrats passent. | Réglage local retenu, avec les limites des nouveaux cas. |

Une erreur isolée ne prouve pas que le changement de prompt en est la cause. Elle interdit
en revanche de présenter cette variante comme dépourvue de défauts. Toutes les variantes
écartées restent archivées ; aucun de leurs résultats n'est remplacé par une meilleure sortie.

## Six cas nouveaux

Après la sélection, six cas non utilisés pour ajuster les variantes ont été exécutés deux
fois : heures au-delà d'un temps partiel, conventions contradictoires, grossesse dans une
autre branche, période d'essai dans un extrait de contrat, projet d'accord à 12 % et congé
pour décès dans un dossier historique. Les mêmes entrées ont ensuite été soumises au modèle
de référence, sans modification des cas ni nouveau réglage du candidat.

Les 12 plans du candidat et les 12 contrôles de référence passent les contrats techniques.
Les données contrôlées sont conservées : horaires, dates, taux proposé, durée contractuelle,
conventions annoncées et incertitudes. L'incertitude entre les conventions des commerces de
gros et Syntec reste explicite ; le candidat ne choisit pas automatiquement celle du profil.

**Limite réelle : deux nouveaux plans du candidat ajoutent encore des valeurs normatives
non fournies dans leurs requêtes** : des taux de majoration pour le temps partiel et un
minimum légal pour le projet d'accord. La référence présente aussi des valeurs ajoutées
de mémoire, notamment des taux et des seuils d'effectif. La neutralité générale n'est donc
pas démontrée. Les entrées fraîches n'ont pas été retouchées pour faire disparaître ces cas.

## Recherche et génération

Des essais RAG isolés complètent les plans. Ils utilisent les composants réels, SQLite et
Qdrant en mémoire, les API réelles et des plans enregistrés rejoués sans réparation. Les
comparaisons C03, C04 et C09 utilisent le même corpus figé de 84 points de 13 documents communs.

| Cas | Observation du candidat retenu, comparé à la référence |
|---|---|
| C03 — entretiens avant une échéance | La recherche ne présuppose pas six ans. L.6315-1 est transmis et une checklist est produite. Cela ne valide pas l'ensemble du droit applicable à l'échéance. |
| C04 — pièces, primes et mail sans calcul | La réponse comprend la checklist, les règles de traitement des primes et le mail. Les faits contrôlés restent présents : effectif, salaire mensuel brut, 13e mois, prime, période de mission et incertitudes. Aucun montant d'indemnité n'est calculé. |
| C09 — accord à 10 % | La référence produit une analyse et des questions complémentaires, sans projet rédigé. Le candidat produit un projet de dix articles avec les paramètres à compléter. Ce constat ne certifie pas sa validité juridique. |
| C08 — grossesse et CCN 66 | Dans les deux versions, la réponse retrouve la réduction conventionnelle et ses conditions dans la source. Le passage indexé 92 est intégralement conservé dans les sources transmises à la génération. |
| C07 — rapport long | Le rejeu du même plan révèle puis corrige un statut « bloqué » malgré trois pièces déjà lues. La génération avec le contexte des pièces produit un rapport de 33 051 caractères, terminé normalement, avec les trois textes transmis intégralement. |

Le dernier test utilise un corpus apparié de 97 points de 16 documents : les 84 points
initiaux et 13 passages CCN 66 de trois documents communs. Les vecteurs supplémentaires
ont été lus en production sans écriture ; leur texte est identique à l'archive initiale.
Une première lecture avait une vérification de périmètre erronée supposant un seul document ;
elle a échoué avant export. La lecture corrigée vérifie les trois documents connus et
l'isolation au corpus commun. Il ne s'agit pas d'une relance de génération.

Ces corpus sont des sous-ensembles contrôlés de l'index. Ils ne démontrent pas l'exhaustivité
des sources de production. En particulier, les dispositions transitoires pertinentes pour
la date du cas C03 ne sont pas établies par ce corpus. La couverture des réformes et des
transitions reste un chantier distinct.

Pour C07, le contrôle d'exécution a révélé une incompatibilité entre le contrat du
planificateur et le suivi des tâches : `answer/document_review`, sans action ou dépendance
supplémentaire, était systématiquement marqué bloqué, même si les pièces avaient été lues.
Le contrôle se fonde maintenant sur la disponibilité technique de ces pièces. Sept tests
couvrent les statuts avec et sans pièces et une consultation explicite en échec.

Le rejeu avant/après utilise le même plan enregistré et les mêmes textes, dans une base
isolée. Il montre le changement de statut sans changement de plan ni de source. Une première
génération de 27 490 caractères utilisait le contexte général de rédaction ; elle est conservée.
Le dernier essai fournit le contexte de lecture des pièces utilisé par l'endpoint et les
douze messages antérieurs archivés, puis génère une seule fois le rapport de 33 051 caractères.
Il s'agit d'une correction du montage technique du test, sans réparation ni sélection du
texte produit. Les fichiers originaux et leurs autorisations historiques ne sont pas
reconstitués : le test utilise les textes déjà lus et une autorisation locale isolée.

## Coût et délai

Sur les 34 appels de la matrice principale, selon les tarifs inscrits dans le dépôt :

| Mesure | Référence | Réglage retenu |
|---|---:|---:|
| Coût estimé total de planification | 0,12859 USD | 0,78776 USD |
| Coût estimé moyen par appel de planification | 0,0038 USD | 0,0232 USD |
| Délai médian mesuré | 8,66 s | 5,67 s |
| P95 observé, rang le plus proche | 14,81 s | 18,04 s |

Le surcoût moyen mesuré est donc d'environ **0,0194 USD par appel de planification**.
Une conversation nécessitant deux passages peut supporter ce surcoût deux fois. Le nombre
maximal de passages, le niveau de raisonnement, les budgets et le modèle de rédaction ne
changent pas.

Les variantes ont été exécutées par lots successifs avec réutilisation de contrôles, pas
dans une mesure de charge en production. Les caches et le réseau peuvent influer sur les
temps. La médiane baisse dans cet échantillon, mais la queue de latence ne s'améliore pas ;
aucune baisse générale du coût ou du délai n'est revendiquée.

L'ensemble de cette étape représente **194 appels de planification distincts et 16 appels
de génération**. Les contrôles recopiés ne sont pas recomptés. Le coût total estimé est
de **4,07 USD**, embeddings et reranking compris. Ces montants utilisent les prix du dépôt,
sans déduction des remises de cache ; ce ne sont pas des factures fournisseur.

## Implémentation et contrôles

`settings.conversation_planner_model` alimente `CONVERSATION_PLANNER_MODEL`. Seul le
planificateur du chat prend ce réglage ; les autres rôles conservent leur configuration.
Les Compose de développement et de production transmettent la variable au backend. Les
deux valeurs `gpt-5.6-terra` et `gpt-5-mini` ont été vérifiées avec `docker compose config`,
sans lancer ou modifier un service applicatif.

Un test HTTP vérifie qu'un modèle choisi pour la planification ne change ni la rédaction
ni la recherche compacte, et que les options de transport interdisent les relances. Ce test
a aussi révélé une erreur du simulateur SDK : son clone conservait un pointeur vers les
anciennes options. Le simulateur a été corrigé pour enregistrer les options réellement
transmises ; ses réponses et fragments restent inchangés.

La version locale produit exactement les 17 requêtes de la variante retenue, modèle,
prompt, schéma, données et budgets compris. La suite ciblée termine avec **343 tests réussis,
1 test payant optionnel ignoré**, en 115,80 secondes. Elle comprend les droits, la recherche,
les erreurs, le streaming, les dossiers, les neuf scénarios HTTP et les deux tests PostgreSQL 16.
`ruff --select F,I` et `git diff --check` passent.

Les preuves privées sont dans `tmp/planner-neutral-search-20261026/`,
`tmp/planner-neutral-fields-20261026/`, `tmp/planner-model-20261026/` et
`tmp/planner-model-names-20261026/`. Le dernier dossier contient la synthèse finale
`validation_final.json`, les contrôles
frais, la revue manuelle et le manifeste d'intégrité. Les conversations ne sont pas versionnées.

Pour sélectionner l'ancien modèle lors d'une livraison ultérieure, le réglage est
`CONVERSATION_PLANNER_MODEL=gpt-5-mini`. Ce changement reste manuel et ne dépend pas de la
qualité d'une réponse. Les étapes précédentes et les travaux parallèles du dépôt sont
préservés. **Aucun commit, push ou déploiement n'est effectué.**
