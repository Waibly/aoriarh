# Corrections ciblées et essais de non-régression — 26 octobre 2026

## Décision

Conserver la correction du préfiltre qui empêchait une demande concrète de rédaction
d'atteindre la recherche juridique. Conserver également la correction technique du
streaming préparée pendant l'audit : en cas d'erreur de transport, restituer les fragments
déjà reçus avant de propager l'erreur, sans relance ni modification du contenu.

**Ne conserver aucune des deux variantes du prompt chronologique expérimentées ici.**
La comparaison manuelle a mis en évidence des comportements indésirables. Le fichier
`backend/app/rag/chronology.py` a retrouvé son contenu de référence. Aucun déploiement,
commit ou push n'a été effectué pour ce travail.

Cette étape ne valide pas une amélioration générale de la qualité juridique. Elle isole
deux corrections et documente pourquoi une modification plus large est écartée.

## Changements conservés

- Dans `intent_router.py`, une question autonome sur les compétences conserve sa réponse
  de présentation. Une demande comme « Es tu capable de rédiger un accord sur le temps
  de travail ? Nous souhaitons majorer les heures supplémentaires à 10 % » passe au
  planificateur avec son texte complet. Le motif précédent capturait aussi cette demande.
- Les demandes explicites de secrets restent prioritaires. Les tests ajoutent notamment
  les formulations à l'infinitif et un cas RH légitime évoquant une clé API.
- Dans `agent.py`, les fragments encore en tampon sont émis une seule fois avant la
  propagation d'une erreur de transport. Le test compare exactement les chaînes reçues
  et émises, espaces et sauts de ligne compris, avec plusieurs tailles de tampon.
- La matrice privée de comparaison et les tests HTTP comprennent désormais le cas de
  rédaction formulé comme une question de capacité : 21 cas de revue et 9 scénarios HTTP.

Les modèles, budgets de contexte et de sortie, paramètres de recherche et règles de
classement ne sont pas réduits pour obtenir un gain artificiel de temps ou de coût.
Aucun juge de génération, nettoyage, réparation ou relance sémantique n'est ajouté.

## Référence et provenance

La référence des comparaisons de prompts est le commit local `72ad715`. Il comprend déjà
la recherche par pertinence dans une période de jurisprudence (`decision_period`), issue
d'un travail distinct présent dans le dépôt pendant cette intervention. Ce mécanisme
différencie une question juridique portant sur une année d'une liste des derniers arrêts.
Il conserve les textes et conventions plus anciens et l'isolation entre organisations.
Les succès de ce mécanisme ne sont donc pas attribués aux prompts expérimentaux.

Les entrées sont reconstruites depuis les archives en lecture seule des dix conversations
de l'[audit de production](AUDIT_REPONSES_PRODUCTION_2026-10-26.md), complétées par trois
cas de dates. Ce ne sont pas les requêtes HTTP historiques exactes. Les corps envoyés aux
API sont archivés intégralement pour rendre les nouvelles expériences inspectables.

La première comparaison autorisée réutilisait un état de dossier après la réponse
historique. La seconde reconstruit l'état antérieur depuis le précédent tour disponible,
ou un dossier vide, avec l'historique récent au format réellement attendu. Ces deux
expériences ne constituent donc pas un seul échantillon homogène.

## Comparaisons avec le planificateur réel

Chaque expérience est fixée à 13 cas × 2 versions × 2 répétitions, soit 52 appels.
Les entrées sont identiques entre versions à l'exception du message système. Les appels
utilisent le même modèle et le même budget, sans relance automatique OpenAI. Toutes
les sorties sont conservées, y compris les sorties défectueuses. La revue est séparée
de l'application et ne conditionne aucun rendu utilisateur.

| Expérience | Résultat observé | Décision |
|---|---|---|
| Variante développée du prompt | Sur un essai C09, les clarifications remplacent le brouillon demandé. Des échappements NUL apparaissent aussi dans certaines sorties. | Écartée. |
| Variante minimale, quatre lignes ajoutées | C03 reste une recherche de règles applicables dans les deux versions. Sur C09, une répétition remplace la rédaction par une clarification et introduit des contrôles de documents fictifs. Sur C06, une répétition demande de lire cinq identifiants fictifs au lieu du catalogue des dernières décisions. | Écartée, modification retirée. |

Il n'est pas possible d'attribuer avec certitude chaque défaut au changement de prompt :
deux répétitions ne suffisent pas. Ces contre-exemples suffisent cependant à refuser de
présenter la variante comme validée. La référence présente elle aussi des défauts :
identifiants de documents inventés dans certains plans, et échappements NUL.

Au total, 104 réponses API de planification ont été obtenues dans ces deux expériences.
Cela ne signifie pas 104 plans exécutables ou corrects. Les sorties contenant des
échappements NUL sont archivées telles quelles : quatre dans la première expérience,
trois dans la seconde, réparties entre référence et variante. Ces caractères constituent
notamment une limite technique pour un stockage JSON PostgreSQL ; ils n'ont pas été
supprimés ni remplacés.

Une première tentative distincte avec la clé locale a reçu 52 erreurs
`insufficient_quota`, sans génération obtenue. Elle est exclue des résultats de qualité.
Les appels suivants utilisent les accès de production autorisés, uniquement en mémoire
du processus local. Aucune clé n'est enregistrée dans les artefacts.

