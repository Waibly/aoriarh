from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class QuotaStatus(StrEnum):
    OK = "ok"
    SOFT_WARNING = "soft_warning"   # >= 80 % of monthly quota
    HARD_WARNING = "hard_warning"   # >= 120 % — triggers upsell email
    TRIAL_EXPIRED = "trial_expired"
    SUSPENDED = "suspended"


# Thresholds for the "fair use" policy. Kept here rather than in plans.py
# because they are implementation details of the quota enforcement, not
# business parameters of the commercial offer.
SOFT_WARNING_RATIO = 0.80
HARD_WARNING_RATIO = 1.20


@dataclass
class QuotaInfo:
    status: QuotaStatus
    used: int
    quota: int
    remaining: int
    period_start: date
    period_end: date
    booster_remaining: int = 0
