from __future__ import annotations

from app.content.emotion_effects import (
    emotion_affection_delta,
    emotion_effect_delta,
    extract_expressed_emotion,
    load_emotion_effects,
)


def test_extract_expressed_emotion_variants():
    assert extract_expressed_emotion("今天真不错 情绪：开心") == ("开心", "今天真不错")
    assert extract_expressed_emotion("（情绪：难过）唉") == ("难过", "唉")
    assert extract_expressed_emotion("[情绪:好吃] 这碗面") == ("好吃", "这碗面")
    # no tag -> unchanged
    assert extract_expressed_emotion("普通的一句话") == (None, "普通的一句话")
    # only two-character emotions are captured
    emotion, _ = extract_expressed_emotion("情绪：开开心心")
    assert emotion is None


def test_emotion_effect_delta_known_and_unknown():
    happy = emotion_effect_delta("开心")
    assert happy.get("mood", 0) > 0
    sad = emotion_effect_delta("难过")
    assert sad.get("mood", 0) < 0
    # 不在表里的词 -> 空
    assert emotion_effect_delta("桌子") == {}
    assert emotion_effect_delta(None) == {}


def test_emotion_table_only_keeps_nonempty_known_fields():
    table = load_emotion_effects()
    assert table  # starter set present
    for word, delta in table.items():
        assert delta  # only non-empty entries are kept
        assert set(delta).issubset({"mood", "stress", "social", "fun", "affection"})


def test_emotion_affection_delta_directional():
    # warm emotions raise affection toward the addressed person, hostile lower it
    assert emotion_affection_delta("喜欢") > 0
    assert emotion_affection_delta("厌恶") < 0
    # self stat accessor never leaks the affection field
    assert "affection" not in emotion_effect_delta("喜欢")
    assert emotion_affection_delta("无聊") == 0  # no affection on a non-relational mood
