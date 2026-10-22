from uuid import uuid4

import httpx


async def owner(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Demo",
            "business_type": "printing",
            "name": "Demo",
            "email": f"{uuid4()}@example.com",
            "password": "synthetic-password",
        },
    )
    assert response.status_code == 201
    return {"Authorization": "Bearer " + response.json()["access_token"]}


async def test_import_preview_mapping_commit_and_isolation(client: httpx.AsyncClient) -> None:
    a, b = await owner(client), await owner(client)
    assert (await client.get("/api/v1/catalog/template.xlsx")).status_code == 401
    assert (await client.get("/api/v1/catalog/template.xlsx", headers=a)).status_code == 200
    content = b'Product Code,Product Name,Rate,GST\nCARD,Visiting cards,"1,20,000",18\n'
    assert (
        await client.post("/api/v1/catalog/import", files={"file": ("prices.csv", content)})
    ).status_code == 401
    uploaded = await client.post(
        "/api/v1/catalog/import", headers=a, files={"file": ("prices.csv", content)}
    )
    assert uploaded.status_code == 201, uploaded.text
    preview = uploaded.json()
    assert preview["rows"][0]["catalog"]["base_price_paise"] == 12000000
    assert (await client.get("/api/v1/catalog/items", headers=a)).json() == []
    path = "/api/v1/catalog/import/" + preview["id"]
    assert (await client.get(path, headers=b)).status_code == 404
    assert (
        await client.post(path + "/commit", headers=b, json={"mapping": preview["mapping"]})
    ).status_code == 404
    assert (await client.post(path + "/commit", headers=a, json={"mapping": {}})).status_code == 400
    committed = await client.post(path + "/commit", headers=a, json={"mapping": preview["mapping"]})
    assert committed.status_code == 200, committed.text
    assert (
        await client.post(path + "/commit", headers=a, json={"mapping": preview["mapping"]})
    ).status_code == 409
    catalog = (await client.get("/api/v1/catalog/items", headers=a)).json()[0]
    item_path = "/api/v1/catalog/items/" + catalog["id"]
    assert (await client.get(item_path, headers=b)).status_code == 404
    changed = {key: value for key, value in catalog.items() if key != "id"}
    changed["name"] = "Changed"
    assert (await client.put(item_path, headers=b, json=changed)).status_code == 404
    assert (await client.put(item_path, headers=a, json=changed)).status_code == 200
    changed["base_price_paise"] = "1.23"
    assert (await client.put(item_path, headers=a, json=changed)).status_code == 422
    assert (await client.delete(item_path, headers=b)).status_code == 404
    assert (await client.delete(item_path, headers=a)).status_code == 204
    assert (await client.get("/api/v1/catalog/items", headers=b)).json() == []


async def test_import_errors_cannot_commit(client: httpx.AsyncClient) -> None:
    headers = await owner(client)
    uploaded = await client.post(
        "/api/v1/catalog/import",
        headers=headers,
        files={"file": ("bad.csv", b"sku,name,price\nONE,One,invalid\n")},
    )
    assert uploaded.status_code == 201
    preview = uploaded.json()
    assert preview["rows"][0]["errors"]
    committed = await client.post(
        "/api/v1/catalog/import/" + preview["id"] + "/commit",
        headers=headers,
        json={"mapping": preview["mapping"]},
    )
    assert committed.status_code == 400
    assert (await client.get("/api/v1/catalog/items", headers=headers)).json() == []
