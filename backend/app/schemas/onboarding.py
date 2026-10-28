from datetime import time
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.knowledge import StrictModel
from app.schemas.requirements import Category

Day = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class OnboardingPreferences(StrictModel):
    category: Category
    tone: Literal["friendly", "formal"] = "friendly"
    languages: list[Literal["en", "hi", "gu", "hinglish", "gujlish"]] = Field(
        min_length=1, max_length=5
    )
    business_hours: dict[Day, tuple[str, str]]

    @model_validator(mode="after")
    def valid_hours(self) -> "OnboardingPreferences":
        if len(set(self.languages)) != len(self.languages):
            raise ValueError("Languages must be unique")
        for start, end in self.business_hours.values():
            if any(
                len(value) != 5 or time.fromisoformat(value).tzinfo is not None
                for value in (start, end)
            ):
                raise ValueError("Business hours must use local HH:MM times")
        return self


class OnboardingState(StrictModel):
    profile_ready: bool
    catalog_ready: bool
    knowledge_ready: bool
    tax_profile_ready: bool
    playground_tested: bool
    completed: bool
    preferences: OnboardingPreferences
