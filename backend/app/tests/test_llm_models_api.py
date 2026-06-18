from __future__ import annotations

from app.api.llm import extract_model_ids


def test_extract_model_ids_supports_openai_data_objects():
    payload = {"data": [{"id": "gpt-test"}, {"id": "gpt-test"}, {"id": "mini"}]}

    assert extract_model_ids(payload) == ["gpt-test", "mini"]


def test_extract_model_ids_supports_common_models_shapes():
    assert extract_model_ids({"models": ["alpha", {"name": "beta"}, {"model": "gamma"}]}) == ["alpha", "beta", "gamma"]
    assert extract_model_ids([{"id": "delta"}, "epsilon"]) == ["delta", "epsilon"]


def test_model_url_candidates_accept_common_openai_compatible_urls():
    from app.api.llm import _model_url_candidates

    assert _model_url_candidates("https://api.example.com/v1") == ["https://api.example.com/v1/models"]
    assert _model_url_candidates("https://api.example.com") == [
        "https://api.example.com/models",
        "https://api.example.com/v1/models",
    ]
    assert _model_url_candidates("https://api.example.com/v1/chat/completions") == ["https://api.example.com/v1/models"]
