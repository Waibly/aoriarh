# Plan d’intégration du dossier conversationnel AORIA RH

> Décision du 24 septembre : dossier généralisé sans interrupteur d'activation ni
> liste pilote. Les passages historiques ci-dessous décrivant une activation
> conditionnelle sont remplacés par le
> [plan de généralisation](../exploitation/GENERALISATION_DOSSIER_2026-09-24.md).

**Statut :** Lots 1 à 7 implémentés localement ; dispositifs du Lot 8 prêts,
validation pilote et activation production à effectuer.
**Date :** 23 septembre 2026
**Périmètre :** chat authentifié, recherche juridique, pièces de conversation,
calculs et productions dérivées

**Révision après audit du 24 septembre :** les défauts identifiés font l’objet des
correctifs décrits en section 22. « Implémenté localement » ne signifie ni déployé,
ni validé en conditions réelles. Les essais PostgreSQL, navigateur et pilote restent
nécessaires avant une activation générale.

## 1. Décision produit

AORIA RH doit faire évoluer la conversation vers un **dossier juridique vivant**.
Le chat reste le moyen d’échanger ; le dossier conserve et organise les faits,
les pièces, les questions, les tâches, les calculs et les conclusions au fil des
tours.

Le dossier ne remplace jamais :

- le texte original des messages ;
- les pièces et leur version d’extraction ;
- les sources juridiques ;
- le jugement de l’utilisateur sur la pertinence de la réponse.

Le dossier doit être visible et corrigeable par l’utilisateur. Une mémoire
invisible ferait courir le risque qu’une extraction erronée devienne une vérité
silencieuse utilisée dans tous les échanges suivants.

## 2. Objectifs

Le dossier doit permettre de :

- conserver les faits importants au-delà de la fenêtre récente du chat ;
- distinguer faits déclarés, contenu des pièces, position d’une partie,
  hypothèses et conclusions juridiques ;
- traiter une demande contenant plusieurs questions et plusieurs tâches ;
- exécuter une recherche distincte pour chaque question juridique ;
- conserver les dépendances entre une qualification juridique, un calcul et une
  rédaction ;
- ne pas redemander une information déjà fournie ;
- signaler les contradictions sans les résoudre silencieusement ;
- produire des courriers, notes, chronologies et tableaux à partir d’un même
  socle factuel ;
- rendre chaque élément traçable jusqu’au message ou à la pièce d’origine ;
- réduire le volume et le désordre du contexte dynamique envoyé au modèle ;
- rendre les réponses reproductibles grâce à la version du dossier utilisée.

## 3. Principes non négociables

### 3.1 Conservation des sorties et absence de réparation automatique

- La demande originale est conservée et fournie intégralement à la génération
  finale.
- Une sortie structurée invalide du planificateur est conservée brute et donne
  lieu à une erreur technique distincte.
- Aucun second appel LLM ne répare, ne complète ou ne réécrit automatiquement
  un plan jugé insuffisant.
- Aucun validateur ne juge automatiquement la qualité sémantique, le style ou
  la pertinence d’une génération.
- Les contrôles automatiques portent seulement sur le contrat technique :
  schéma, types, limites, droits d’accès, identifiants et paramètres d’action.

### 3.2 Provenance avant confiance

Le dossier n’attribue pas un score opaque de « confiance ». Il indique la
provenance et le statut :

- déclaré par l’utilisateur ;
- lu dans une pièce ;
- affirmé par l’employeur, la RH ou une autre partie ;
- hypothèse de travail ;
- conclusion juridique produite par AORIA ;
- contesté ;
- remplacé par une information plus récente.

### 3.3 Pas d’écrasement silencieux

Une correction crée une nouvelle version et conserve la valeur précédente. Une
contradiction crée deux éléments reliés et une question à résoudre ; elle ne
provoque pas un choix automatique entre les versions.

### 3.4 Cloisonnement

Le dossier hérite des droits de la conversation : propriétaire, organisation et
administration autorisée. Aucun fait, document ou résultat ne traverse les
frontières d’une organisation ou d’un utilisateur.

## 4. Socle disponible dès le début d’une conversation

### 4.1 Données organisationnelles héritées

Dès le premier message, chaque dossier peut utiliser le profil déjà connu de
l’organisation :

- nom de l’organisation ;
- forme juridique ;
- secteur d’activité ;
- tranche d’effectif déclarée ;
- conventions collectives installées et leurs IDCC ;
- indication que l’organisation n’est soumise à aucune convention collective ;
- profil métier de l’utilisateur pour adapter le niveau de langage, sans en
  faire un fait juridique du dossier.

Ces informations sont déjà chargées par `_load_org_context` dans
`backend/app/api/conversations.py`. Elles doivent devenir un **socle
organisationnel hérité**, visible dans le dossier avec la mention « Profil de
l’organisation ».

### 4.2 Ne pas dupliquer une source de vérité

Le profil courant de l’organisation reste stocké dans les tables
`organisations` et `organisation_conventions`. Le dossier ne doit pas créer une
copie indépendante que l’utilisateur serait obligé de maintenir dans chaque
conversation.

Le fonctionnement recommandé est :

1. afficher le profil courant par référence dans chaque dossier ;
2. enregistrer dans chaque événement de traitement un instantané daté du profil
   réellement transmis au modèle ;
3. utiliser le profil actualisé aux tours suivants ;
4. conserver l’ancien instantané pour expliquer les réponses antérieures.

Ainsi, une modification de la convention collective ou de la taille déclarée
est immédiatement utilisable sans réécrire tous les dossiers, tandis que les
réponses passées restent reproductibles.

### 4.3 Effectif : tranche et nombre exact sont différents

Le champ actuel `Organisation.taille` est une tranche déclarative. AORIA ne doit
jamais la convertir en effectif exact. Si l’utilisateur indique ensuite « 42
salariés », le dossier enregistre séparément :

- tranche d’effectif issue du profil de l’organisation ;
- effectif exact déclaré pour le dossier ;
- date à laquelle cet effectif est pertinent ;
- provenance du nombre exact.

