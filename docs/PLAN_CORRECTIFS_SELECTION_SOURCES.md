# Plan de correctifs — Sélection des sources (chat + recherche documentaire)

Issu de l'audit du pipeline question → sources (juin 2026), affiné sur les 188 traces RAG de prod.
Trois correctifs, par ordre de priorité. Aucun déploiement sans validation explicite.

---

## Correctif 1 — Filtre d'intention de source (bug de rappel)

**Constat prod** : 5 questions / 188 (~3 %) ont fini avec un pool de candidats vide parce qu'un mot
comme « ccn » ou « contrat de travail » a restreint la recherche à un seul type de document
(`source_intent.py`). Le fallback actuel (boucle de re-recherche post-rerank dans `agent.py`)
renvoie alors des chunks bruts : sans rerank, sans expansion parent — jusqu'à 15 cartes
de jurisprudence non triées pour une question qui portait sur la CCN.

### 1a. Resserrer les déclencheurs (`backend/app/rag/source_intent.py`)

Ne déclencher le filtre que sur une question *dirigée vers la source*, pas sur une simple mention :

- Exiger un motif interrogatif/directif à proximité du nom de source :
  `(que (dit|prévoit|précise|indique)|selon|d'après|dans)\s+(la|ma|notre|votre)\s*(ccn|convention collective|règlement intérieur|contrat|accord d'entreprise…)`
- Supprimer les déclencheurs « mention nue » : `le contrat`, `la convention`, `contrat de travail`,
  `ccn` isolé.
- Conserver les déclencheurs déjà sûrs (« que dit le code du travail », « notre règlement intérieur
  prévoit-il »…).

Cas de test (faux positifs avérés en prod → ne doivent PLUS déclencher) :
- « Si l'employeur a une ccn il faut la prendre en compte dans le calcul des indemnités »
- « Comment préparer une rupture du contrat de travail pour limiter les risques prud'homaux »
- « La convention de forfait doit-elle être écrite ? »

Cas qui doivent continuer à déclencher :
- « Que dit la CCN sur les congés d'ancienneté ? »
- « Que prévoit notre règlement intérieur sur les retards ? »
- « Selon ma convention collective, quel préavis ? »

### 1b. Filet de sécurité : retry complet sans filtre

Dans `_search_with_expansion` (`agent.py`) : si la recherche **filtrée** par intention retourne un
pool vide (ou < 3 candidats), relancer immédiatement la même recherche **sans filtre**
(plancher législation réactivé), AVANT le rerank. Le pipeline qualité complet s'applique alors
normalement.

### 1c. Assainir la boucle de re-recherche existante

La boucle `while len(results) < 2` post-rerank injecte des chunks bruts dans le contexte et les
sources. Deux options (choisir à l'implémentation) :
- la supprimer (1b la rend quasi inutile), ou
- faire repasser ses résultats par rerank + expansion parent avant usage.

**Tests** : unitaires sur `detect_source_intent` (listes ci-dessus) + rejeu des 5 questions prod à
pool vide → vérifier pool non vide, sources mixtes (loi + jurisprudence + CCN si installée).

**Impact attendu** : plus aucune réponse avec sources en vrac sur ces formulations ; rappel restauré
(Code du travail + jurisprudence de nouveau interrogés).

---

## Correctif 2 — Plancher de pertinence sur les sources

**Constat prod** : 9,5 groupes servis en moyenne (cap 10 saturé), 8,3 cartes affichées ;
52 % des groupes ont un score rerank < 0,5, 30 % < 0,4, 10 % < 0,3. Un seuil relatif
(50 % du top) ne couperait que 4 % → il faut un **plancher absolu**.

### 2a. Calibration préalable sur les traces prod (lecture seule)

Script de rejeu : pour chaque trace (`messages.rag_trace->parent_groups`), simuler les seuils
0,30 / 0,35 / 0,40 et sortir un CSV : question, sources qui auraient été coupées (nom, type, score).
Validation humaine (David/Vanessa) : si rien d'utile dans la liste coupée → seuil retenu.

### 2b. Implémentation (`agent.py` + `rag/config.py`)

- Nouveau réglage `SOURCE_SCORE_FLOOR` (valeur issue de 2a, défaut pressenti 0,35).
- Filtrage appliqué **après l'expansion parent, avant le boost cross-référence** (pour filtrer sur
  le score rerank propre, pas sur le score gonflé ×1,05).
- Garde-fous :
  - toujours conserver au moins 3 groupes (les mieux notés), même sous le plancher ;
  - conserver la règle `min_legislation=2` existante ;
  - aucun changement au chemin d'injection par identifiant (article/pourvoi cité par l'utilisateur).
- S'applique mécaniquement au chat ET à la recherche documentaire (même `prepare_context`).
- Traçabilité : ajouter `groups_dropped` (liste compacte nom+score) au `RagTrace` pour suivre
  l'effet en prod sur la page Qualité.

**Tests** : unitaires (plancher, min 3, min_legislation) + rejeu 2a comme non-régression.

**Impact attendu** : ~30 % de cartes sources en moins (la traîne faible), contexte de génération
réduit d'autant → baisse directe du coût gpt-5.2 et de la latence de génération (18,9 s en moyenne
aujourd'hui, principal poste des 25 s totales).

---

## Correctif 3 — Exposer la date des textes au LLM

**Constat** : le prompt impose la règle de récence (« l'avenant 2021 remplace l'avenant 2017 »)
mais `_build_context` ne transmet pas `content_date` pour les textes non-jurisprudence.
Le modèle devine la date à partir du nom du document.

### Implémentation (`agent.py::_build_context`)

- Ajouter une ligne `Date du texte : <content_date>` dans l'en-tête de chaque source quand le champ
  est présent (la jurisprudence a déjà sa date via `date_decision`).
- Vérifier au préalable le taux de remplissage de `content_date` dans les payloads Qdrant
  (CCN/avenants KALI notamment). S'il est faible, le noter : le correctif reste sans risque mais
  le gain dépend de la couverture.

**Tests** : snapshot du contexte construit avec/sans date.

**Impact attendu** : moins de risque de citer une valeur périmée (grilles, primes, préavis d'avenants
successifs).

---

## Ordre d'exécution et déploiement

1. Correctif 1 (bug) → 2a calibration → validation humaine du CSV → 2b → 3.
2. Trois commits séparés, même branche. Vérification runtime locale avant tout déploiement :
   poser les questions piège + 3-4 questions standard, inspecter les traces.
3. Déploiement prod : uniquement sur accord explicite (règle projet).
4. Mesure post-déploiement (page Qualité / traces) :
   - 0 pool vide sur les formulations piège ;
   - nb moyen de groupes servis (attendu : ~6-7 au lieu de 9,5) ;
   - latence génération et totale (attendu : baisse sensible du p50 de 24,8 s) ;
   - aucun signalement de source utile manquante.

## Hors périmètre (backlog, après mesure des correctifs)

- Latence de l'étape expansion (~4,3 s) : chrono séparé expansion vs recherche, puis optimisation.
- `seed_text` généralisé aux groupes non-jurisprudence + fusion des fenêtres qui se chevauchent
  (extraits de cartes en recherche documentaire).
- Dédup des variantes identiques avant recherche (économie marginale Voyage/Qdrant).
- Appels Qdrant async / scrolls parallèles (gain ~0,5-0,7 s, surtout utile sous charge).
