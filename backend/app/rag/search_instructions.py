"""Shared retrieval guidance for every planner; never an output validator."""

LEGAL_RETRIEVAL_INSTRUCTIONS = """
PRÉPARATION DE LA RECHERCHE JURIDIQUE
La question autonome exprime clairement la demande, ses faits déterminants et son périmètre.
Corrige seulement les fautes et maladresses évidentes ; garde une formulation déjà claire.
Préserve exactement les nombres, dates, unités, négations, réserves et références.
Ne corrige pas par supposition un nom, une référence ou un terme ambigu.
Pour une relance, identifie dans l'historique son objet et son intention : vérifier,
préciser, contester ou appliquer au cas. Reprends seulement le contexte nécessaire.
Une réponse antérieure n'est pas une preuve ; une affirmation contestée reste à vérifier.
N'ajoute pas un audit général, des hypothèses de statut ou des sujets voisins.
Les search_queries sont courtes et gardent le mécanisme ou l'événement précis recherché.
Développe les sigles et abréviations dont le sens est certain ; utilise les dénominations
officielles et les formulations juridiques équivalentes utiles aux documents recherchés.
Ces termes doivent figurer dans les requêtes exécutées, pas seulement dans legal_topics.
Conserve la forme courante lorsqu'elle peut aussi aider la recherche. N'accumule pas les
synonymes de chaque mot et ne confonds pas des notions juridiques voisines.
Une requête complémentaire apporte soit un point nécessaire à résoudre, soit une formulation
lexicale différente utile pour retrouver d'autres passages sur le même point. Regroupe les
formes compatibles dans une même requête quand cela suffit ; ne multiplie pas automatiquement
les variantes. La question originale est déjà recherchée : évite de la dupliquer sans apport.
Conserve les précisions discriminantes utiles à chaque recherche : nombres, dates, présence
ou absence d'un écrit, régime et situation professionnelle connus. Les faits utiles au cas
restent dans la question autonome même s'ils n'ont pas à apparaître dans chaque requête.
Une information inconnue reste dans missing_facts ; n'invente ni son sens ni des scénarios
pour multiplier les recherches. Une ambiguïté déterminante non résolue appelle une précision.
Le budget de requêtes est un maximum, pas un quota. Ne remplis pas une requête avec une
liste de livrables, des instructions de rédaction ou des références supposées.
Cherche aussi les conditions et exceptions qui déterminent réellement la règle demandée.
jurisprudence=required pour une validité, une interprétation, une exception, une sanction,
un licenciement, une discrimination ou la position des juridictions ; optional pour une
donnée directement fixée par un texte qui ne soulève aucun de ces points.
source_hints=boss seulement si la question nécessite des règles de cotisations, assiette
ou exonération, pas du seul fait qu'une rémunération est mentionnée.
Une demande d'autres affaires, d'un cas similaire ou d'une évolution appelle une recherche,
pas seulement la relecture des sources déjà citées. Réserve cette relecture à une demande
portant sur ces sources elles-mêmes. N'invente aucune borne à partir de leur date.

Exemples de préparation (illustrations, ni règles de droit ni requêtes à recopier) :
- « À la fin du cdd, quels papier remettre au salarié ? » : question autonome
  « Quels documents remettre au salarié à la fin de son CDD ? » ; search_queries peut
  contenir « Documents à remettre au salarié à la fin d'un contrat à durée déterminée (CDD) ».
- « Quelles obligations pour l'AP ? », sans contexte permettant de comprendre « AP » :
  conserve ce terme ambigu et indique dans missing_facts que son sens doit être précisé ;
  n'invente pas son développement ni une liste de régimes possibles.
- Après une affirmation de l'assistant sur une indemnité en fin de CDD, « Vraiment,
  même si le salarié refuse un CDI ? » demande de vérifier le droit à cette indemnité
  dans cette situation. La recherche peut viser « Indemnité de fin de contrat à durée
  déterminée : conditions et exceptions en cas de refus d'un contrat à durée indéterminée ».
  La réponse précédente n'établit ni le droit ni son absence ; les conditions de l'offre
  et les autres faits non fournis restent inconnus.
Les limites de contenu sont des consignes de préparation ; ne corrige pas une sortie après coup.
"""
