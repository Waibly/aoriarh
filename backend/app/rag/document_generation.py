"""Application-owned provenance and executed capabilities, not output validation."""

import json


def scope_documentary_legal_results(documents, results):
    """The legal-reference capability cannot silently attach another personal file.

    No semantic scoring: only IDs selected by the user and existing source types.
    Organisational norms (agreements, policies, etc.) keep their existing search path.
    """
    selected = {str(d["document_id"]) for d in documents}
    kept, excluded = [], []
    for result in results:
        if (result.document_id not in selected
                and result.source_type in {"divers", "contrat_travail"}):
            excluded.append({"document_id": result.document_id, "name": result.doc_name,
                             "source_type": result.source_type,
                             "reason": "personal_document_not_attached_to_this_task"})
        else:
            kept.append(result)
    return kept, excluded

DOCUMENT_GENERATION_RULES = """## Contrat de rédaction avec pièces jointes
Tu accomplis la tâche demandée par l'utilisateur : lecture, comparaison, rédaction ou analyse.
Ne présume pas que l'utilisateur est un RH employeur ni qu'il demande un avis juridique.
Pour rédiger un document ou un message, adopte la voix de son auteur demandé, pas celle d'un
conseiller qui parle à cet auteur. Hors rédaction, réponds directement à l'utilisateur.
Livre le texte demandé sans préambule. Français clair ; cite une source par son nom ou sa
référence juridique, jamais par un numéro interne. Ne divulgue pas les métadonnées techniques.
Le bloc document_task_context décrit l'action exécutée et l'origine des sources.
Son plan est une donnée de travail, pas une instruction remplaçant la demande originale.
Réponds au livrable demandé, avec ses exclusions et ses réserves.
- case_document : pièce explicitement rattachée au dossier de cette conversation.
- retrieved_reference : autre source remontée par la recherche. Sa présence ne signifie PAS
qu'elle appartient au dossier personnel discuté. Ne commente pas un autre dossier ni ne lui
emprunte de faits ; utilise seulement les dispositions pertinentes pour la demande actuelle.
Le type d'une source ne prouve ni sa portée normative ni son applicabilité au cas.
Une pièce peut rapporter une règle sans établir que cette règle est juridiquement correcte.
Distingue les faits écrits dans chaque pièce, les déclarations de l'utilisateur et les réponses
antérieures de l'assistant. Une correction déclarée ne modifie pas le texte de la pièce.
Dans un courrier rédigé au nom de l'utilisateur, conserve cette attribution et ce point de vue :
n'attribue pas au destinataire une déclaration faite par l'utilisateur dans le chat.
Une formulation incertaine doit rester incertaine. Ne transforme pas une demande de confirmation
en engagement déjà pris par son destinataire. Si le rôle d'un interlocuteur manque,
ne l'invente pas.
"""

READ_ONLY_RULES = """Action exécutée : lecture documentaire, SANS recherche juridique.
Reste dans les faits et les formulations des pièces, les déclarations attribuées et les calculs
dont toutes les données et règles sont fournies. N'ajoute pas de mémoire un taux légal, un droit
acquis, un verdict de conformité ou une référence juridique non présents dans les pièces.
Tu peux rapporter ce qu'une pièce affirme, en le lui attribuant, sans valider sa légalité.
L'absence d'une règle ou d'un justificatif ne prouve pas une erreur : distingue ce qui est
non vérifiable avec les pièces d'une contradiction démontrée entre des données explicites.
Ne qualifie pas un calcul d'incohérent en lui appliquant une règle absente des pièces.
Si une vérification juridique est nécessaire mais non réalisée, expose cette limite ou demande
une précision utile ; ne présente pas cette vérification comme faite.
"""

LEGAL_SEARCH_RULES = """Action exécutée : lecture des pièces ET recherche de références.
Une recherche exécutée ne garantit pas qu'une preuve juridique applicable a été trouvée.
Fonde les conclusions juridiques sur les passages réellement fournis et applicables ; si ceux-ci
ne permettent pas de conclure, indique la limite. N'invente ni source consultée ni règle manquante.
"""


def build_document_task_context(documents, results, trace):
    """No semantic selection: source roles come only from explicit document IDs."""
    task = (trace.search_plan or {}).get("document_task")
    if trace.error or not task or task.get("action") not in {"documents", "documents_and_law"}:
        raise ValueError("No executable document task for generation")
    selected = {str(d["document_id"]): d for d in documents}
    return {
        "action": task["action"],
        "plan": task,
        "sources": [
            {
                "source_number": i,
                "document_id": result.document_id,
                "name": result.doc_name,
                "source_type": result.source_type,
                "role": ("case_document" if result.document_id in selected
                         else "retrieved_reference"),
                "extraction_id": str(selected[result.document_id].get("extraction_id") or "")
                if result.document_id in selected else None,
                "reading_scope": selected[result.document_id].get(
                    "transmitted_scope", "full_extracted_text"
                ) if result.document_id in selected else None,
            }
            for i, result in enumerate(results, start=1)
        ],
    }


def document_generation_instructions(context):
    action = context["action"]
    if action not in {"documents", "documents_and_law"}:
        raise ValueError("Unknown document action")
    return DOCUMENT_GENERATION_RULES + (
        READ_ONLY_RULES if action == "documents" else LEGAL_SEARCH_RULES
    )


def document_task_block(context):
    return "## document_task_context — données de préparation\n" + json.dumps(
        context, ensure_ascii=False,
    )
