# Diagnostic des réponses enregistrées en production

La priorité est de fiabiliser le choix de recherche avant de changer de modèle ou
de réduire le contexte. Deux réponses récentes montrent qu'une date peut orienter
une analyse juridique vers un catalogue chronologique. Une autre demande concrète
est encore arrêtée par un préfiltre de présentation du produit. Ces problèmes
apparaissent avant la rédaction finale.

Le coût enregistré se concentre sur la génération et ses entrées volumineuses.
Cette piste mérite une expérience séparée, en protégeant les passages décisifs et
les livrables longs effectivement demandés.

## Périmètre et méthode

Au point de coupure du **26 octobre 2026 à 10 h 20 min 37 s UTC**, les 60 derniers
jours contiennent **359 réponses**, dont **348 hors organisation de démonstration**.
Sur l'ensemble des 359 réponses, 358 ont une trace ; un seul retour utilisateur
explicite est enregistré, négatif, hors démonstration.

Le repérage porte sur les **220 réponses hors démo les plus récentes**, du
9 septembre au 26 octobre, puis sur le retour négatif du 1er septembre. Dix
conversations distinctes ont été retenues pour une revue documentaire séparée du
rendu : questions simples, demandes datées, plusieurs livrables, référence exacte,
liste d'actualités, travail sur pièces et routages courts.

Les originaux de ces dix conversations représentent **38 messages**. L'export
comprend leurs sources conservées, traces, événements de dossier et écritures de
coût associées. Les profils et métadonnées documentaires actuels sont étiquetés
comme tels ; ils ne remplacent pas les instantanés historiques des traces.

Les requêtes PostgreSQL utilisent des transactions `REPEATABLE READ READ ONLY`,
avec un délai maximal de 15 secondes par requête. Les contrôles Qdrant utilisent
uniquement `scroll`, sans embeddings, reranking ou génération. Aucune conversation,
configuration, indexation ou donnée applicative de production n'est modifiée.

Le code lu dans le conteneur a été archivé avec ses empreintes. Le dépôt serveur
observé est à `796e8bd1b554da2d185d18c6b80659c3ff7ac0c0`. Le backend reste démarré
avec sa date de création du 25 octobre, sans livraison effectuée par cet audit.

Cette sélection est ciblée, comporte des usages de test et mélange plusieurs
versions historiques du pipeline. Elle ne mesure pas un taux global de qualité.
La revue vérifie les demandes, les passages conservés et quelques fondements
officiels ; elle n'est pas une validation juridique exhaustive de chaque phrase.

## Les dix cas examinés

Les identifiants C01 à C10 renvoient à une correspondance conservée uniquement dans
l'archive privée. Aucun nom de personne, de client ou d'organisation n'est repris ici.

| Cas | Situation | Constat | Traitement recommandé |
| --- | --- | --- | --- |
| C01 | Nombre de jours pour un mariage | Réponse courte, fondée sur les dispositions conventionnelles conservées. Entrée de génération de 30 224 tokens. | Préserver le résultat ; expérimenter sur le contexte et le temps de préparation. |
| C02 | Heures travaillées et congés payés, avec jurisprudence de 2025 demandée | Recherche dirigée vers cinq décisions récentes de décembre 2025. L'arrêt de septembre cité dans la réponse ne figure dans aucune de ces cinq sources. | Corriger le choix entre analyse thématique et catalogue chronologique. |
| C03 | Checklist d'entretiens avant une date donnée | Catalogue d'entrées en vigueur, aucun document obtenu, tâche marquée bloquée ; réponse néanmoins affirmative sur les règles et leurs dates. | Revoir l'intention de recherche et les consignes de rédaction lorsque les sources nécessaires manquent. |
| C04 | Pièces à réunir, traitement de primes et mail, sans calcul d'indemnité | Les livrables demandés sont présents ; les inconnues sont maintenues et aucune indemnité n'est chiffrée. Contexte de 335 825 caractères. | Préserver ces comportements ; comparer une sélection documentaire plus ciblée. |
| C05 | Explication d'une décision d'appel désignée précisément | La réponse indique que la décision n'est pas dans les documents consultés, sans lui inventer de solution. | Préserver cette abstention ; examiner séparément le coût des résultats non correspondants. |
| C06 | Dernières décisions de la chambre sociale | Les cinq références affichées correspondent aux cinq sources ; limites de collecte et sélection annoncées. | Préserver le fonctionnement de la vraie demande chronologique. |
| C07 | Rapport d'enquête à partir de trois pièces | Livrable long demandé, avec distinction entre faits, déclarations et limites. Premier texte en 15,4 s, fin en 124,4 s. | Préserver le fond et le streaming ; examiner le temps de génération sans imposer de raccourcissement. |
| C08 | Réduction d'horaire et grossesse, retour négatif | Bon passage premier au reranking, puis perdu dans le contexte parent historique. | Incident historique expliqué ; conservation du passage vérifiée dans le code actuel. |
| C09 | Demande d'accord collectif introduite par « es-tu capable » | Réponse générique sur le périmètre d'AORIA RH. Faux positif reproduit avec le routeur actuel. | Correctif de préfiltre ciblé, avec tests de routage et de sécurité. |
| C10 | Vérifications avant utilisation d'une IA pour les candidatures | Ancienne réponse de confidentialité sur l'architecture. La question exacte passe aujourd'hui vers le juridique. | Garder le cas dans la référence ; aucun nouveau correctif justifié sur ce seul incident. |

