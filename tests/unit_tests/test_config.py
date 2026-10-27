"""Unit tests for application configuration settings.

This module tests the default values and behavior of the Settings class
defined in docintel.config. It verifies that the configuration defaults
match the expected local development setup.
"""

from docintel.config import Settings


def test_defaults_are_local_and_use_a_current_model() -> None:
    """Verify default settings use local storage and a current NIM model.

    Creates a Settings instance without loading .env file to test pure defaults.
    Checks that:
    - Storage backend defaults to "local" (filesystem)
    - LLM output mode defaults to "prompted" (JSON in prompt)
    - Primary LLM model uses NVIDIA NIM prefix
    """
    settings = Settings(_env_file=None)

    assert settings.storage_backend == "local"
    assert settings.llm_output_mode == "prompted"
    assert settings.llm_model.startswith("nim:")