Pour les règles dépendant d’une date ou d’une méthode de décompte, le nombre de
salariés reste un fait à qualifier et non une donnée universelle permanente.

### 4.4 Une initialisation par conversation

Chaque conversation possède son dossier afin de conserver un périmètre simple
et sûr. Toutes les conversations d’une même organisation héritent du même socle
organisationnel, mais leurs faits propres restent séparés.

Le rattachement de plusieurs conversations à un dossier transversal pourra être
ajouté plus tard, uniquement par une action explicite de l’utilisateur.

## 5. Contenu fonctionnel du dossier

### 5.1 Faits

Exemples : contrat, statut, poste, ancienneté, rémunération, effectif, dates,
événements, personnes ou fonctions concernées.

Chaque fait contient au minimum :

- une clé fonctionnelle ;
- un libellé lisible ;
- une valeur textuelle et, si nécessaire, une valeur structurée ;
- sa provenance ;
- son statut ;
- sa date de création ;
- la période à laquelle il s’applique, si elle est connue ;
- le fait précédent qu’il remplace, le cas échéant.

Statuts initiaux :

- `declared` : déclaré par l’utilisateur ;
- `documented` : présent dans une pièce ;
- `contested` : contesté ;
- `superseded` : remplacé ;
- `assumption` : hypothèse explicitement utilisée ;
- `unknown` : information nécessaire non encore disponible.

### 5.2 Positions des parties

Les affirmations d’une RH, d’un salarié, d’un manager ou d’un conseil sont
stockées comme `party_statement`. Elles ne deviennent pas des faits établis ni
des règles juridiques.

### 5.3 Documents

Le dossier relie les documents joints ou retrouvés dans la bibliothèque avec :

- `document_id` ;
- `extraction_id` ;
- nom et rôle dans le dossier ;
- message d’introduction ;
- couverture de lecture : document complet ou passages ciblés ;
- version de fichier utilisée.

Une pièce ajoutée est reliée au dossier. L’extraction de faits intervient
seulement lorsqu’elle est lue pour une demande ou lorsque l’utilisateur demande
explicitement son intégration au dossier.

### 5.4 Questions et tâches

Types de tâches initiaux :

- `legal_analysis` ;
- `document_analysis` ;
- `calculation` ;
- `comparison` ;
- `drafting` ;
- `clarification` ;
- `synthesis`.

Chaque tâche contient :

- la question ou le livrable attendu ;
- les faits concernés ;
- les pièces nécessaires ;
- les sources juridiques demandées ;
- les recherches à exécuter ;
- les dépendances avec les autres tâches ;
- son état technique ;
- le message de résultat, s’il existe.

États techniques : `open`, `running`, `executed`, `blocked`, `cancelled` et
`technical_error`. `executed` signifie que les actions prévues ont été menées,
pas que la réponse est éditorialement satisfaisante.

### 5.5 Conclusions juridiques

Les conclusions d’AORIA sont stockées séparément sous le type `legal_finding`,
avec :

- la question traitée ;
- la version du dossier ;
- le message assistant qui contient la réponse originale ;
- les sources mobilisées ;
- les limites signalées dans la réponse.

Une ancienne réponse de l’assistant n’est jamais promue automatiquement comme
fait du dossier.

### 5.6 Calculs

Chaque calcul conserve :

- la formule ;
- la source de la formule ;
- les variables et leurs unités ;
- la provenance de chaque valeur ;
- les hypothèses ;
- le résultat ;
- la version du dossier utilisée ;
- les tâches dont il dépend.

Une correction d’un montant invalide techniquement les calculs dépendants, sans
les réécrire ni les relancer automatiquement. L’utilisateur décide de demander
un nouveau calcul.

## 6. Plan multi-questions et multi-tâches

Une demande complexe ne doit plus être ramenée à une phrase unique. Le
planificateur produit un delta de dossier et un graphe de tâches :

```json
{
  "case_delta": {
    "new_entries": [],
    "revisions": [],
    "contradictions": [],
    "document_links": []
  },
  "objective": "Calculer les droits liés au licenciement économique",
  "tasks": [
    {
      "id": "notification",
      "type": "legal_analysis",
      "question": "Déterminer la date et la régularité de la notification",
      "relevant_entry_ids": [],
      "depends_on": [],
      "search_queries": []
    },
    {
      "id": "prime",
      "type": "legal_analysis",
      "question": "Qualifier la prime et déterminer son traitement",
      "relevant_entry_ids": [],
      "depends_on": [],
      "search_queries": []
    },
    {
      "id": "reference_salary",
      "type": "calculation",
      "question": "Comparer les salaires de référence sur trois et douze mois",
      "relevant_entry_ids": [],
      "depends_on": ["prime"],
      "search_queries": []
    },
    {
      "id": "final_answer",
      "type": "synthesis",
      "question": "Présenter les droits et les limites du calcul",
      "relevant_entry_ids": [],
      "depends_on": ["notification", "prime", "reference_salary"],
      "search_queries": []
    }
  ]
}
```

Le schéma est strict et borné. Les limites d’actions et de recherches restent
possédées par l’application. Il n’existe ni boucle de réparation ni relance pour
obtenir un plan jugé meilleur.

## 7. Cycle de vie d’un tour de conversation

### 7.1 Réception

1. Vérifier l’utilisateur, l’organisation, le plan et le quota.
2. Vérifier les références documentaires et leurs versions.
3. Enregistrer le message utilisateur original et ses références.
4. Charger le dossier et sa version sous verrou transactionnel ou contrôle de
   version optimiste.

L’enregistrement du message avant les appels LLM permet de conserver la demande
même en cas d’erreur technique ultérieure.

### 7.2 Planification

Le planificateur reçoit :

- le message courant intégral ;
- le socle organisationnel courant ;
- l’instantané actif du dossier ;
- les questions ouvertes ;
- les pièces actives ;
- les messages récents nécessaires au dialogue.

Un seul appel produit le delta de dossier et les actions à exécuter. La sortie
brute est persistée dans `case_events` avant application.