## Recherche et génération réelles dans un environnement isolé

Six exécutions supplémentaires utilisent SQLite et Qdrant en mémoire, les composants
réels d'orchestration, de recherche hybride, d'expansion, de classement et de génération,
ainsi que les API réelles d'embedding, de reranking et de génération. Les plans sont
rejoués depuis leurs sorties brutes archivées, sans nouvel appel de planification.

Le corpus figé contient **84 points vectoriels de 13 documents communs** : arrêts
pertinents ou récents et passages du Code du travail. Il ne représente pas tout l'index
de production. Les métadonnées SQL locales sont reconstruites depuis les payloads du
corpus ; ce montage ne démontre pas l'exhaustivité du catalogue SQL de production.
Les écritures de dossiers et conversations restent dans SQLite, et les événements de
coût sont collectés localement. Aucun message ni coût applicatif n'est écrit en production.

| Cas | Observation manuelle | Portée |
|---|---|---|
| C02 — 31 h travaillées et 7 h de congés, jurisprudence 2025 | L'arrêt du 10 septembre 2025, n° 23-14.455, figure dans les huit groupes de sources transmis. La réponse distingue le décompte hebdomadaire et conclut à trois heures donnant droit à majoration. | Vérifie le chemin recherche → passage source → réponse sur ce corpus ; plan issu de la variante ensuite rejetée. |
| C03 — entretiens professionnels avant une échéance | Les deux versions transmettent L.6315-1 et produisent une checklist. Elles ne démontrent pas la maîtrise des dispositions transitoires absentes de ce corpus. | Pas de validation juridique exhaustive ; pas de gain causal démontré pour le prompt. |
| C06 — dernières décisions | Le plan expérimental demande des identifiants fictifs ; la consultation échoue et aucune source n'est transmise. La réponse signale cet échec. | Échec réel d'exécution du plan, pas un succès de recherche ; aucun correctif automatique du plan. |
| C09 — projet d'accord à 10 % | Avec un plan de la référence conservée, neuf groupes de sources sont transmis et un projet de 12 articles est produit, avec des champs à compléter et des questions sur le mode de conclusion. Sortie intégrale de 8 134 caractères. | Vérifie la production effective d'un brouillon ; ne certifie pas sa validité juridique ni tous les modes de négociation. |
| C05 — arrêt identifié absent | Avec un plan de la référence conservée, la réponse dit ne pouvoir fournir le texte ni l'analyse de la décision absente et distingue l'absence dans la sélection d'une absence de publication. | Abstention observée sur cet essai ; les autres sources ne sont pas présentées comme l'arrêt demandé. |

Les sorties longues de C07 n'ont pas fait l'objet d'une nouvelle génération complète.
La planification et les contrats de conservation du texte ont été testés ; cela ne vaut
pas validation d'un nouveau rapport d'enquête. Le défaut historique C08 de perte du
passage sur la grossesse était déjà corrigé avant cette intervention ; les tests
d'expansion et de conservation du passage pertinent restent dans la suite ciblée.

Les temps mesurés localement et les tailles de ces réponses ne sont pas des gains
avant/après en production. Le corpus, les caches et le réseau sont différents.
L'estimation calculée avec les tarifs inscrits dans le dépôt est d'environ **0,94 USD**
pour les 104 planifications réussies et les six exécutions RAG, embeddings et reranking
compris. C'est une estimation technique, sans prise en compte des remises de cache,
et non une facture fournisseur ni une estimation du coût futur par utilisateur.

## Vérification du code conservé

La commande ciblée réunit les tests du préfiltre, du routage de sécurité, des périodes
de décisions, des requêtes et de l'orchestrateur, des prompts de génération, des erreurs
de recherche et de streaming, de l'expansion des sources, du parcours documentaire et
des outils d'audit : **263 réussis, 1 ignoré**, en 69,53 secondes. Le test ignoré concerne
une capture payante explicitement optionnelle. Les neuf scénarios HTTP utilisent des
transports simulés ; ils vérifient les contrats, pas la qualité juridique du modèle.

Le contrôle `ruff --select F,I` porte sur les fichiers Python modifiés par l'audit.
`git diff --check` contrôle les changements locaux. Les avertissements de dépréciation
observés pendant pytest ne sont pas des échecs de ces tests.

## Preuves privées et limites restantes

Les dossiers `tmp/search-routing-20261026`,
`tmp/search-routing-20261026-authorized` et `tmp/search-routing-minimal-20261026`
contiennent les protocoles, entrées, requêtes, réponses complètes et erreurs. Ils sont
privés et ne doivent pas être versionnés avec les conversations de production. Le
dernier contient également la revue manuelle, la synthèse technique et un manifeste
d'intégrité des pièces. Les noms et informations des personnes ne sont pas reproduits ici.

Restent ouverts : la fidélité du plan aux livrables demandés, les références de documents
inventées, les sorties structurées contenant NUL, la couverture des dispositions
transitoires et l'exhaustivité du contexte utile. La réduction des gros contextes et le
remaniement global du prompt ne sont pas validés par cette étape. Ils nécessitent leurs
propres comparaisons avant d'être retenus. Aucun résultat ici ne garantit l'absence de
régression sur toutes les futures questions.
