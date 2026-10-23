from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.schemas.knowledge import StrictModel

Category = Literal["photography", "printing", "interior", "repair", "electronics"]


class RequirementDefinition(StrictModel):
    category: Category
    json_schema: dict[str, Any]
    defaults: dict[str, Any]
    question_templates: dict[str, str]

    @model_validator(mode="after")
    def valid_definition(self) -> "RequirementDefinition":
        schema = self.json_schema
        properties = schema.get("properties", {})
        if (
            schema.get("type") != "object"
            or not isinstance(properties, dict)
            or not 1 <= len(properties) <= 20
        ):
            raise ValueError("Schema must define between 1 and 20 object properties")
        if set(schema) - {"type", "properties", "required", "additionalProperties"}:
            raise ValueError("Unsupported schema keywords")
        if schema.get("additionalProperties") is not False:
            raise ValueError("Additional properties must be disabled")
        required = schema.get("required", [])
        if (
            not isinstance(required, list)
            or any(not isinstance(key, str) for key in required)
            or not set(required) <= set(properties)
        ):
            raise ValueError("Required slots must exist")
        for key, spec in properties.items():
            if not isinstance(key, str) or not key.isidentifier() or len(key) > 50:
                raise ValueError("Slot names must be short identifiers")
            if not isinstance(spec, dict) or spec.get("type") not in (
                "string",
                "integer",
                "boolean",
            ):
                raise ValueError("Slots support string, integer or boolean values")
            if set(spec) - {"type", "enum", "minimum", "maximum", "maxLength"}:
                raise ValueError("Unsupported slot keywords")
            for bound in ("minimum", "maximum", "maxLength"):
                if bound in spec and (type(spec[bound]) is not int or spec[bound] < 0):
                    raise ValueError("Slot limits must be nonnegative integers")
            if "enum" in spec and (
                not isinstance(spec["enum"], list)
                or not spec["enum"]
                or any(not value_valid(value, spec) for value in spec["enum"])
            ):
                raise ValueError("Invalid slot choices")
        if not set(properties) <= self.question_templates.keys():
            raise ValueError("Each slot needs a question template")
        if any(not text.strip() or len(text) > 200 for text in self.question_templates.values()):
            raise ValueError("Questions must contain at most 200 characters")
        if not set(self.defaults) <= set(properties) or any(
            not value_valid(value, properties[key]) for key, value in self.defaults.items()
        ):
            raise ValueError("Defaults must match the slot schema")
        return self


def value_valid(value: Any, spec: dict[str, Any]) -> bool:
    expected = {"string": str, "integer": int, "boolean": bool}[spec["type"]]
    if type(value) is not expected:
        return False
    if "enum" in spec and value not in spec["enum"]:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and len(value) <= min(spec.get("maxLength", 500), 500)
    if type(value) is int:
        return bool(spec.get("minimum", 0) <= value <= spec.get("maximum", 1_000_000))
    return True


class RequirementView(RequirementDefinition):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: UUID


class SlotUpdate(StrictModel):
    key: str = Field(max_length=50)
    value: str = Field(max_length=500)


class RequirementsInput(StrictModel):
    question: str
    category: Category
    slots: list[str]
    filled: list[SlotUpdate]


class RequirementsOutput(StrictModel):
    updates: list[SlotUpdate] = Field(max_length=20)
