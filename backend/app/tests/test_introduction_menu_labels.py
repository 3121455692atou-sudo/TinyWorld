import pytest
from app.core.models import World
from app.llm.action_options import build_action_options
from app.llm.action_protocol import format_action_options_for_prompt
from app.tools.tool_specs import TOOL_SPECS
from app.world.visibility import build_visible_people, mark_name_known
from app.tests.conftest import make_world
pytest_plugins = ['app.tests.conftest']

def test_english_third_person_introduction_shows_both_people(db):
    world, agents = make_world(db, 4)
    world.settings_json = {'language': 'en'}
    for agent, name in zip(agents, ['Alice', 'Bob', 'Carol', 'Diana']):
        agent.chosen_name = name
    actor = agents[0]
    for target in agents[1:]:
        mark_name_known(db, actor.agent_id, target, 0, 'test')
    db.flush()
    refs = {p.visible_ref:p.target_agent_id for p in build_visible_people(db, actor, 0, persist=False)}
    options = build_action_options(db, world, actor, [TOOL_SPECS['introduce_other_agent']], refs)
    assert options
    print(format_action_options_for_prompt(options, language='en'))
    for choice in options[0].target_choices:
        assert choice['params']['known_name'] in choice['label'], (choice['label'], choice['params']['known_name'])
