from docintel.config import Settings


def test_settings_read_docintel_prefixed_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOCINTEL_LLM_MODEL", "provider:model")
    monkeypatch.setenv("DOCINTEL_CLASSIFIER_MODEL", "provider:classifier")

    settings = Settings()

    assert settings.llm_model == "provider:model"
    assert settings.classifier_model == "provider:classifier"
