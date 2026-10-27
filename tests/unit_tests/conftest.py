import pytest

from tests.unit_tests.fakes import Pipeline


@pytest.fixture
def pipeline() -> Pipeline:
    return Pipeline()
