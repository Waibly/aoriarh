"""Technical stream errors, independent of generated content."""

from openai import RateLimitError


def stream_error_payload(error: Exception) -> dict[str, str]:
    if isinstance(error, RateLimitError):
        if (
            error.code in {"insufficient_quota", "credit_balance_exhausted"}
            or error.type == "insufficient_quota"
        ):
            return {
                "error": "provider_quota_exhausted",
                "message": "Le service IA est indisponible : "
                "le compte API configuré n’a plus de crédits. "
                "Un administrateur doit le recharger pour rétablir les réponses. "
                "Votre question est conservée.",
            }
        return {
            "error": "provider_rate_limited",
            "message": "Le service IA reçoit trop de demandes. Réessayez dans quelques instants. "
            "Votre question est conservée.",
        }
    return {
        "error": "server_error",
        "message": "Une erreur est survenue lors du traitement de votre question. "
        "Votre question est conservée. Vous pouvez réessayer.",
    }
