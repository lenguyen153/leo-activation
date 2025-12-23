
from abc import ABC, abstractmethod
from typing import Any, Dict


class NotificationChannel(ABC):
    """Base strategy for all activation channels."""

    @abstractmethod
    def send(self, recipient_segment: str, message: str, **kwargs: Any) -> Dict[str, Any]:
        """Send a message to a recipient segment.

        Returns a dict with at least a `status` key.
        """
        pass
    
    
# Channel alias map to support short names and common variants
CHANNEL_ALIASES = {
    # Zalo variants
    "zalo": "zalo_oa",
    "zalo_oa": "zalo_oa",
    "zalo_push": "zalo_oa",
    "zalooa": "zalo_oa",

    # Facebook variants
    "facebook": "facebook_page",
    "facebook_page": "facebook_page",
    "facebookpage": "facebook_page",
    "facebook_push": "facebook_page",
    "fb": "facebook_page",
    "fb_page": "facebook_page",

    # Email variants
    "email": "email",
    "email_channel": "email",
    
    # Push Notification variants
    "mobile_push": "mobile_push",
    "mobile_notification": "mobile_push",
    "web_push": "web_push",
    "web_notification": "web_push",
}


def normalize_channel_key(key: str) -> str:
    """Normalize incoming channel names to canonical keys.

    Handles common variants with spaces, hyphens, and compact forms (e.g. "Zalo OA", "zalo-oa", "ZaloOA").
    Returns either a canonical channel key (e.g. "zalo_oa"), or a normalized string the caller can use to look up mappings.
    """
    if not key or not isinstance(key, str):
        return ""
    raw = key.lower().strip()

    # Direct alias mapping if present
    mapped = CHANNEL_ALIASES.get(raw)
    if mapped:
        return mapped

    # Try common variants
    variants = {
        raw.replace(" ", "_"),
        raw.replace(" ", ""),
        raw.replace("-", "_"),
        raw.replace("-", ""),
        raw.replace(" ", "_").replace("-", "_"),
    }

    for v in variants:
        mapped = CHANNEL_ALIASES.get(v)
        if mapped:
            return mapped
        # If variant is itself a canonical channel key (e.g. "zalo_oa"), return it
        if v in ActivationManager._channels:
            return v

    # Fallback: strip non-alphanumeric to compact form ("zalooa", "facebookpage")
    import re
    compact = re.sub(r"[^a-z0-9]", "", raw)
    mapped = CHANNEL_ALIASES.get(compact)
    if mapped:
        return mapped

    # Nothing matched — return the lowercased raw to let callers apply additional heuristics
    return raw


