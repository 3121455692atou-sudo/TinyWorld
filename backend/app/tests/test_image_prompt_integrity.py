import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.core.models import Agent
from app.events.event_store import create_event
from app.image_generation import service
from conftest import make_world


def setup_image(db):
    world, agents = make_world(db, 4)
    config = service.normalize_image_generation_settings({
        'enabled': True, 'provider_type': 'sdxl', 'prompt_style': 'dalle',
        'prompt_llm_mode': 'custom', 'prompt_llm_model_name': 'test',
        'request_template_json': '{"model":"{{model}}","prompt":"{{prompt}}","aspect_ratio":"16:9"}',
        'agent_aliases': {a.agent_id:a.chosen_name for a in agents},
    })
    world.settings_json={'image_generation':config}
    source=create_event(db,world=world,event_type='note',viewer_text='、'.join(a.chosen_name for a in agents)+'在广场说话。')
    event=create_event(db,world=world,event_type='image_generation',viewer_text='待生成',payload={'status':'pending','source_event_ids':[source.event_id]})
    db.commit()
    return world,agents,event,config


@pytest.mark.parametrize('raw', ['抱歉，您的问题我无法识别。',''])
def test_invalid_prompt_never_calls_image_provider(db,monkeypatch,raw):
    world,agents,event,config=setup_image(db)
    monkeypatch.setattr(service.provider,'complete_text',AsyncMock(return_value=SimpleNamespace(raw_text=raw,error=None)))
    image=AsyncMock(side_effect=AssertionError('Paid image request forbidden'))
    monkeypatch.setattr(service,'_call_image_provider',image)
    monkeypatch.setattr(service,'_broadcast_image_update',AsyncMock())
    asyncio.run(service._generate_image_with_session(db,world,event))
    assert event.payload['status']=='failed'
    assert '未调用生图接口' in event.payload['error']
    image.assert_not_called()


def test_natural_prose_does_not_add_people_or_styles(db,monkeypatch):
    world,agents,event,config=setup_image(db)
    prose=f'{agents[0].chosen_name}与{agents[1].chosen_name}坐在广场上交谈。动画原画风。'
    writer=AsyncMock(return_value=SimpleNamespace(raw_text='POSITIVE='+prose+'\nNEGATIVE=',error=None))
    monkeypatch.setattr(service.provider,'complete_text',writer)
    positive,negative,debug=asyncio.run(service._create_image_prompt(db,world,event,config))
    assert positive==prose and negative==''
    assert agents[2].chosen_name not in positive
    assert '内容标签' not in writer.call_args.kwargs['user_prompt']
    assert service._request_payload(config,'sdxl',positive,negative)['prompt']==prose


def test_six_named_people_are_rejected_before_paid_request(db,monkeypatch):
    world,agents,event,config=setup_image(db)
    for index,name in enumerate(['第五人','第六人']):
        agent=Agent(agent_id=f'extra{index}',world_id=world.world_id,chosen_name=name)
        db.add(agent);agents.append(agent)
    db.commit()
    raw='POSITIVE='+'、'.join(a.chosen_name for a in agents)+'在广场。\nNEGATIVE='
    monkeypatch.setattr(service.provider,'complete_text',AsyncMock(return_value=SimpleNamespace(raw_text=raw,error=None)))
    with pytest.raises(ValueError,match='超过 5'):
        asyncio.run(service._create_image_prompt(db,world,event,config))