### 7.3 Application du delta

L’application est déterministe :

- ajouter une entrée ;
- créer une nouvelle version ;
- relier deux entrées contradictoires ;
- relier une pièce ;
- créer une tâche et ses dépendances.

Le code ne complète pas les faits absents et ne choisit pas entre deux versions
contradictoires.

### 7.4 Exécution

Chaque tâche est exécutée selon son type :

| Type | Exécution |
|---|---|
| Analyse juridique | Recherche légale, conventionnelle et jurisprudentielle dédiée |
| Analyse documentaire | Lecture de la pièce ou recherche de passages dans la pièce |
| Calcul | Application d’une formule établie par les sources |
| Comparaison | Exécution et présentation de plusieurs scénarios |
| Rédaction | Utilisation des résultats des tâches dont elle dépend |
| Clarification | Question factuelle à l’utilisateur |
| Synthèse | Réunion des résultats exécutés, sans inventer les branches manquantes |

### 7.5 Génération finale

Le prompt final reçoit :

1. la demande originale ;
2. les faits pertinents et leur provenance ;
3. les questions à traiter ;
4. les résultats regroupés par tâche ;
5. les passages des pièces ;
6. les sources juridiques ;
7. les calculs et leurs hypothèses ;
8. les informations manquantes et erreurs techniques.

La sortie non vide du modèle est conservée et affichée intégralement.

### 7.6 Finalisation

- Enregistrer la réponse assistant et ses sources.
- Relier les tâches exécutées au message assistant.
- Enregistrer les conclusions comme `legal_finding`, séparées des faits.
- Incrémenter la version du dossier.
- Émettre l’événement SSE `chat_case_file_updated`.

### 7.7 Interruption ou erreur

- Le message et les faits déclarés restent enregistrés.
- Une tâche non terminée reste ouverte ou passe en `technical_error`.
- Un flux partiel reste affiché selon les règles actuelles.
- Une conclusion incomplète n’est pas promue comme fait.
- Aucune relance automatique ne cherche à corriger le contenu.

## 8. Utilisation du dossier dans le pipeline

### 8.1 Planification

Le dossier remplace la reconstruction fragile de toute la situation à partir
des six derniers messages. Une petite fenêtre récente reste utile pour le ton,
les anaphores et le fil immédiat.

### 8.2 Recherche juridique

Chaque sous-question reçoit uniquement les faits qui influencent la règle et
les filtres applicables : IDCC, statut, date, type de rupture, effectif ou
catégorie de document. Les faits ne sont pas concaténés sans distinction dans
toutes les requêtes vectorielles.

### 8.3 Lecture documentaire

Le dossier indique quelles pièces sont déjà connues, leur version, leur rôle et
leur couverture de lecture. Une réponse globale sur une pièce lue seulement par
passages continue de signaler cette limite.

### 8.4 Réponse finale

Le dossier apporte les faits ; les pièces apportent les preuves ; les sources
juridiques apportent les règles ; la demande courante détermine le livrable.

### 8.5 Productions dérivées

Courriers, notes, chronologies, tableaux de calcul et préparations d’entretien
réutilisent le même socle, sans demander à l’utilisateur de ressaisir les faits.

## 9. Interface utilisateur

### 9.1 Emplacement

Ajouter dans l’en-tête de la conversation un bouton :

```text
Dossier · 12 faits · 3 questions
```

- ordinateur : panneau latéral droit ;
- mobile : tiroir plein écran ;
- le chat reste la vue principale.

### 9.2 Rubriques

1. **Contexte organisationnel** : profil hérité et date d’actualisation.
2. **Synthèse** : objet et état technique du dossier.
3. **Chronologie** : événements datés et provenances.
4. **Faits** : faits actifs, contestés et remplacés.
5. **Questions et tâches** : ouvertes, exécutées ou bloquées.
6. **Pièces** : versions et couverture de lecture.
7. **Calculs** : formules, valeurs, hypothèses et résultats.
8. **Conclusions** : analyses reliées aux réponses et aux sources.

### 9.3 Actions utilisateur

L’utilisateur peut :

- confirmer un fait ;
- corriger sa valeur ;
- le contester ;
- l’archiver du dossier actif ;
- ouvrir son message ou sa pièce d’origine ;
- rouvrir ou abandonner une tâche ;
- apporter une précision.

Une correction ne réécrit jamais le message d’origine.

### 9.4 Notification

Après un tour, afficher une indication discrète :

```text
Dossier mis à jour : 3 faits ajoutés, 1 précision, 2 questions ouvertes.
```

Le détail n’interrompt pas la lecture de la réponse.

### 9.5 Informations internes

Le client ne voit pas le prompt système, les contrôles de sécurité, les
identifiants techniques, les raisonnements internes ou les traces détaillées de
classement. La sortie brute du planificateur et le delta technique sont visibles
dans l’inspection administrateur.

## 10. Modèle de données proposé

### 10.1 `case_files`

```text
id
conversation_id UNIQUE
version
status
created_at
updated_at
```

Le propriétaire et l’organisation sont dérivés de la conversation.

### 10.2 `case_entries`

```text
id
case_file_id
entry_type
key
label
value_text
value_json
status
valid_from
valid_to
source_kind
source_message_id
source_document_id
source_extraction_id
source_excerpt
supersedes_entry_id
created_by_user_id
created_at
updated_at
```

Types initiaux : `fact`, `party_statement`, `assumption`, `legal_finding`,
`calculation` et `deadline`.

### 10.3 `case_tasks`

```text
id
case_file_id
task_type
question
status
depends_on
relevant_entry_ids
required_document_ids
created_from_message_id
result_message_id
created_at
updated_at
```

Les collections peuvent commencer en JSONB avec validation stricte. Une table
relationnelle de dépendances pourra les remplacer si les usages de requêtage le
justifient.

### 10.4 `case_document_links`

```text
case_file_id
document_id
extraction_id
role
added_from_message_id
created_at
```

### 10.5 `case_events`

