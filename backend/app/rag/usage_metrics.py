"""Optional provider usage details, for observation only (never output control)."""


def usage_details(usage) -> dict[str, int]:
    result = {}
    for attribute, field, name in (
        ("prompt_tokens_details", "cached_tokens", "tokens_cached"),
        ("prompt_tokens_details", "cache_write_tokens", "tokens_cache_write"),
        ("completion_tokens_details", "reasoning_tokens", "tokens_reasoning"),
    ):
        details = getattr(usage, attribute, None)
        value = details.get(field) if isinstance(details, dict) else getattr(details, field, None)
        if type(value) is int and value >= 0:
            result[name] = value
    return result