def test_rerun_preserves_user_prompt_through_request_with_old_style(db,monkeypatch):
    world,agents,event,config=setup_image(db)
    config['style_prompt']='旧画风，不应重新添加'
    config['negative_prompt']='旧负面，不应重新添加'
    world.settings_json={'image_generation':config}
    monkeypatch.setattr(service,'_schedule_background_generation',lambda *args:None)
    monkeypatch.setattr(service,'_broadcast_image_update',AsyncMock())
    writer=AsyncMock(side_effect=AssertionError('Manual rerun must bypass writer'))
    monkeypatch.setattr(service.provider,'complete_text',writer)
    prose='高松灯在窗边读信。\n动画原画风。'
    asyncio.run(service.rerun_image_generation_event(db,world,event.event_id,prompt=prose,negative_prompt=''))
    positive,negative,debug=asyncio.run(service._create_image_prompt(db,world,event,config))
    payload=service._request_payload(config,'sdxl',positive,negative)
    assert event.payload['prompt']==positive==payload['prompt']==prose
    assert negative=='' and payload['aspect_ratio']=='16:9'
    writer.assert_not_called()


@pytest.mark.parametrize('manual_kind', ['manual', 'rerun', 'automatic'])
def test_auto_switch_does_not_block_explicit_requests(db, monkeypatch, manual_kind):
    world, agents, event, config = setup_image(db)
    config['auto_enabled'] = False
    world.settings_json = {'image_generation': config}
    payload = dict(event.payload)
    if manual_kind == 'manual':
        payload.update(manual=True, manual_prompt='我手写的画面。')
    elif manual_kind == 'rerun':
        payload.update(rerun=True, prompt='我手写的画面。')
    event.payload = payload
    db.commit()
    image = AsyncMock(return_value='mock-image')
    writer = AsyncMock(side_effect=AssertionError('No prompt generation expected'))
    monkeypatch.setattr(service, '_call_image_provider', image)
    monkeypatch.setattr(service.provider, 'complete_text', writer)
    monkeypatch.setattr(service, 'store_image_data_url', lambda _: {'image_url': '/mock.png'})
    monkeypatch.setattr(service, '_broadcast_image_update', AsyncMock())
    asyncio.run(service._generate_image_with_session(db, world, event))
    if manual_kind == 'automatic':
        assert event.payload['status'] == 'skipped'
        image.assert_not_called()
    else:
        assert event.payload['status'] == 'completed'
        assert image.call_args.args[1] == '我手写的画面。'
    writer.assert_not_called()


def test_auto_switch_blocks_scheduling_but_allows_manual(db, monkeypatch):
    world, agents, event, config = setup_image(db)
    config.update(auto_enabled=False, source_mode='auto_summary')
    world.settings_json = {'image_generation': config}
    monkeypatch.setattr(service, '_schedule_background_generation', lambda *args: None)
    assert service.maybe_schedule_auto_image_generation(db, world, event.payload['source_event_ids'], force=True) == []
    assert service.create_prompt_image_generation(db, world, prompt='手动生图')
    assert service.create_manual_image_generation(db, world)
    config['source_mode'] = 'narration'
    world.settings_json = {'image_generation': config}
    assert service.schedule_image_generation(db, world, narrator_run=None, narration_event=event, source_events=[]) == []
    assert service.normalize_image_generation_settings({}, config)['auto_enabled'] is False


def test_references_follow_final_prompt_not_source_participants(db):
    world, agents, event, config = setup_image(db)
    config.update(reference_standing_images=True, reference_avatar_images=False)
    for index, agent in enumerate(agents):
        import base64
        agent.avatar_hint_json = {'standing_image_data_url': 'data:image/png;base64,' + base64.b64encode(str(index).encode()).decode()}
    prompt = f'{agents[2].chosen_name}和{agents[0].chosen_name}坐在一起。'
    refs = service._reference_images_for_event(db, world, event, config, prompt=prompt)
    assert [ref['content'] for ref in refs] == [b'2', b'0']
    assert service._reference_images_for_event(db, world, event, config, prompt='空无一人的房间。') == []