```text
id
case_file_id
case_version
event_type
source_message_id
actor_type
organisation_context_snapshot
raw_planner_output
structured_delta
technical_error
created_at
```

### 10.6 Intégrité et concurrence

- suppression en cascade avec la conversation ;
- références documentaires supprimées en `SET NULL` avec conservation du nom
  et de l’empreinte utile dans l’événement ;
- index sur dossier, statut, clé et provenance ;
- contrôle optimiste par `case_files.version` ou verrou PostgreSQL ;
- HTTP 409 si une correction vise une version devenue obsolète.

## 11. API

### 11.1 Lecture

```http
GET /conversations/{conversation_id}/case-file
```

Retourne le contexte hérité, les entrées, tâches, pièces, calculs et la version.

### 11.2 Correction versionnée

```http
POST /conversations/{conversation_id}/case-file/entries/{entry_id}/revisions
```

```json
{
  "operation": "correct",
  "value": "3963",
  "comment": "Montant corrigé depuis le bulletin de salaire",
  "expected_case_version": 6
}
```

Opérations initiales : `confirm`, `correct`, `contest` et `archive`.

### 11.3 Gestion d’une tâche

```http
POST /conversations/{conversation_id}/case-file/tasks/{task_id}/actions
```

Actions : rouvrir, abandonner ou demander explicitement une nouvelle analyse.
Une modification ne déclenche pas seule un appel LLM.

### 11.4 Événement SSE

```text
event: chat_case_file_updated
data: {
  "version": 7,
  "facts_added": 3,
  "facts_changed": 1,
  "tasks_added": 2
}
```

Le navigateur recharge le dossier via l’API dédiée.

## 12. Fichiers backend impactés

### 12.1 Nouveaux fichiers

- `backend/app/models/case_file.py`
- `backend/app/schemas/case_file.py`
- `backend/app/services/case_file_service.py`
- `backend/app/api/case_files.py`
- migration Alembic après `g6h7chatdocs01`
- tests unitaires et d’intégration dédiés

### 12.2 Fichiers à modifier

| Fichier | Modification |
|---|---|
| `backend/app/models/conversation.py` | Relations vers le dossier et cycle de persistance du tour |
| `backend/app/models/__init__.py` | Déclaration des nouveaux modèles |
| `backend/app/schemas/conversation.py` | Résumé du dossier et événements SSE |
| `backend/app/services/conversation_service.py` | Enregistrer le message avant les appels et gérer son état technique |
| `backend/app/api/conversations.py` | Charger, mettre à jour et transmettre le dossier |
| `backend/app/services/conversation_orchestrator.py` | Ajouter `case_delta` et le graphe multi-tâches au plan existant |
| `backend/app/rag/search_plan.py` | Produire des sous-plans juridiques par question |
| `backend/app/services/conversation_document_service.py` | Employer le dossier pour la continuité et la lecture ciblée |
| `backend/app/rag/agent.py` | Ajouter dossier et résultats par tâche au prompt final |
| `backend/app/api/admin_quality.py` | Inspecter version, delta et contexte organisationnel |
| `backend/app/services/data_retention_service.py` | Export et suppression RGPD |
| `backend/app/services/user_service.py` | Suppression des dossiers de l’utilisateur |
| `backend/app/services/organisation_service.py` | Suppression des dossiers de l’organisation |
| `backend/app/main.py` | Enregistrer le routeur |
| `backend/app/core/config.py` | Feature flag par organisation |

Le nouvel orchestrateur présent dans le dossier de travail doit rester l’unique
point de planification. Il ne faut pas créer un classifieur ou un second
planificateur concurrent.

## 13. Fichiers frontend impactés

### 13.1 Nouveaux composants

- `frontend/src/components/chat/case-file-panel.tsx`
- `case-file-summary.tsx`
- `case-facts.tsx`
- `case-timeline.tsx`
- `case-tasks.tsx`
- `case-documents.tsx`
- `case-calculations.tsx`
- `case-entry-editor.tsx`

### 13.2 Modifications

| Fichier | Modification |
|---|---|
| `frontend/src/types/api.ts` | Types du dossier |
| `frontend/src/lib/chat-api.ts` | Lecture, corrections et événement SSE |
| `frontend/src/components/chat/conversation.tsx` | Bouton, panneau et rafraîchissement |
| `frontend/src/components/chat/message-list.tsx` | Navigation vers un message de provenance |
| `frontend/src/components/chat/message-bubble.tsx` | Action « Voir dans le dossier » |
| Admin Quality | Deltas, version et contexte utilisé |

## 14. Sécurité, confidentialité et cycle de vie

- mêmes contrôles de propriété et d’appartenance que la conversation ;
- aucune donnée accessible depuis une autre organisation ;
- vérification de chaque `document_id` et `extraction_id` ;
- données du dossier et pièces traitées comme données non fiables en tant
  qu’instructions ;
- journalisation des corrections et changements importants ;
- inclusion dans l’export RGPD ;
- suppression physique avec le compte ou l’organisation ;
- conversation masquée : dossier masqué au même utilisateur ;
- aucune utilisation transversale entre conversations sans action explicite.

## 15. Conversations existantes

Ne pas générer silencieusement des dossiers pour tout l’historique de
production.

- nouvelles conversations : alimentation progressive dès le premier message ;
- anciennes conversations : bouton « Créer un dossier à partir de cette
  conversation » ;
- une extraction bornée, sans boucle de réparation ;
- si le volume dépasse la limite, demander à l’utilisateur de sélectionner les
  échanges ou pièces utiles ;
- conserver la sortie brute et signaler toute erreur structurée.

## 16. Tests

### 16.1 Unitaires

- application déterministe d’un delta ;
- ajout, correction, contestation et remplacement d’un fait ;
- contradiction ;
- provenance message et document ;
- dépendances entre tâches ;
- contexte organisationnel hérité et instantané ;
- validation technique stricte ;
- absence de réparation automatique ;
- conflit de version.

### 16.2 Intégration

