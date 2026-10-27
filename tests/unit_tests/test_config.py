from docintel.config import Settings


def test_defaults_are_local_and_use_a_current_model() -> None:
    settings = Settings(_env_file=None)

    assert settings.storage_backend == "local"
    assert settings.llm_output_mode == "prompted"
    assert settings.llm_model.startswith("nim:")
