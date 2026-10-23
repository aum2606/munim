from typing import Any

from app.schemas.requirements import RequirementDefinition


def requirement_defaults() -> list[RequirementDefinition]:
    definitions: dict[str, list[tuple[str, str]]] = {
        "photography": [
            ("event_type", "What type of event is it?"),
            ("date", "What is the event date?"),
            ("city_venue", "Which city and venue?"),
            ("days", "How many days of coverage?"),
            ("hours", "How many hours per day?"),
            ("deliverables", "Do you need photos, video or an album?"),
            ("crew_size", "How many crew members do you need?"),
        ],
        "printing": [
            ("item", "What would you like printed?"),
            ("size", "What size do you need?"),
            ("material", "Which paper or material?"),
            ("quantity", "How many do you need?"),
            ("sides", "Single-sided or double-sided?"),
            ("colour", "Colour or black and white?"),
            ("finishing", "What finishing do you need?"),
            ("deadline", "When do you need it?"),
        ],
        "interior": [
            ("room_types", "Which rooms are involved?"),
            ("area_sqft", "What is the area in square feet?"),
            ("scope", "What work do you need?"),
            ("budget_range", "What budget range do you have in mind?"),
            ("timeline", "What is your timeline?"),
            ("site_visit", "Do you need a site visit?"),
        ],
        "repair": [
            ("device", "Which device needs repair?"),
            ("brand_model", "What is the brand and model?"),
            ("issue", "What is the issue?"),
            ("warranty", "Is it under warranty?"),
            ("pickup", "Do you need pickup?"),
        ],
        "electronics": [
            ("product", "Which product do you need?"),
            ("brand", "Which brand do you prefer?"),
            ("specs", "What specifications do you need?"),
            ("quantity", "How many do you need?"),
            ("delivery", "Do you need delivery?"),
        ],
    }
    result = []
    for category, slots in definitions.items():
        properties: dict[str, Any] = {key: {"type": "string", "maxLength": 500} for key, _ in slots}
        for key in {"quantity", "days", "hours", "crew_size", "area_sqft"} & properties.keys():
            properties[key] = {"type": "integer", "minimum": 1, "maximum": 1_000_000}
        all_defaults: dict[str, dict[str, Any]] = {
            "photography": {"hours": 8, "crew_size": 2},
            "printing": {
                "size": "standard",
                "material": "standard",
                "colour": "colour",
                "finishing": "none",
            },
            "interior": {"site_visit": "yes"},
            "repair": {"warranty": "unknown", "pickup": "no"},
            "electronics": {"brand": "no preference", "specs": "standard", "delivery": "no"},
        }
        defaults = all_defaults[category]
        result.append(
            RequirementDefinition.model_validate(
                {
                    "category": category,
                    "json_schema": {
                        "type": "object",
                        "properties": properties,
                        "required": [key for key, _ in slots],
                        "additionalProperties": False,
                    },
                    "defaults": defaults,
                    "question_templates": dict(slots),
                }
            )
        )
    return result