- enrichissement sur plusieurs tours ;
- correction d’un montant ;
- évolution du profil organisationnel entre deux tours ;
- distinction tranche d’effectif/nombre exact ;
- ajout puis lecture d’une pièce ;
- tâche dépendante d’une qualification juridique ;
- erreur de recherche sans perte du dossier ;
- interruption du flux ;
- reprise de conversation ;
- cloisonnement entre organisations.

### 16.3 Suppression et export

- suppression utilisateur ;
- suppression organisation ;
- export RGPD ;
- masquage de conversation ;
- suppression d’un document déjà cité.

### 16.4 Frontend

- panneau ordinateur et mobile ;
- dossier vide et dossier volumineux ;
- correction d’un fait ;
- provenance ouvrable ;
- actualisation SSE ;
- conflit de version ;
- affichage du contexte hérité.

Les tests LLM vérifient les contrats techniques à partir de sorties brutes
contrôlées ou archivées. Ils ne deviennent pas un évaluateur éditorial
automatique des générations.

## 17. Coût et performance

### 17.1 Ce qui nécessite le LLM

Le LLM intervient pour proposer, à partir du nouveau message, des pièces et du
dossier existant :

- les faits ou précisions à ajouter ;
- les contradictions à conserver ;
- les questions et tâches demandées ;
- les dépendances entre tâches ;
- les recherches juridiques nécessaires.

Cette production doit être intégrée à l’appel du planificateur conversationnel
déjà exécuté pour préparer la recherche. Il ne faut pas ajouter un appel LLM
spécifique « mise à jour du dossier » puis un second appel « plan de recherche ».
Le même résultat structuré contient `case_delta` et `tasks`.

L’application du delta, son stockage, son affichage et sa version sont ensuite
déterministes et ne nécessitent aucun appel LLM.

### 17.2 Ce qui ne nécessite pas le LLM

Les opérations suivantes sont assurées par l’application et la base de données :

- charger le profil de l’organisation au début de la conversation ;
- afficher ou recharger le dossier ;
- relier une pièce explicitement ajoutée ;
- appliquer un delta techniquement valide ;
- enregistrer une correction manuelle de l’utilisateur ;
- conserver les versions et provenances ;
- signaler un conflit de version ;
- exécuter un calcul arithmétique dont la formule et les variables sont établies ;
- exporter ou supprimer le dossier.

Une correction depuis le panneau n’entraîne donc aucun coût LLM. Un nouvel appel
n’a lieu que si l’utilisateur demande ensuite une nouvelle analyse, un nouveau
calcul ou une nouvelle rédaction.

### 17.3 Impact marginal de l’alimentation du dossier

À nombre d’appels identique, l’impact propre au dossier vient surtout de :

- quelques tokens supplémentaires en entrée pour l’état structuré pertinent ;
- une sortie de planification plus riche ;
- quelques écritures PostgreSQL ;
- une lecture API supplémentaire lorsque le panneau est ouvert ou actualisé.

Les écritures et lectures PostgreSQL sont faibles devant les appels de modèle,
de recherche et de reranking. Le surcoût du planificateur doit néanmoins être
mesuré, car le schéma produit davantage de champs.

Une trace de production observée sur un dossier complexe indique environ
`0,0012 $` et quatre secondes pour le planificateur existant de cette question.
Cette mesure est un point de référence, pas une prévision du nouveau système.
Le coût et la latence supplémentaires doivent être mesurés sur le même jeu de
questions avant et après extension du schéma.

### 17.4 Coût réel des demandes complexes

Le principal surcoût ne vient pas du stockage du dossier, mais de l’exécution
correcte de toutes les questions qu’il révèle. Une demande qui contient trois
questions juridiques peut nécessiter davantage de recherches, de passages
rerankés et de contexte final qu’une question simple.

Ce coût correspond à un travail qui était auparavant omis. Il ne doit pas être
masqué en réduisant arbitrairement la demande à une seule question.

Pour limiter le temps mural sans retirer de tâche :

- exécuter en parallèle les recherches indépendantes ;
- mutualiser les embeddings identiques ;
- regrouper le reranking lorsque les contraintes de sources le permettent ;
- ne transmettre à chaque tâche que ses faits pertinents ;
- dédupliquer les sources avant la génération finale ;
- imposer un budget global explicite d’actions et de requêtes ;
- conserver les résultats déjà obtenus en cas d’erreur technique, sans inventer
  les branches manquantes.

### 17.5 Comportement attendu selon la demande

| Situation | Impact attendu |
|---|---|
| Ouverture du dossier | Lecture de base de données, aucun LLM |
| Initialisation avec le profil société | Lecture de données, aucun LLM |
| Question juridique simple | Un plan, une tâche, recherche comparable à l’existant |
| Situation détaillée à une seule question | Plan plus riche, même nombre d’appels principaux |
| Plusieurs questions indépendantes | Davantage de recherches, parallélisables |
| Calcul fondé sur une formule établie | Calcul applicatif, aucun LLM supplémentaire |
| Correction manuelle d’un fait | Écriture de base de données, aucun LLM |
| Nouvelle analyse après correction | Nouveau tour normal, donc coût normal d’une question |

### 17.6 Budgets et mesure

Le plan doit définir des plafonds techniques, par exemple :

- maximum de tâches par tour ;
- maximum de recherches juridiques au total ;
- maximum de recherches par tâche ;
- budget de contexte par tâche et pour la synthèse ;
- délai maximum par recherche et borne globale de préparation.

Ces plafonds sont des limites d’exécution, pas des validateurs de contenu. Si la
demande dépasse le budget, AORIA indique les tâches non exécutées et conserve le
plan brut ; elle ne prétend pas avoir traité l’ensemble.

Les mesures comparatives doivent séparer :

- coût et latence du planificateur ;
- embeddings ;
- recherche et reranking ;
- génération finale ;
- lecture et écriture du dossier ;
- nombre de tâches prévues et réellement exécutées.

## 18. Observabilité

Mesures techniques utiles :

