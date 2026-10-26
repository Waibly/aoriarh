"""Prepare strict generation schemas; never modify a received model response."""


def strict_planner_schema(value):
    if isinstance(value, dict):
        value.pop("default", None)
        if value.get("type") == "object":
            value["additionalProperties"] = False
            value["required"] = list(value.get("properties", {}))
        for item in value.values():
            strict_planner_schema(item)
    elif isinstance(value, list):
        for item in value:
            strict_planner_schema(item)
    return value
