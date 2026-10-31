"""Provider token details for observation and billing, never output control."""


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
    details = getattr(usage, "prompt_tokens_details", None)
    writes = (
        details.get("cache_write_tokens_details") if isinstance(details, dict)
        else getattr(details, "cache_write_tokens_details", None)
    )
    for field, name in (
        ("ttl_30m_tokens", "tokens_cache_write_30m"),
        ("ttl_12h_tokens", "tokens_cache_write_12h"),
    ):
        value = writes.get(field) if isinstance(writes, dict) else getattr(writes, field, None)
        if type(value) is int and value >= 0:
            result[name] = value
    return result
