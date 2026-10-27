from pydantic_ai import models

models.ALLOW_MODEL_REQUESTS = False  # no test can reach a provider by accident
