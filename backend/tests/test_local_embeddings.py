import httpx
import pytest
import respx
from fastapi import HTTPException
from app import local_embeddings as local


def test_local_embedding_uses_fixed_authenticated_endpoint_and_query_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(local.config, 'data_dir', tmp_path)
    folder = tmp_path / 'knowledge-rag'; folder.mkdir(); (folder / 'bridge.key').write_text('local-only-test-key')
    seen = []
    def respond(request):
        import json
        seen.append(json.loads(request.content))
        assert request.headers['Authorization'] == 'Bearer local-only-test-key'
        return httpx.Response(200, json={'model': local.MODEL, 'data': [{'index': i, 'embedding': [1.] * 512} for i in range(len(seen[-1]['input']))]})
    with respx.mock as mock:
        route = mock.post(local.BASE + '/embeddings').mock(side_effect=respond)
        e = local.LocalEmbeddings()
        assert len(e.embed_documents(['文档'] * 33)) == 33
        assert len(e.embed_query('问题')) == 512
        assert [b['query'] for b in seen] == [False, False, True]
        assert e.last_usage is None
        route.mock(return_value=httpx.Response(200, json={'model': local.MODEL, 'data': [{'index': 0, 'embedding': [0.] * 512}]}))
        with pytest.raises(HTTPException): e.embed_query('问题')
