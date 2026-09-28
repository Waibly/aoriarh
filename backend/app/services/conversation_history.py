"""Preserve source references in the already-authorised conversation history."""


def planner_history(messages):
    history = []
    for message in messages:
        item = {
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
        }
        coverage = (message.rag_trace or {}).get("search_plan_validation", {}).get("chronology")
        if coverage:
            item["chronology"] = coverage
        if message.role == "assistant" and message.sources:
            item["sources"] = [
                {
                    key: source[key]
                    for key in ("document_id", "document_name", "source_type")
                    if key in source
                }
                for source in message.sources
                if isinstance(source, dict)
            ]
        history.append(item)
    return history
