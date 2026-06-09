from __future__ import annotations

from app.llm.openai_compatible import OpenAICompatibleProvider


def test_model_limit_prefers_provider_scoped_model_key():
    provider = OpenAICompatibleProvider()

    limit = provider._model_limit(
        "https://api.example.com/v1",
        "same-model",
        "Example",
        {
            "model_limits": {
                "same-model": 9,
                "https://api.example.com/v1::same-model": 2,
            }
        },
    )

    assert limit == 2
