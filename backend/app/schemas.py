from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ReferenceFaceSelection(BaseModel):
    reference_face_id: UUID


class MatchDecisionUpdate(BaseModel):
    decision: str = Field(pattern="^(accepted|rejected|undecided)$")


class SaveCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
