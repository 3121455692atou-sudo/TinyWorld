import io
import json
import zipfile

from fastapi.testclient import TestClient
from app.main import app
from conftest import make_world


def unpack(response):
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return json.loads(archive.read('configs/agent_config.json'))


def test_local_reuse_keeps_credentials_but_export_remains_redacted(db):
    world, agents = make_world(db, 1)
    agents[0].llm_api_key = 'test-provider-secret'
    agents[0].llm_base_url = 'https://example.test/v1'
    agents[0].model_name = 'test-model'
    agents[0].avatar_hint_json = {'image_data_url': 'data:image/png;base64,QUJD', 'standing_image_data_url': 'data:image/png;base64,REVG'}
    world.settings_json = {'image_generation': {'api_key': 'test-image-secret', 'prompt_llm_api_key': 'test-prompt-secret'}}
    db.commit()
    client = TestClient(app)
    exported = unpack(client.get(f'/api/worlds/{world.world_id}/agents/export'))
    response = client.post(f'/api/worlds/{world.world_id}/agents/reuse')
    reused = unpack(response)
    assert response.headers['cache-control'] == 'no-store'
    assert exported['providers'][0]['apiKey'] == ''
    assert exported['imageGeneration']['api_key'] == ''
    assert exported['imageGeneration']['prompt_llm_api_key'] == ''
    assert reused['providers'][0]['apiKey'] == 'test-provider-secret'
    assert reused['imageGeneration']['api_key'] == 'test-image-secret'
    assert reused['imageGeneration']['prompt_llm_api_key'] == 'test-prompt-secret'
    assert reused['agents'][0]['avatarPath']
    assert reused['agents'][0]['standingImagePath']


def test_partial_profile_updates_preserve_other_images_and_explicit_clear_works(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.avatar_hint_json = {'image_data_url': 'data:image/png;base64,QUJD', 'standing_image_data_url': 'data:image/png;base64,REVG', 'color': '#123456'}
    db.commit()
    client = TestClient(app)
    url = f'/api/worlds/{world.world_id}/agents/{agent.agent_id}/profile'
    response = client.patch(url, json={'avatar_hint': {'standing_image_data_url': 'data:image/png;base64,R0hJ'}})
    hint = response.json()['identity']['avatar_hint']
    assert hint['image_data_url'] == 'data:image/png;base64,QUJD'
    assert hint['color'] == '#123456'
    response = client.patch(url, json={'avatar_hint': {'image_data_url': None}})
    hint = response.json()['identity']['avatar_hint']
    assert 'image_data_url' not in hint
    assert hint['standing_image_data_url'] == 'data:image/png;base64,R0hJ'
