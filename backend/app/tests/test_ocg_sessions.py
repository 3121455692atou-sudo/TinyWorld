import asyncio

import httpx
import pytest

from app.llm.openai_compatible import OpenAICompatibleProvider


@pytest.mark.parametrize('base_url', ['https://opencode.ai/zen/go/v1', 'https://opencode.ai/inference/go/v1'])
def test_ocg_conversation_survives_ten_retries_and_isolates_worlds_and_roles(monkeypatch, base_url):
    headers = []
    async def post(_self, _client, **kwargs):
        headers.append(dict(kwargs['headers']))
        if len(headers) <= 10:
            raise httpx.ConnectError('offline simulated transient failure')
        return {'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr(OpenAICompatibleProvider, '_post_chat_completion', post)
    async def request(conversation_id):
        return await OpenAICompatibleProvider().complete_text(
            model_alias='world_agent', system_prompt='system', user_prompt='test',
            model_name='deepseek-v4.1-flash', api_key='test', base_url=base_url,
            conversation_id=conversation_id, retry_count=10, retry_interval_ms=0)
    async def run():
        for conversation in ['world1:agent1', 'world1:agent1', 'world1:agent2', 'world2:agent1']:
            assert not (await request(conversation)).error
    asyncio.run(run())
    assert len(headers) == 14  # Initial call + 10 retries, then 3 later turns.
    ids = [h['x-opencode-session'] for h in headers]
    assert len(set(ids[:12])) == 1
    assert len(set(ids[11:])) == 3
    assert all(h['User-Agent'] == 'TinyWorld/1.0' for h in headers)


def test_other_hosts_do_not_receive_ocg_session_headers(monkeypatch):
    async def post(_client, **kwargs):
        assert 'x-opencode-session' not in kwargs['headers']
        return {'choices': [{'message': {'content': 'OK'}}]}
    client = OpenAICompatibleProvider()
    monkeypatch.setattr(client, '_post_chat_completion', post)
    result = asyncio.run(client.complete_text(model_alias='test', system_prompt='', user_prompt='test',
        model_name='test', api_key='test', base_url='https://other.example/v1', conversation_id='world1:agent1'))
    assert not result.error
