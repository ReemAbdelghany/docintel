"""Agent construction: the structured-output mode is a setting, not a code change."""

from pydantic import BaseModel
from pydantic_ai import Agent, PromptedOutput, ToolOutput
from pydantic_ai.models import Model


def make_agent[T: BaseModel](
    model: Model, mode: str, output_type: type[T], instructions: str, retries: int = 2
) -> Agent[None, T]:
    """'tool' sends the schema as a function the model must call; 'prompted' inlines it."""
    output = ToolOutput(output_type) if mode == "tool" else PromptedOutput(output_type)
    return Agent(
        model,
        output_type=output,
        instructions=instructions,
        retries=retries,
        # Some models split one answer across parallel calls to the output tool and only the
        # first call is used, silently dropping fields. OpenAI honors this setting; NVIDIA NIM
        # does not, so for Nemotron on NIM use output mode "prompted".
        model_settings={"parallel_tool_calls": False},
    )
