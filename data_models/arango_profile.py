from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class SegmentRef(BaseModel):
    id: str
    name: str


class JourneyRef(BaseModel):
    id: str
    name: str
    funnelIndex: int


class Touchpoint(BaseModel):
    _key: str
    hostname: str
    name: str
    url: str
    parentId: str


class ArangoProfile(BaseModel):
    model_config = ConfigDict(
        extra="ignore"   # ✅ silently ignore unexpected fields
    )

    profile_id: Optional[str] = None
    identities: List[str] = Field(default_factory=list)

    primaryEmail: Optional[EmailStr] = None
    secondaryEmails: List[EmailStr] = Field(default_factory=list)

    primaryPhone: Optional[str] = None
    secondaryPhones: List[str] = Field(default_factory=list)

    firstName: Optional[str] = None
    lastName: Optional[str] = None
    livingLocation: Optional[str] = None
    livingCountry: Optional[str] = None
    livingCity: Optional[str] = None

    jobTitles: List[str] = Field(default_factory=list)
    dataLabels: List[str] = Field(default_factory=list)
    contentKeywords: List[str] = Field(default_factory=list)
    mediaChannels: List[str] = Field(default_factory=list)
    behavioralEvents: List[str] = Field(default_factory=list)
    inSegments: List[SegmentRef] = Field(default_factory=list)
    inJourneyMaps: List[JourneyRef] = Field(default_factory=list)

    eventStatistics: Dict[str, int] = Field(default_factory=dict)
    topEngagedTouchpoints: List[Touchpoint] = Field(default_factory=list)

    @classmethod
    def from_arango(cls, doc: Dict[str, Any]) -> "ArangoProfile":
        return cls(
            # --- identity ---
            profile_id=doc.get("_key"),
            identities=doc.get("identities", []),

            # --- contact ---
            primaryEmail=doc.get("primaryEmail"),
            secondaryEmails=doc.get("secondaryEmails", []),

            primaryPhone=doc.get("primaryPhone"),
            secondaryPhones=doc.get("secondaryPhones", []),

            # --- personal ---
            firstName=doc.get("firstName"),
            lastName=doc.get("lastName"),
            livingLocation=doc.get("livingLocation"),
            livingCountry=doc.get("livingCountry"),
            livingCity=doc.get("livingCity"),

            # --- enrichment ---
            jobTitles=doc.get("jobTitles", []),
            dataLabels=doc.get("dataLabels", []),
            contentKeywords=doc.get("contentKeywords", []),
            mediaChannels=doc.get("mediaChannels", []),
            behavioralEvents=doc.get("behavioralEvents", []),

            # --- segmentation ---
            inSegments=[
                SegmentRef(
                    id=s.get("id"),
                    name=s.get("name"),
                )
                for s in doc.get("inSegments", [])
                if isinstance(s, dict)
            ],

            # --- journeys ---
            inJourneyMaps=[
                JourneyRef(
                    id=j.get("id"),
                    name=j.get("name"),
                    funnelIndex=j.get("funnelIndex", 0),
                )
                for j in doc.get("inJourneyMaps", [])
                if isinstance(j, dict)
            ],

            # --- statistics ---
            eventStatistics=doc.get("eventStatistics", {}),

            # --- touchpoints ---
            topEngagedTouchpoints=[
                Touchpoint(
                    _key=t.get("_key"),
                    hostname=t.get("hostname"),
                    name=t.get("name"),
                    url=t.get("url"),
                    parentId=t.get("parentId"),
                )
                for t in doc.get("topEngagedTouchpoints", [])
                if isinstance(t, dict)
            ],
        )



CDP_PROFILE_QUERY = """
    FOR p IN cdp_profile
        FILTER p.inSegments != null
        FILTER @segment_id IN p.inSegments[*].id
        FILTER (
            (p.primaryEmail != null AND p.primaryEmail != "")
            OR
            (p.primaryPhone != null AND p.primaryPhone != "")
        )

        LET topEngagedTouchpoints = (
            FOR t IN cdp_touchpoint
                FILTER t._key IN p.topEngagedTouchpointIds
                RETURN {
                    _key: t._key,
                    hostname: t.hostname,
                    name: t.name,
                    url: t.url,
                    parentId: t.parentId
                }
        )

        RETURN {
            _key: p._key,
            identities: p.identities,

            primaryEmail: p.primaryEmail,
            secondaryEmails: p.secondaryEmails,

            primaryPhone: p.primaryPhone,
            secondaryPhones: p.secondaryPhones,

            firstName: p.firstName,
            lastName: p.lastName,
            livingLocation: p.livingLocation,
            livingCountry: p.livingCountry,
            livingCity: p.livingCity,

            jobTitles: p.jobTitles,
            dataLabels: p.dataLabels,
            contentKeywords: p.contentKeywords,
            mediaChannels: p.mediaChannels,
            behavioralEvents: p.behavioralEvents,

            inSegments: p.inSegments,
            inJourneyMaps: p.inJourneyMaps,

            eventStatistics: p.eventStatistics,
            topEngagedTouchpoints: topEngagedTouchpoints
        }
"""
