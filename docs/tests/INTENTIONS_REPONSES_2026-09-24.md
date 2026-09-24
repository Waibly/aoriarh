# Intentions et rédaction — vérification locale du 24 septembre 2026

## Changements

- La demande originale gouverne le format de la réponse. Dans le parcours avec dossier, le format de la dernière branche de recherche ne gouverne plus toute la réponse.
- Chaque tâche juridique conserve son intention dans le contexte transmis à la rédaction. Le dossier apporte des faits, pas un plan supplémentaire à réciter.
- Les consignes distinguent question simple, vérifications, analyse et rédaction. Elles demandent de conserver les conditions juridiques utiles, sans imposer de longueur.
- Pour une correction de document, les consignes demandent de préserver les autres informations du document.
- Les six messages récents sélectionnés ne sont plus coupés à 2 000 caractères chacun dans le parcours avec dossier. Cela augmente parfois les tokens d'entrée, mais évite de perdre la fin du document à modifier. La fenêtre de sélection reste inchangée.
- La préparation reçoit des instructions plus précises sur les intentions et les références aux faits existants.

Terra reste chargé de la rédaction. Aucun appel supplémentaire, filtre éditorial, validateur sémantique, raccourcissement automatique ou relance corrective n'a été ajouté. Les sorties restent intégrales. La clarification des priorités des consignes s'appuie sur le skill OpenAI Docs et la [documentation officielle sur les prompts](https://developers.openai.com/api/docs/guides/prompting).

## Comparaison réelle

Le script `backend/scripts/compare_answer_intent.py` capture en lecture seule trois contextes locaux, puis compare les prompts avant modification et ceux de la version finale avec le même modèle, les mêmes sources et les mêmes données par cas. Le profil d'organisation est fixé identiquement dans les deux variantes ; il ne constitue pas une reconstitution exhaustive du profil historique.

Ces mesures portent uniquement sur la génération, pas sur le parcours complet. Un seul échantillon final par cas ne permet pas de conclure à une tendance de performance, notamment en raison de la variabilité du service et du cache.

| Cas | Avant | Version finale | Caractères avant → après |
| --- | ---: | ---: | ---: |
| Vérifications / checklist | 35,08 s | 46,22 s | 6 493 → 5 845 |
| Analyse + checklist + e-mail | 58,25 s | 59,81 s | 12 585 → 11 867 |
| Correction du salaire dans un e-mail | 13,26 s | 6,99 s | 2 712 → 2 743 |

Les sorties originales, entrées et métriques sont conservées localement dans `/tmp/aoriarh-intent-20260924-a`, hors dépôt. Ce répertoire temporaire contient des données de conversation et n'est pas un rapport public.

## Lecture manuelle, séparée du fonctionnement applicatif

- Checklist : réponse davantage centrée sur un tableau de contrôles/actions. Les contrôles conditionnels (absences, mi-carrière, fin de carrière) figurent dans la version finale. Elle reste assez longue et présente encore des répétitions.
- Cas multiple : les trois livrables demandés sont distingués. Les inconnues relatives à la convention collective et à la prime sont explicites. La longueur reste importante, cohérente avec plusieurs livrables ; elle n'est pas plafonnée.
- Correction d'e-mail : sortie limitée au mail demandé, salaire à 3 450 €, sans calcul ajouté. La conservation de l'historique intégral sélectionné améliore la reprise des demandes de pièces et des réserves du document.

Cette revue ne certifie pas l'exactitude juridique exhaustive des réponses. L'articulation des règles légales et conventionnelles reste notamment à examiner juridiquement.

## Limites et incidents observés

- Aucun gain global de vitesse démontré : la checklist finale est plus lente, le cas multiple est proche et la correction d'e-mail est plus rapide.
- Le planificateur final produit une checklist exécutable sans références à des faits inexistants, mais classe encore l'intention `factual_rule` au lieu de `procedure`. Il introduit aussi des périodicités dans sa requête. La classification n'est donc pas parfaitement résolue ; la rédaction doit rester guidée par la demande originale.
- Deux essais intermédiaires ont rencontré une erreur réseau `httpx.ReadError`. Ils ne sont pas comptés comme des succès rapides. Le premier a fait l'objet d'un nouvel essai technique explicitement lancé ; aucune politique de relance applicative n'a changé. Le script conserve désormais les erreurs et les sorties partielles sans les réparer.
- Les trois générations finales ont terminé sans erreur. Aucun test connecté à l'interface avec le compte utilisateur n'a été réalisé pendant cette vérification ; son mot de passe n'a pas été modifié.

## Vérifications techniques

Suite ciblée élargie : **129 tests réussis, 1 ignoré**, avec 6 avertissements de dépréciation existants. Elle couvre notamment dossier, demandes, orchestration, calculs, documents, traces, prompts, délais et parité du bac à sable administrateur.

Les tests vérifient notamment la conservation exacte de la sortie, du contexte du dossier et d'un ancien document dépassant 2 000 caractères, ainsi que les intentions distinctes des tâches. Ils ne notent pas la qualité éditoriale des générations et ne conditionnent pas leur affichage.
