from pydantic import BaseModel, Field
from typing import List, Optional


class BgmTrack(BaseModel):
    id: str
    title: str
    mood: Optional[str] = None
    bpm: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    filename: str
    url: str
    uploaded_at: Optional[str] = None


class BgmUpdatePayload(BaseModel):
    title: Optional[str] = None
    mood: Optional[str] = None
    bpm: Optional[float] = None
    tags: Optional[List[str]] = None
