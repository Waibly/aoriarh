"""Search limitations displayed separately from the untouched LLM output."""


def search_feedback(trace: dict | object | None) -> dict:
    if trace is not None and not isinstance(trace, dict):
        # Feedback must not depend on serializing the full diagnostic trace.
        trace = {
            "search_plan": getattr(trace, "search_plan", None),
            "search_plan_validation": getattr(trace, "search_plan_validation", None),
            "router_raw_response": getattr(trace, "router_raw_response", None),
            "error": getattr(trace, "error", None),
        }
    plan = (trace or {}).get("search_plan") or {}
    validation = (trace or {}).get("search_plan_validation") or {}
    warnings = []
    if plan.get("planner_status") in {"error", "fallback"}:
        warnings.append("Le plan de recherche n’a pas pu être exécuté ; aucune recherche de secours n’a été lancée.")
    if (plan.get("time_scope") or {}).get("kind") == "application_year":
        warnings.append("La disponibilité de la version historique demandée reste à vérifier.")
    if "ambiguous_time_scope" in plan.get("warnings", []):
        warnings.append(
            "La période de recherche est ambiguë ; aucun filtre de date n'a été imposé."
        )
    if validation.get("missing_requested_source_types"):
        warnings.append(
            "Certaines sources demandées n'ont pas été retrouvées ; les compléments ne les remplacent pas."
        )
    if any(b.get("status") == "error" for b in validation.get("branches", [])):
        warnings.append(
            "Une partie des recherches a échoué. Les résultats disponibles ont été conservés."
        )
    if validation.get("contract_identity_unresolved"):
        warnings.append("Le contrat personnel concerné n'est pas identifié par cette recherche.")
    if any(branch.get("status") == "error" for branch in validation.get("branches", [])) or (trace or {}).get("error") == "search_retrieval_error":
        warnings.append("Une recherche documentaire a échoué ; la récupération des sources est incomplète.")
    selection = validation.get("selection") or {}
    if selection.get("status") == "error":
        warnings.append("La sélection documentaire a échoué ; aucun classement de secours n’a été utilisé.")
    groups = selection.get("groups", [])
    if selection.get("excluded_by_publication_period"):
        warnings.append("Des résultats sans date vérifiable ou hors de la période de publication demandée ont été écartés, sans recherche de remplacement.")
    if any(g.get("fetch_limited") for g in groups):
        warnings.append("La récupération des passages voisins a atteint sa limite technique. Les passages sélectionnés sont conservés.")
    if any(g.get("omitted_indices") for g in groups):
        warnings.append("Le contexte contient une sélection de passages, pas nécessairement les documents complets.")
    return {
        "raw_response": plan.get("planner_raw_response"),
        "warnings": warnings,
        "router_raw_response": (trace or {}).get("router_raw_response"),
    }
