from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.tenant import TenantContext
from app.ingestion.documents import DocumentService
from app.llm import FakeEmbedder
from app.repositories.documents import DocumentRepository
from app.schemas.documents import FAQInput


class FakeQueue:
    def __init__(self):
        self.jobs = []

    async def enqueue(self, task, tenant_id, resource_id):
        self.jobs.append((task, tenant_id, resource_id))


async def owner(client):
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
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    profile = (await client.get("/api/v1/me", headers=headers)).json()
    return headers, TenantContext(UUID(profile["tenant_id"]))


async def test_queued_documents_ingestion_retries_faq_and_isolation(client, sessions, tmp_path):
    a, ctx_a = await owner(client)
    b, ctx_b = await owner(client)
    queue = FakeQueue()
    client_app = client._transport.app
    client_app.state.jobs = queue
    client_app.state.settings = Settings(
        database_url=client_app.state.settings.database_url,
        storage_dir=str(tmp_path),
        secret_key="test-only-key-with-at-least-32-characters",
    )
    assert (
        await client.post(
            "/api/v1/documents",
            files={"file": ("policy.txt", b"Delivery takes three working days.")},
        )
    ).status_code == 401
    uploaded = await client.post(
        "/api/v1/documents",
        headers=a,
        files={"file": ("policy.txt", b"Delivery takes three working days.")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = UUID(uploaded.json()["id"])
    assert uploaded.json()["status"] == "pending"
    assert queue.jobs == [("ingest_document", ctx_a.tenant_id, document_id)]
    path = "/api/v1/documents/" + str(document_id)
    assert (await client.get(path, headers=b)).status_code == 404
    assert (await client.post(path + "/retry", headers=b)).status_code == 404
    assert (await client.get("/api/v1/documents", headers=b)).json() == []
    async with sessions() as session:
        service = DocumentService(session, ctx_a, client_app.state.settings, queue)
        await service.ingest(document_id, FakeEmbedder())
        await service.ingest(document_id, FakeEmbedder())
        assert len(await DocumentRepository(session, ctx_a).chunks(document_id)) == 1
        assert (await DocumentRepository(session, ctx_a).get(document_id)).status == "ready"
        faq = await service.faq(
            FAQInput(question="When are you open?", answer="Monday through Saturday.")
        )
        await service.ingest(faq.id, FakeEmbedder())
        assert len(await DocumentRepository(session, ctx_a).chunks(faq.id)) == 1
    assert (await client.get(path, headers=a)).json()["status"] == "ready"
    assert (await client.post(path + "/retry", headers=a)).status_code == 409
    assert (
        await client.post("/api/v1/documents", headers=a, files={"file": ("bad.exe", b"bad")})
    ).status_code == 400
    assert (
        await client.post("/api/v1/faqs", headers=a, json={"question": "", "answer": ""})
    ).status_code == 422
    broken = await client.post("/api/v1/documents", headers=a, files={"file": ("empty.txt", b" ")})
    async with sessions() as session:
        await DocumentService(session, ctx_a, client_app.state.settings, queue).ingest(
            UUID(broken.json()["id"]), FakeEmbedder()
        )
    failed = (await client.get("/api/v1/documents/" + broken.json()["id"], headers=a)).json()
    assert failed["status"] == "failed" and "No readable text" in failed["error"]