- latence et coût du planificateur ;
- nombre de tâches produites et exécutées ;
- erreurs de schéma ;
- conflits de version ;
- volume moyen d’un dossier ;
- nombre de faits corrigés ou contestés par l’utilisateur ;
- recherches et pièces utilisées par tâche ;
- échecs de suppression ou d’export.

Ces mesures décrivent le fonctionnement. Elles ne notent pas automatiquement la
qualité sémantique des réponses.

## 19. Ordre d’intégration

### Lot 1 — Contrats et socle de données

**État au 23 septembre 2026 : implémenté localement.** Le socle comprend les
tables et modèles versionnés, l’initialisation transactionnelle des nouvelles
conversations, le rattrapage des conversations existantes, le contexte société
hérité en temps réel avec instantané initial, le contrôle d’accès, la lecture
`GET /api/v1/conversations/{id}/case-file`, l’export et l’effacement RGPD ainsi
que les tests associés. Il n’alimente encore aucun fait par LLM et ne modifie ni
le planificateur, ni la recherche, ni la réponse finale.

- figer le vocabulaire des entrées, tâches, statuts et événements ;
- créer migration, modèles et service ;
- intégrer droits d’accès, export et suppression ;
- ajouter le socle organisationnel hérité et les instantanés ;
- écrire les tests unitaires.

Aucun changement de réponse à ce stade.

### Lot 2 — Plan de dossier en observation

**État au 23 septembre 2026 : implémenté localement.** L’unique planificateur
conversationnel produit désormais, dans le même appel structuré, un
`case_delta` et des `case_tasks`. Chaque sortie brute est conservée intégralement
dans `case_events`, avec le delta typé, la version du dossier, le contexte
organisationnel et l’éventuelle erreur technique. Les propositions ne sont pas
appliquées aux entrées ou tâches actives et n’influencent pas la génération
finale. Admin Quality permet d’inspecter le brut et le structuré liés à une
réponse. Une sortie vide ou invalide n’est ni réparée ni relancée.

- étendre le schéma du planificateur existant ;
- produire `case_delta` et tâches ;
- enregistrer les sorties brutes sans modifier les réponses ;
- afficher les traces dans Admin Quality.

### Lot 3 — Alimentation progressive

**État au 23 septembre 2026 : implémenté localement.** Le message utilisateur
exact est désormais enregistré avant l’intention, la planification et la
génération : il reste donc disponible même si une étape technique ultérieure
échoue. Le dernier plan techniquement valide du tour est appliqué une seule
fois, dans une nouvelle version du dossier, sans nouvel appel LLM. Les ajouts,
révisions, contestations et archivages conservent les valeurs précédentes et
leur provenance ; aucun arbitrage sémantique automatique n’est effectué. Les
tâches reçoivent leurs dépendances et les identifiants réels des entrées, et
les pièces sont reliées à leur version d’extraction exacte. Un conflit de
version ou une erreur d’application est enregistré séparément comme erreur
technique, sans altérer ni remplacer la sortie brute du planificateur ni la
réponse destinée à l’utilisateur.

- enregistrer le message avant traitement ;
- appliquer les deltas techniquement valides ;
- gérer versions, corrections et contradictions ;
- relier les pièces et les tâches.

### Lot 4 — Interface en lecture

**État au 23 septembre 2026 : implémenté localement.** Le chat expose un bouton
« Dossier » ouvrant un panneau latéral adaptatif. Il présente la version du
dossier, le contexte société hérité, les entrées actives ou contestées, les
tâches, les pièces et l’historique des valeurs remplacées ou archivées. Chaque
entrée conserve son extrait source ; les provenances message ramènent à
l’échange exact et les provenances documentaires affichent le nom, la version
d’extraction, le périmètre de lecture et l’empreinte utilisée. Un événement SSE
`case_file_updated` est émis uniquement après l’application effective d’une
nouvelle version et recharge le panneau lorsqu’il est ouvert. L’interface reste
en lecture seule dans ce lot et rappelle explicitement à l’utilisateur de
vérifier les informations extraites.

- bouton et panneau Dossier ;
- contexte organisationnel, faits, chronologie, tâches et pièces ;
- provenance vers messages et documents ;
- événement SSE de mise à jour.

### Lot 5 — Corrections utilisateur

**État au 23 septembre 2026 : implémenté localement.** Chaque entrée active du
panneau propose désormais les actions confirmer, corriger, contester et
archiver. L’API applique ces décisions avec un contrôle optimiste sur la version
du dossier et renvoie HTTP 409 si le client travaille sur une version devenue
obsolète. Une correction crée une nouvelle entrée `confirmed`, conserve
l’ancienne en `superseded`, enregistre l’utilisateur et son commentaire comme
provenance, puis incrémente la version. Les autres décisions modifient le statut
et créent un événement d’audit sans réécrire le message ou la pièce d’origine.
Le panneau adopte immédiatement la réponse versionnée de l’API ; en cas
d’erreur, il affiche le message technique et recharge l’état courant. Les
entrées `confirmed` et `contested` font partie du contexte actif transmis au
planificateur dès le tour de conversation suivant. Aucune de ces actions ne
déclenche un appel LLM.

- confirmer, corriger, contester et archiver ;
- gérer les conflits de version ;
- employer les corrections dès le tour suivant.

### Lot 6 — Exécution multi-questions

**24 septembre 2026 — implémenté localement.** Chaque tâche peut référencer ses
actions juridiques. Les passages d’un même document issus de recherches différentes
sont conservés et regroupés par branche, avec la sous-question originale. La
génération reçoit le dossier courant, ses provenances, les résultats par question
et les tâches bloquées. Limites techniques : deux passages de planification, six
actions au total et trois recherches juridiques. Les tâches exécutées sont reliées
à la réponse terminée ; un flux interrompu ne marque pas la rédaction comme exécutée.

- plusieurs sous-plans juridiques ;
- résultats regroupés par tâche ;
- dépendances ;
- génération finale alimentée par toutes les branches exécutées.

C’est ce lot qui apporte le gain principal sur les demandes complexes.

### Lot 7 — Calculs et productions

