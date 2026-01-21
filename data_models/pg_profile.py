from psycopg.types.json import Json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
import re


_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


class PGProfileUpsert(BaseModel):
    # =====================================================
    # MULTI-TENANCY
    # =====================================================
    tenant_id: str

    # =====================================================
    # CORE IDENTITY
    # =====================================================
    profile_id: str
    identities: List[str] = Field(default_factory=list)

    # =====================================================
    # CONTACT INFORMATION
    # =====================================================
    primary_email: Optional[EmailStr] = None
    secondary_emails: List[EmailStr] = Field(default_factory=list)

    primary_phone: Optional[str] = None
    secondary_phones: List[str] = Field(default_factory=list)

    # =====================================================
    # PERSONAL & LOCATION
    # =====================================================
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    living_location: Optional[str] = None
    living_country: Optional[str] = None
    living_city: Optional[str] = None

    # =====================================================
    # ENRICHMENT & INTEREST SIGNALS
    # =====================================================
    job_titles: List[str] = Field(default_factory=list)
    data_labels: List[str] = Field(default_factory=list)
    content_keywords: List[str] = Field(default_factory=list)
    media_channels: List[str] = Field(default_factory=list)
    behavioral_events: List[str] = Field(default_factory=list)

    # =====================================================
    # SEGMENTATION & JOURNEYS
    # =====================================================
    segments: List[Dict[str, Any]] = Field(default_factory=list)
    journey_maps: List[Dict[str, Any]] = Field(default_factory=list)

    # =====================================================
    # STATISTICS & TOUCHPOINTS
    # =====================================================
    event_statistics: Dict[str, int] = Field(default_factory=dict)
    top_engaged_touchpoints: List[Dict[str, Any]] = Field(default_factory=list)

    # =====================================================
    # EXTENSIBILITY
    # =====================================================
    ext_data: Dict[str, Any] = Field(default_factory=dict)

    # =====================================================
    # VALIDATORS (FAIL-SOFT, NEVER BLOCK SYNC)
    # =====================================================

    @field_validator("primary_email", mode="before")
    @classmethod
    def normalize_primary_email(cls, v):
        """
        If email is invalid, silently drop it (set NULL).
        """
        if not v:
            return None
        try:
            return EmailStr(v)
        except Exception:
            return None

    @field_validator("secondary_emails", mode="before")
    @classmethod
    def normalize_secondary_emails(cls, v):
        """
        Keep only valid emails.
        """
        if not v:
            return []
        valid: List[str] = []
        for e in v:
            try:
                valid.append(str(EmailStr(e)))
            except Exception:
                continue
        return valid

    @field_validator("primary_phone", mode="before")
    @classmethod
    def normalize_primary_phone(cls, v):
        """
        If phone is invalid, silently drop it (set NULL).
        """
        if not v:
            return None
        v = v.strip()
        if _PHONE_RE.match(v):
            return v
        return None

    @field_validator("secondary_phones", mode="before")
    @classmethod
    def normalize_secondary_phones(cls, v):
        """
        Keep only valid phone numbers.
        """
        if not v:
            return []
        return [p for p in v if isinstance(p, str) and _PHONE_RE.match(p.strip())]

    # =====================================================
    # SERIALIZATION FOR POSTGRES
    # =====================================================
    def to_pg_row(self) -> Dict[str, Any]:
        """
        Convert the profile into a dict compatible with psycopg
        and the cdp_profiles INSERT / UPSERT statement.

        Guarantees:
        - Invalid emails / phones become NULL
        - JSON-like fields are wrapped with Json
        - AI / portfolio fields are untouched
        """
        return {
            "tenant_id": self.tenant_id,
            "profile_id": self.profile_id,

            # identity
            "identities": Json(self.identities),

            # contact
            "primary_email": self.primary_email,
            "secondary_emails": Json(self.secondary_emails),
            "primary_phone": self.primary_phone,
            "secondary_phones": Json(self.secondary_phones),

            # personal & location
            "first_name": self.first_name,
            "last_name": self.last_name,
            "living_location": self.living_location,
            "living_country": self.living_country,
            "living_city": self.living_city,

            # enrichment
            "job_titles": Json(self.job_titles),
            "data_labels": Json(self.data_labels),
            "content_keywords": Json(self.content_keywords),
            "media_channels": Json(self.media_channels),
            "behavioral_events": Json(self.behavioral_events),

            # segmentation & journeys
            "segments": Json(self.segments),
            "journey_maps": Json(self.journey_maps),

            # statistics & touchpoints
            "event_statistics": Json(self.event_statistics),
            "top_engaged_touchpoints": Json(self.top_engaged_touchpoints),

            # extensibility
            "ext_data": Json(self.ext_data),
        }
