"""Shared retrieval guidance for every planner; never an output validator."""

LEGAL_RETRIEVAL_INSTRUCTIONS = """
PRÉPARATION DE LA RECHERCHE JURIDIQUE
La question autonome conserve la demande, ses faits déterminants et son périmètre.
Si elle est déjà autonome, recopie-la exactement ; pour une relance, résous seulement
les références nécessaires avec l'historique. Une réponse antérieure n'est pas une preuve.
N'ajoute pas un audit général, des hypothèses de statut ou des sujets voisins.
Les requêtes complémentaires sont courtes, en vocabulaire juridique, et couvrent des
angles distincts réellement nécessaires. Conserve les précisions discriminantes : nombres,
dates, présence ou absence d'un écrit, régime et situation professionnelle connus.
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
Les limites de contenu sont des consignes de préparation ; ne corrige pas une sortie après coup.
"""