**24 septembre 2026 — implémenté localement.** Les tâches de calcul portent une
expression arithmétique, des variables avec unités et clés de faits, la source de
la formule, des hypothèses et un scénario. L’exécuteur emploie Decimal (28 chiffres
significatifs), seulement +, -, *, / et des parenthèses, sans eval ni exécution de
code. Il conserve les paramètres et erreurs techniques, les résultats et la version
du dossier. Une correction, contestation ou archive d’un fait utilisé marque le
calcul comme périmé sans modifier son résultat historique. Les tâches de rédaction
consomment le même contexte de faits, sources et résultats. Si la formule dépend
d’une recherche nouvelle, le second passage borné reçoit les textes trouvés ; une
qualification juridique non établie ne devient pas automatiquement un calcul validé.
Le système vérifie les références et l’arithmétique, pas la justesse juridique de
la formule proposée : les hypothèses et sources restent à examiner par l’utilisateur.

- formules et valeurs traçables ;
- scénarios ;
- invalidation ciblée après correction ;
- courriers, notes et chronologies utilisant les résultats des tâches.

### Lot 8 — Activation progressive

**24 septembre 2026 — préparation locale terminée ; activation réelle en attente.**
`CASE_FILE_ENABLED=false` et `CASE_FILE_PILOT_ORGANISATION_IDS=[]` sont les valeurs
par défaut. Une liste JSON d’UUID active le dossier uniquement pour les organisations
pilotes ; le backend contrôle l’accès et expose la capacité au frontend. Les anciennes
conversations proposent une sélection explicite de messages utilisateur (20 maximum,
100 000 caractères cumulés) importés intégralement comme déclarations. Les imports
ne déclenchent aucun appel LLM et ne reconstituent pas automatiquement tout l’historique.
La trace conserve le nombre d’appels de planification, la durée de préparation et
les résultats d’exécution ; les appels restent suivis par la comptabilité existante.
Le choix des organisations pilotes, les mesures de coût/latence réelles et les contrôles
post-déploiement restent requis avant l’activation générale. Aucun déploiement n’est
déclaré réalisé par les tests locaux.

- feature flag pour les organisations internes ou pilotes ;
- contrôles de sécurité, latence, coûts et cycle de vie ;
- activation générale après validation des parcours ;
- initialisation explicite des anciennes conversations si demandée.

## 20. Critères de réussite

Le chantier est fonctionnel lorsque :

- un fait donné au premier tour reste disponible plusieurs échanges plus tard ;
- une correction ne supprime pas l’ancienne valeur ;
- l’utilisateur voit d’où vient chaque information ;
- plusieurs questions d’une même demande obtiennent des recherches distinctes ;
- une tâche de calcul attend la qualification juridique dont elle dépend ;
- une pièce partiellement lue est présentée comme telle ;
- une position de la RH n’est pas transformée en règle juridique ;
- une modification du profil de l’organisation est utilisée aux tours futurs
  sans réécrire les réponses passées ;
- le dossier disparaît avec les données auxquelles il appartient ;
- aucune sortie LLM non vide n’est réparée ou remplacée automatiquement.

## 21. Cible produit

La cible est un **chat au centre accompagné d’un dossier transparent sur le
côté** :

- le chat permet de raconter, préciser et demander ;
- le dossier conserve et organise ;
- les pièces établissent les éléments documentaires ;
- les sources juridiques fondent les règles ;
- les tâches structurent le travail ;
- les calculs appliquent les formules ;
- la réponse finale réunit ces éléments sans remplacer les contenus originaux.

## 22. Correctifs consécutifs à l’audit du 24 septembre 2026

### Calculs et tâches

- Les valeurs numériques extraites disposent de `numeric_value.number` et `unit`,
  conservées à côté du texte original et visibles dans le panneau.
- Une variable référencée est contrôlée contre l’entrée exacte : existence,
  unicité, état actif, valeur décimale et unité lorsqu’elle est structurée.
  Aucun nombre n’est extrait automatiquement d’un texte libre comme « 3 200 € ».
  Une valeur inexploitable entraîne une erreur distincte, sans réparation du plan.
- Les variables peuvent référencer `entry_id` ; les identifiants effectivement
  liés sont enregistrés dans la provenance du calcul.
- `replaces_task_id` permet au plan de reprendre explicitement une tâche ouverte
  avec une nouvelle version de travail. L’ancienne devient `superseded` ; le lien
  est conservé dans l’événement de delta. Pas de rapprochement par mots-clés.
- Les tâches ouvertes transmettent leurs dépendances, faits et pièces au tour suivant.
- L’API refuse les modifications directes d’un résultat calculé, comme l’interface.

### Exécution et finalisation

- Les lectures accumulent les résultats au lieu d’écraser ceux d’autres branches.
- Une erreur de recherche juridique ou un budget atteint est enregistré par action ;
  les résultats des autres branches restent disponibles pour une réponse partielle
  explicitant les limites. Une sortie de plan inexécutable demeure une erreur.
- Les groupes composés uniquement de recherches juridiques indépendantes peuvent
  être exécutés en parallèle, dans les limites de trois recherches/six actions.
  Le chat crée un agent de recherche distinct par branche : aucun plan mutable
  partagé entre branches. Les parcours dépendants restent séquentiels.
- Le prompt distingue la récupération des règles, les scénarios et l’arithmétique ;
  il décrit la continuation après recherche juridique et ne prétend plus fonctionner
  en observation seule.
- Les clarifications et générations terminées passent par la finalisation des tâches.
  Celle-ci contrôle la version du dossier et enregistre un événement d’audit.
  Un conflit ne relance pas le modèle et ne modifie pas la réponse déjà sauvegardée.
- Une analyse juridique terminée est référencée comme `legal_finding` avec message,
  version, tâches et références de sources, sans résumé ni appel LLM supplémentaire.
- Les interruptions sont des avertissements séparés et persistés dans la trace.
  Le texte généré demeure inchangé ; une sortie vide est une erreur technique.

### Transparence et interface

