import httpx

from tests.conftest import PASSWORD, bearer, register, unique_email


async def _create(client: httpx.AsyncClient, token: str, **extra: str) -> httpx.Response:
    body = {"email": unique_email(), "name": "Staff", "password": PASSWORD, **extra}
    return await client.post("/api/v1/users", json=body, headers=bearer(token))


async def _staff_token(client: httpx.AsyncClient, owner: str) -> tuple[str, str]:
    created = await _create(client, owner)
    email = created.json()["email"]
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return created.json()["id"], login.json()["access_token"]


async def test_owner_creates_and_lists_staff(client: httpx.AsyncClient) -> None:
    _, owner = await register(client)
    created = await _create(client, owner)
    assert created.status_code == 201 and created.json()["role"] == "staff"
    listed = await client.get("/api/v1/users", headers=bearer(owner))
    assert len(listed.json()) == 2
    assert "password" not in listed.text


async def test_staff_cannot_manage_users(client: httpx.AsyncClient) -> None:
    _, owner = await register(client)
    _, staff = await _staff_token(client, owner)
    assert (await client.get("/api/v1/users", headers=bearer(staff))).status_code == 403
    assert (await _create(client, staff)).status_code == 403
    assert (await client.get("/api/v1/me", headers=bearer(staff))).status_code == 200


async def test_users_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/users")).status_code == 401
    assert (await client.post("/api/v1/users", json={})).status_code == 401


async def test_create_user_validation_and_duplicates(client: httpx.AsyncClient) -> None:
    _, owner = await register(client)
    email = unique_email()
    assert (await _create(client, owner, email=email)).status_code == 201
    assert (await _create(client, owner, email=email)).status_code == 409
    assert (await _create(client, owner, password="short")).status_code == 422
    assert (await _create(client, owner, role="admin")).status_code == 422


async def test_tenant_isolation_for_users(client: httpx.AsyncClient) -> None:
    _, token_a = await register(client)
    _, token_b = await register(client)
    a_user = (await _create(client, token_a, name="Only in A")).json()["id"]

    # B sees only its own owner...
    users_b = (await client.get("/api/v1/users", headers=bearer(token_b))).json()
    assert len(users_b) == 1 and a_user not in [u["id"] for u in users_b]
    # ...cannot write A's user (404, same as a user that does not exist)...
    patch = await client.patch(
        f"/api/v1/users/{a_user}", json={"is_active": False}, headers=bearer(token_b)
    )
    assert patch.status_code == 404
    # ...and A's user is untouched.
    users_a = (await client.get("/api/v1/users", headers=bearer(token_a))).json()
    assert next(u for u in users_a if u["id"] == a_user)["is_active"] is True
    # Users B creates land in B, never A.
    await _create(client, token_b)
    assert len((await client.get("/api/v1/users", headers=bearer(token_a))).json()) == 2


async def test_deactivated_user_loses_access_immediately(client: httpx.AsyncClient) -> None:
    _, owner = await register(client)
    staff_id, staff = await _staff_token(client, owner)
    assert (await client.get("/api/v1/me", headers=bearer(staff))).status_code == 200

    off = await client.patch(
        f"/api/v1/users/{staff_id}", json={"is_active": False}, headers=bearer(owner)
    )
    assert off.status_code == 200
    assert (await client.get("/api/v1/me", headers=bearer(staff))).status_code == 401


async def test_owner_cannot_deactivate_themselves(client: httpx.AsyncClient) -> None:
    _, owner = await register(client)
    me = (await client.get("/api/v1/me", headers=bearer(owner))).json()["user"]["id"]
    response = await client.patch(
        f"/api/v1/users/{me}", json={"is_active": False}, headers=bearer(owner)
    )
    assert response.status_code == 403
