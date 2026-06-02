from __future__ import annotations

from app.llm.action_protocol import ActionOption, packet_to_action_choice, parse_action_packet


def test_aohp_v2_preserves_free_chinese_speech_and_prefilled_target():
    options = [
        ActionOption(
            option_id=7,
            label="请求拥抱 附近人物A",
            tool_name="hug_visible_agent",
            params={"visible_ref": "附近人物A"},
            text_slot="speech",
        )
    ]

    raw = """[07]
嗯…好呀，但你先慢一点。我刚才真的有点被吓到。"""
    packet = parse_action_packet(raw)
    assert packet is not None
    action = packet_to_action_choice(packet, options)

    assert action is not None
    assert action.tool_name == "hug_visible_agent"
    assert action.params["visible_ref"] == "附近人物A"
    assert action.params["speech"] == "嗯…好呀，但你先慢一点。我刚才真的有点被吓到。"


def test_aohp_v2_does_not_strip_pipes_at_symbols_or_commas_from_speech():
    options = [
        ActionOption(
            option_id=12,
            label="对附近人物A说话",
            tool_name="say_to_visible_agent",
            params={"visible_ref": "附近人物A"},
            text_slot="speech",
        )
    ]
    raw = """[12]
，，嗯…好呀，A|B 这种符号我也照样说，@也只是普通字符。"""
    packet = parse_action_packet(raw)
    action = packet_to_action_choice(packet, options) if packet else None
    assert action is not None
    assert action.params["speech"] == "，，嗯…好呀，A|B 这种符号我也照样说，@也只是普通字符。"


def test_aohp_v2_numeric_value_is_clamped_and_no_tool_name_is_needed():
    options = [
        ActionOption(
            option_id=3,
            label="睡觉",
            tool_name="sleep",
            params={},
            value_slot="sleep_hours",
            min_value=1,
            max_value=10,
            default_value=8,
        )
    ]

    packet = parse_action_packet("[3:99]")
    assert packet is not None
    action = packet_to_action_choice(packet, options)

    assert action is not None
    assert action.tool_name == "sleep"
    assert action.params["sleep_hours"] == 10


def test_aohp_v2_accepts_value_with_space():
    options = [
        ActionOption(
            option_id=8,
            label="睡觉",
            tool_name="sleep",
            params={},
            value_slot="sleep_hours",
            min_value=1,
            max_value=16,
            default_value=8,
        )
    ]
    packet = parse_action_packet("[08 7.5]")
    action = packet_to_action_choice(packet, options) if packet else None
    assert action is not None
    assert action.params["sleep_hours"] == 7.5


def test_aohp_rejects_number_outside_current_menu():
    packet = parse_action_packet("[88]\n我随便选一个")
    assert packet is not None
    assert packet_to_action_choice(packet, []) is None


def test_aohp_v2_preserves_english_body_without_json_or_delimiter_pollution():
    options = [
        ActionOption(
            option_id=5,
            label="speak to Person A",
            tool_name="say_to_visible_agent",
            params={"visible_ref": "附近人物A"},
            text_slot="speech",
        )
    ]
    raw = """[05]
Well... yes, I heard you — but A|B and @ signs are just part of what I said."""
    packet = parse_action_packet(raw)
    action = packet_to_action_choice(packet, options) if packet else None
    assert action is not None
    assert action.params["speech"] == "Well... yes, I heard you — but A|B and @ signs are just part of what I said."
    assert action.tool_name == "say_to_visible_agent"
    assert action.params["visible_ref"] == "附近人物A"
