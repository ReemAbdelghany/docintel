from docintel.config import Settings


def test_settings_read_docintel_prefixed_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOCINTEL_LLM_MODEL", "provider:model")
    monkeypatch.setenv("DOCINTEL_CLASSIFIER_MODEL", "provider:classifier")

    settings = Settings(_env_file=None)

    assert settings.llm_model == "provider:model"
    assert settings.classifier_model == "provider:classifier"


def test_providers_default_to_local_storage_docling_and_tool_output(monkeypatch) -> None:
    monkeypatch.setenv("DOCINTEL_LLM_MODEL", "nim:meta/llama-3.3-70b-instruct")
    monkeypatch.setenv("DOCINTEL_CLASSIFIER_MODEL", "nim:meta/llama-3.3-70b-instruct")

    settings = Settings(_env_file=None)

    assert settings.storage_backend == "local"
    assert settings.parser_backend == "docling"
    assert settings.llm_output_mode == "tool"
    assert settings.nvidia_api_key.get_secret_value() == ""