- Les provenances documentaires exactes sont transmises dans le dossier ; l’interface
  utilise la paire document/extraction, et non le seul document.
- Chaque nouvelle lecture conserve son périmètre dans l’événement de traitement ;
  le lien expose le périmètre de la lecture la plus récente.
- Les contradictions conservent une relation explicite vers l’entrée contestée.
- Historique technique paginé, accessible au propriétaire sans message assistant,
  avec sorties originales intégrales, erreurs et deltas ; chargement explicite.
- État technique, chronologie des éléments datés et accès aux analyses originales
  complètent les rubriques du panneau. Ils ne constituent pas une synthèse juridique
  générée ou une validation automatique des réponses.

### Activation et volume

- Hors activation du dossier : pas de création à l’ouverture d’une conversation,
  pas de champs de dossier dans le schéma du planificateur ni d’instructions associées,
  et au plus une recherche juridique par tour. La découverte documentaire demeure.
- Les réimports d’un même message historique ne dupliquent plus sa déclaration.
- La lecture courante du dossier ne charge plus toutes les observations brutes ni
  tous les messages de la conversation ; l’historique technique est chargé séparément.
- Les branches finales référencent les passages transmis dans le contexte RAG au lieu
  d’en dupliquer le texte. Les traces conservent les mesures techniques par branche.
- Un plafond explicite de 250 000 caractères sur les messages de planification
  provoque une erreur avant appel LLM, sans troncature ni résumé automatique. C’est
  une borne de sécurité grossière, pas une promesse de coût optimal pour toute taille
  de dossier. Une sélection de contexte plus fine reste à mesurer sur le pilote.

### Vérifications restant hors validation locale

Migration et concurrence sur PostgreSQL réel, rendu navigateur/mobile, scénarios
avec modèles réels, coûts/latences et déploiement pilote ne sont pas réputés validés
par les tests simulés. Aucun mécanisme d’évaluation éditoriale automatique n’est
ajouté au rendu.

## 23. Simplification du parcours local — 24 septembre 2026

Cette section remplace les décisions de génération et les deltas cumulatifs des
sections précédentes pour le parcours avec dossier activé. Aucun déploiement de
production n'est inclus.

### Contrat requests_v2

- Un appel propose deux contrats indépendants : `case_delta` et `requests`.
- Une seule liste de demandes : question, dépendances, faits utiles, opération
  éventuelle (recherche juridique, catalogue, lecture, passages, calcul) ou livrable.
- Aucune action `generate`/`respond` et aucun `needs_continuation` produit par le
  modèle. Le code enchaîne les outils puis la rédaction. Une lecture découverte ou
  un calcul nécessitant les sources peut déclencher un second passage, pas une
  relance destinée à réparer un plan.
- La compilation vers les représentations internes de l'exécuteur et des tables
  ne modifie pas le texte original. Le parcours sans dossier conserve son ancien
  contrat ; ce n'est jamais un fallback après une erreur du nouveau contrat.
- Le second passage reçoit les demandes précédentes conservées par le code et le
  dossier actualisé. Il ne régénère ni les faits inchangés ni tout le premier plan.
  La découverte/lecture de nouveaux fichiers n'est plus une capacité disponible
  dans son schéma. Sans nouveau contenu effectivement obtenu, aucun second appel
  de planification n'est lancé : la rédaction explique directement l'ambiguïté.

### Enregistrement et exécution

- Les faits dont le contrat technique est valide sont enregistrés avant la
  recherche. Une erreur indépendante de recherche ne les efface pas.
- Les erreurs de structure, références, versions ou droits restent explicites.
  Une demande invalide n'est pas réparée ; ses dépendantes ne sont pas exécutées.
  Les demandes indépendantes demeurent disponibles. La sortie brute intégrale et
  les erreurs sont accessibles dans l'historique technique du dossier.
- Les dates structurées sont de vraies dates ou horodatages. Une précision limitée
  au mois reste dans le texte du fait : aucun jour n'est inventé par le code.
- Les recherches indépendantes peuvent être parallèles même en présence d'autres
  types de consultations. Les livrables partagent leurs sources par dépendances.
- Une convention héritée du profil peut être déclarée non applicable/incertaine
  pour le cas ; elle n'est alors pas imposée comme filtre de cette recherche.
  Le profil de l'organisation n'est pas modifié.

### Contexte et présentation

- Conservation de tous les faits actifs/confirmés/contestés, sans résumé destructif
  ni sélection sémantique automatique. Suppression des champs techniques inutiles
  et de la répétition de la question dans les contextes.
- Le dossier reste un panneau par conversation. La réponse utilise des sections
  Markdown par question/livrable, sans réciter le dossier ni ses identifiants.
- Les paramètres de présentation sont dans le prompt. Aucun contrôle éditorial,
  score de qualité, réécriture, nettoyage ou relance corrective n'est ajouté.
- Les états de consultation (dont les candidats ambigus) sont transmis à la
  rédaction ; aucune pièce ambiguë n'est sélectionnée automatiquement.

### Mesures et limites

- Traces par appel : contrat, durée, taille du prompt/schéma/sortie, motif de fin.
  Les métriques par branche et l'attribution des coûts restent disponibles.
- Même modèle de planification (`gpt-5-mini`), effort `low` pour ce contrat au lieu
  de `minimal`, pour la compréhension des demandes multiples. Plafond de sortie
  8 000 tokens (incluant le raisonnement), pas une longueur demandée. Ce choix doit
  être mesuré : moins d'appels inutiles n'implique pas automatiquement moins de
  tokens ou une latence inférieure pour chaque cas.
- Pas de délai global interrompant une analyse active ; messages de patience.
  Le plafond réseau du planificateur reste de 300 secondes de silence, sans retry.
  Ce n'est pas un objectif de latence. Le flux final conserve son garde d'inactivité.
- Les tests simulés portent sur les contrats, la persistance, les dépendances,
  les accès et la conservation des sorties. Les essais réels sont séparés du rendu
  et ne constituent pas une certification de justesse juridique.