def test_openrouter_references_use_json_and_preserve_manual_prompt(monkeypatch):
    import json
    import httpx
    prompt = '  高松灯坐在窗边。\n保留我的原文  '
    config = {
        'provider_type': 'sdxl', 'base_url': 'https://openrouter.ai/api/v1',
        'endpoint_path': '/images', 'model_name': 'openai/gpt-image-2.5-sunburst',
        'request_template_json': '{"model":"{{model}}","prompt":"{{prompt}}","aspect_ratio":"16:9"}',
    }
    requests = []
    def respond(request):
        requests.append(request)
        assert str(request.url) == 'https://openrouter.ai/api/v1/images'
        assert request.headers['Content-Type'] == 'application/json'
        payload = json.loads(request.content)
        assert payload['prompt'] == prompt.replace('高松灯', '高松灯【图1】')
        assert payload['aspect_ratio'] == '16:9'
        assert payload['input_references'] == [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YWJj'}}]
        return httpx.Response(200, json={'data': [{'url': 'data:image/png;base64,YWJj'}]})
    client_class = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, 'AsyncClient', lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
    edit = AsyncMock(side_effect=AssertionError('OpenRouter must not use multipart edit'))
    monkeypatch.setattr(service, '_call_openai_image_edit', edit)
    asyncio.run(service._call_image_provider_once(config, prompt, '', reference_images=[{'content': b'abc', 'media_type': 'image/png', 'character_names': ['高松灯']}]))
    assert len(requests) == 1
    edit.assert_not_called()


def test_other_openai_providers_keep_multipart_edit(monkeypatch):
    edit = AsyncMock(return_value='data:image/png;base64,YWJj')
    monkeypatch.setattr(service, '_call_openai_image_edit', edit)
    asyncio.run(service._call_image_provider_once({'provider_type': 'sdxl', 'base_url': 'https://example.test/v1'}, '原文', '', reference_images=[{'content': b'abc', 'media_type': 'image/png'}]))
    edit.assert_awaited_once()


def test_identity_reuse_in_new_world_retains_standing_image(db):
    from app.api.identity_library import _identity_item
    world, agents = make_world(db, 1)
    agents[0].avatar_hint_json = {'image_data_url': 'data:image/png;base64,QUJD', 'standing_image_data_url': 'data:image/png;base64,REVG'}
    exported = _identity_item(agents[0], world)
    assert exported['standingImageDataUrl'] == 'data:image/png;base64,REVG'
    assert exported['avatarDataUrl'] == 'data:image/png;base64,QUJD'


def test_reference_numbers_follow_actual_attachments_and_are_idempotent(db):
    world, agents, event, config = setup_image(db)
    config.update(reference_standing_images=True, reference_avatar_images=False)
    agents[0].avatar_hint_json = {'standing_image_data_url': 'broken'}
    agents[1].avatar_hint_json = {'standing_image_data_url': 'data:image/png;base64,QUJD'}
    agents[2].avatar_hint_json = {'standing_image_data_url': 'data:image/png;base64,REVG'}
    prompt = f'{agents[0].chosen_name}、{agents[2].chosen_name}【图9】和{agents[1].chosen_name}。{agents[2].chosen_name}回头。'
    refs = service._reference_images_for_event(db, world, event, config, prompt=prompt)
    assert [r['content'] for r in refs] == [b'DEF', b'ABC']
    expected = f'{agents[0].chosen_name}、{agents[2].chosen_name}【图1】和{agents[1].chosen_name}【图2】。{agents[2].chosen_name}【图1】回头。'
    result = service._annotate_reference_names(prompt, refs)
    assert result == expected
    assert service._annotate_reference_names(result, refs) == expected
    assert service._annotate_reference_names(prompt, []) == prompt


def test_reference_alias_regex_escapes_names_and_handles_two_images():
    refs = [
        {'character_names': ['Alice (A)', '爱丽丝']},
        {'character_names': ['Alice (A)', '爱丽丝']},
        {'character_names': ['Bob']},
    ]
    assert service._annotate_reference_names('Alice (A)与Bob；爱丽丝。', refs) == 'Alice (A)【图1】【图2】与Bob【图3】；爱丽丝【图1】【图2】。'
