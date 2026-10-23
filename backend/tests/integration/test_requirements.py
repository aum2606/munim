from copy import deepcopy

from app.schemas.requirements import RequirementDefinition
from seeds.requirements import requirement_defaults
from tests.integration.test_workspace import owner


async def test_requirement_schemas_defaults_validation_and_isolation(client):
    a, _, _ = await owner(client)
    b, _, _ = await owner(client)
    path = "/api/v1/requirement-schemas"
    assert (await client.get(path)).status_code == 401
    assert (await client.put(path, json={})).status_code == 401
    schemas = (await client.get(path, headers=a)).json()
    assert {schema["category"] for schema in schemas} == {
        "photography",
        "printing",
        "interior",
        "repair",
        "electronics",
    }
    printing = next(schema for schema in schemas if schema["category"] == "printing")
    printing.pop("id")
    printing["question_templates"]["quantity"] = "How many copies please?"
    assert (await client.put(path, headers=a, json=printing)).status_code == 200
    others = (await client.get(path, headers=b)).json()
    assert (
        next(schema for schema in others if schema["category"] == "printing")["question_templates"][
            "quantity"
        ]
        != "How many copies please?"
    )
    printing["defaults"]["quantity"] = -1
    assert (await client.put(path, headers=a, json=printing)).status_code == 422


def test_requirement_defaults_reject_invalid_schema_and_defaults():
    import pytest
    from pydantic import ValidationError

    for definition in requirement_defaults():
        assert RequirementDefinition.model_validate(definition.model_dump())
    original = requirement_defaults()[0].model_dump()
    for mutate in (
        lambda d: d["json_schema"].update(type="array"),
        lambda d: d["json_schema"].update(additionalProperties=True),
        lambda d: d["defaults"].update(unknown="value"),
        lambda d: d["json_schema"]["properties"].update(extra={"type": "number"}),
        lambda d: d["question_templates"].clear(),
    ):
        invalid = deepcopy(original)
        mutate(invalid)
        with pytest.raises(ValidationError):
            RequirementDefinition.model_validate(invalid)