## Recherche thématique et recherche chronologique

### C02 Une année demandée ne signifie pas une liste de décisions récentes

L'utilisateur décrit une semaine de travail et demande une réponse appuyée sur la
jurisprudence de 2025. Le plan conserve cette demande, mais renseigne aussi
`chronology` avec l'année 2025, `order=newest` et `limit=5`.

Cette branche remplace la recherche hybride et le reranking habituels par une
consultation du catalogue. Les cinq textes retenus sont datés des 10 et 17 décembre
2025. Le catalogue signale 37 documents correspondant au thème dans sa sélection,
un plafond de candidats atteint et une pagination restante.

La rédaction cite pourtant **Cass. soc., 10 septembre 2025, n° 23-14.455**, absent
des cinq sources enregistrées, y compris de leur texte conservé. Cet arrêt est
réel et son apport sur le décompte hebdomadaire des congés est confirmé par le
[communiqué de la Cour de cassation](https://www.courdecassation.fr/toutes-les-actualites/2025/09/10/communique-conge-paye-et-decompte-des-heures-supplementaires).
Le défaut est donc la consultation de la source décisive, pas l'invention d'un
numéro d'arrêt. Un contrôle de l'index actuel retrouve sept passages du même arrêt.

Le plan a recherché les documents récents d'une année alors qu'il fallait établir
une règle pertinente pour le cas. La mention d'une année doit rester compatible
avec une recherche thématique ; elle ne suffit pas à justifier un parcours de veille.

### C03 Une date de contrôle devient un filtre d'entrée en vigueur

La question demande les vérifications à effectuer avant le 1er octobre 2026. Le
plan génère une recherche d'entrée en vigueur se terminant à cette date, tout en
déclarant une intention `procedure`. Le catalogue exclut les codes et les CCN de
son périmètre de sources et ne renvoie aucun document.

La trace de génération contient pourtant zéro caractère de source et une tâche
juridique `blocked`. La réponse affirme notamment que la réforme s'applique depuis
le 1er octobre 2026 et énonce des périodicités et contrôles comme établis.

La date est généralisée à tort : l'[article 3 de la loi du 24 octobre 2025](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000052430940/2026-03-02)
réserve cette transition aux accords collectifs portant sur la périodicité. Le
[ministère du Travail](https://travail-emploi.gouv.fr/lentretien-de-parcours-professionnel)
distingue les dispositions déjà applicables depuis octobre 2025 et les transitions
concernant ces accords. Il précise aussi des conditions de reprise après absence
que la réponse ne restitue pas intégralement.

L'index actuel contient l'article L.6315-1 en plusieurs passages, dont une version
mentionnant les quatre ans et l'entretien de première année. Cela ne prouve pas
l'état intégral du corpus le 22 octobre ; cela montre qu'un catalogue d'entrées en
vigueur n'est pas le seul moyen de consulter ce droit.

**Expérience proposée :** préciser dans le prompt de préparation la distinction
entre établir une règle à une date, analyser un cas avec une jurisprudence datée
et lister des publications. Comparer C02 et C03, puis protéger C06 et les vraies
demandes de nouveautés. La sortie originale de chaque plan reste conservée, sans
correction déterministe de son intention ni nouvelle recherche de remplacement.

La rédaction doit également recevoir des consignes cohérentes sur les limites
documentaires. Ajouter un validateur éditorial après génération ne résoudrait pas
le mauvais choix de recherche et n'est pas proposé.

## Routage statique

### C09 Une demande concrète encore traitée comme une présentation du produit

La question combine une formulation de capacité avec un projet concret d'accord
sur le temps de travail. Elle reçoit une présentation du périmètre juridique,
suivie d'une invitation à poser une question concrète déjà présente dans la demande.

Le motif est reproductible hors ligne : la regex
`\b(es-tu|êtes-vous|es tu)\s+(spécialisé|expert|capable)\b` déclenche `meta_scope`.
Le routeur local utilisé pour cette vérification a la même empreinte que le
fichier lu dans le conteneur. Aucun LLM n'est appelé par cette vérification.

Le correctif doit préserver les questions de présentation seules et laisser les
demandes concrètes atteindre le planificateur. Les demandes de secrets et de
données d'autres comptes doivent continuer à être bloquées. Ce contrat peut être
vérifié par des tests techniques d'entrée, distincts d'une évaluation des réponses.

### C10 Un incident ancien qui ne justifie plus une nouvelle correction

La question exacte sur une IA de présélection avait reçu `meta_internals` et un
événement de reconnaissance technique le 2 octobre. Le routeur actuel renvoie
`legal_question`, sans réponse statique ni événement de sécurité. Un test existant
couvre déjà cette formulation dans
[test_intent_router_prefilter.py](../../backend/tests/test_intent_router_prefilter.py).

L'ancien résultat reste utile pour protéger ce comportement, mais il ne constitue
pas la preuve d'un défaut encore présent dans le préfiltre actuel.

## Incident conventionnel historique localisé

Le retour négatif C08 contestait une réponse affirmant l'absence de réduction
d'horaire sous la CCN 66. La disposition de réduction de 10 %, à partir du troisième
mois ou du 61e jour, figure à l'[article 20.10 consultable sur Légifrance](https://www.legifrance.gouv.fr/conv_coll/article/KALIARTI000005863131).

La trace du 1er septembre apporte une information déterminante : le fragment 92
est premier dans les candidats hybrides, puis premier au reranking, avec un score
de 0,8633. Après expansion, son groupe parent commence au fragment 85. Les textes
conservés en source finale ne contiennent plus la disposition sur la grossesse.

Dans l'index actuel, le même document et le fragment 92 portent cette disposition.
L'article est réparti sur les fragments 85 à 92. Une recherche exacte du sous-numéro
20.10 ne renvoie pas de point : ces fragments sont étiquetés sous l'article 20.

L'historique du dépôt identifie le correctif `bb7bdc1` du **2 septembre 2026** : il
retire précisément la prise du début du parent suivie d'une coupure à 9 000
caractères, pour réserver le budget au passage sélectionné. Le code actuel a depuis
évolué et conserve les passages entiers avec priorité aux passages classés.

Un contrôle local, avec le code d'expansion identique à celui lu en production et
les fragments actuels de cet article, conserve intégralement le fragment 92.
Ce contrôle n'est pas un rejeu complet de la génération historique. Il explique
le mécanisme et confirme la protection actuelle du passage.

**Conséquence :** augmenter le nombre de requêtes ou changer de modèle n'aurait
pas traité la cause de cet incident précis. Le bon passage était déjà trouvé.
Ce cas doit rester dans le jeu de non-régression de conservation du contexte.

## Coût et délai observés

Les montants ci-dessous sont ceux du suivi applicatif, en USD estimés. Ils ne
constituent pas une facture fournisseur ; le traitement du cache et les éventuels
appels non tracés limitent leur précision.

Sur les 220 réponses repérées, 217 ont des écritures d'usage associées. Les
990 écritures consultées attribuent **96,58 % du coût enregistré à la génération**,
contre environ 1,98 % à l'orchestrateur et 1,17 % au reranking.

| Cas | Durée enregistrée | Premier texte | Sources envoyées en caractères | Tokens d'entrée du générateur | Coût enregistré USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| C01 Question courte | 15,2 s | 14,0 s | 85 831 | 30 224 | 0,066949 |
| C02 Cas avec jurisprudence datée | 37,1 s | 33,3 s | 58 829 | 25 097 | 0,074005 |
| C03 Checklist sans source obtenue | 50,6 s | 36,5 s | 0 | 8 740 | 0,053094 |
| C04 Plusieurs livrables | 73,7 s | 36,6 s | 335 825 | 97 822 | 0,246296 |
| C05 Décision non consultée | 9,7 s | 8,5 s | 63 079 | 26 598 | 0,058946 |
| C06 Liste chronologique | 17,0 s | 11,8 s | 63 942 | 26 189 | 0,061450 |
| C07 Rapport sur pièces | 124,4 s | 15,4 s | 37 447 | 33 934 | 0,173019 |

Sur les 145 réponses du repérage disposant des métriques de tokens de génération,
la médiane d'entrée est de **40 762 tokens**, et le 95e percentile de **125 731**.
Sur les 219 réponses avec durée enregistrée, la médiane est de **21,5 secondes** et
le 95e percentile de **67,3 secondes**. Les quantiles utilisent l'observation
d'indice arrondi `round((n-1)*p)`. Ces chiffres décrivent ce groupe historique,
sans mesurer l'effet d'une modification ni représenter toute la clientèle.

### Cibles d'expérience

- **C01 :** 30 224 tokens d'entrée pour 129 tokens de sortie. Le planificateur
  prend 9,3 secondes, contre 2,3 secondes pour le contexte de recherche. Les
  consignes et le schéma général du planificateur méritent une expérience de
  simplification qui préserve ses capacités et les faits du dossier.
- **C04 :** un seul arrêt fournit 99 203 caractères au contexte. L'expansion
  intégrale de plusieurs décisions explique une grande partie du volume.
  Comparer des contextes à passages ciblés, en conservant les motifs, conditions
  et dispositifs nécessaires, est une piste à tester. Le texte intégral reste
  disponible comme source ; aucun raccourcissement de réponse n'est proposé.
- **C07 :** 111,8 secondes relèvent de la génération d'un rapport de 32 732
  caractères demandé par l'utilisateur. Le premier texte arrive à 15,4 secondes.
  Ce cas doit protéger les livrables longs et le streaming lors d'une optimisation.

Il n'y a pas de gain de coût ou de délai démontré par cet audit. Les métriques
désignent où mener des comparaisons, pas une autorisation à retirer des nuances
ou à plafonner les réponses.

## Lots proposés et critères de vérification

1. **Choix de recherche dans le prompt de préparation.** Comparer les analyses
   datées C02/C03 avec les listes C06. Vérifier que les sources décisives sont
   effectivement consultées et que les limites de consultation restent explicites.
2. **Préfiltre C09.** Préparer un correctif indépendant, avec tests des questions
   de capacité seules, des demandes concrètes et des demandes sensibles. Conserver
   C10 parmi les protections déjà satisfaites.
3. **Volume du contexte.** Comparer C01/C04/C05 à sources disponibles identiques,
   en gardant le passage classé et les fondements nécessaires. Protéger C08 et
   les consultations de décisions complètes. Mesurer les tokens et le coût estimé.
4. **Temps de préparation.** Tester séparément une simplification des consignes
   ou du schéma du planificateur. Maintenir les corrections de faits, exclusions,
   droits documentaires et besoins multiples dans le même parcours de chat.

Pour les comparaisons de rédaction, les sources enregistrées sont déjà figées.
Un rejeu complet de recherche demanderait un instantané autorisé plus complet du
corpus et des candidats ; les aperçus de trace ne remplacent pas les passages
intégraux de tous les candidats historiques. Les essais auront lieu hors production,
avec appels bornés et sorties originales intégrales, sans note automatique ni
relance éditoriale. Chaque changement se compare indépendamment avant livraison.

## Conservation des preuves

Les originaux et la correspondance des cas sont conservés uniquement dans
`tmp/prod-answer-audit-20261026/`, ignoré par Git, répertoire privé `0700` et fichiers
`0600`. Ils comprennent :

- inventaire, sélection et transactions SQL en lecture seule ;
- `selected_snapshot.json` et les dix fichiers de cas, avec textes originaux ;
- traces, sources historiques conservées et métadonnées actuelles distinctes ;
- code déployé consulté, empreintes et état du serveur ;
- lectures ciblées de l'index actuel, sans nouveaux appels modèle ;
- métriques descriptives, revue documentaire manuelle et contrôles locaux.

Les noms, données personnelles et textes de pièces ne sont pas copiés dans le
présent rapport versionné. Les archives privées doivent être sauvegardées dans
un emplacement privé durable avant une campagne ultérieure.

Aucune génération payante, évaluation automatique des réponses, modification
applicative ou livraison en production n'est effectuée dans ce lot.
