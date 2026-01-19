
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field


class PGProfileUpsert(BaseModel):
    tenant_id: str

    profile_id: str
    email: Optional[EmailStr] = None
    mobile_number: Optional[str] = None

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None

    segments: List[str] = Field(default_factory=list)
    raw_attributes: Dict[str, Any]

    def to_pg_row(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "profile_id": self.profile_id,
            "email": self.email,
            "mobile_number": self.mobile_number,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "job_title": self.job_title,
            "segments": self.segments,
            "raw_attributes": self.raw_attributes,
        }
