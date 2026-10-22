from app.llm import FakeEmbedder


async def test_offline_multilingual_embedding_contract() -> None:
    embedder = FakeEmbedder(16)
    vectors = await embedder.embed(["laptop ka rate", "भाव क्या है", "કિંમત કેટલી છે"])
    assert len(vectors) == 3
    assert all(len(vector) == 16 for vector in vectors)
    assert len({tuple(vector) for vector in vectors}) == 3
