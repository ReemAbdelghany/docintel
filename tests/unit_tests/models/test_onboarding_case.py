from uuid import uuid4

import pytest

from docintel.models.errors import InvariantViolated
from docintel.models.events import DocumentSubmitted
from docintel.models.onboarding_case import OnboardingCase


def test_a_new_document_is_added_and_announced() -> None:
    case = OnboardingCase(uuid4())

    document, created = case.submit("a.pdf", "hash-a", "local://raw/a")

    assert created
    assert case.documents == [document]
    assert [type(e) for e in case.pull_events()] == [DocumentSubmitted]


def test_a_duplicate_content_hash_returns_the_original_without_an_event() -> None:
    case = OnboardingCase(uuid4())
    original, _ = case.submit("a.pdf", "hash-a", "local://raw/a")
    case.pull_events()

    again, created = case.submit("renamed.pdf", "hash-a", "local://raw/a")

    assert not created
    assert again == original
    assert case.pull_events() == []


def test_a_closed_case_accepts_no_submissions() -> None:
    case = OnboardingCase(uuid4())
    case.close()

    with pytest.raises(InvariantViolated):
        case.submit("a.pdf", "hash-a", "local://raw/a")
