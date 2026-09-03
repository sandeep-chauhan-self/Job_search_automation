"""Guards on what gets typed into real job applications.

A wrong value here is a false statement to an employer, so these cases matter
more than ordinary unit tests.
"""

import pytest

from src.auto_applier.question_answerer import QuestionAnswerer


class ExplodingLLM:
    """Fails loudly so a test can prove the saved-answer path was not used."""

    def __init__(self):
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append(prompt)
        return "LLM_ANSWER"


PROFILE = {
    "personal": {"name": "Test User"},
    "skills": {
        "languages": ["Python", "JavaScript"],
        "frameworks": ["React"],
        "tools": ["Docker"],
    },
}

ANSWERS = [
    {"pattern": "years of experience", "answer": "6", "generic": True},
    {"pattern": "expected salary", "answer": "2500000"},
    {"pattern": "current salary", "answer": "2000000"},
    {"pattern": "notice period", "answer": "30 days"},
    {"pattern": "authorized to work", "answer": "Yes"},
]


@pytest.fixture
def qa():
    return QuestionAnswerer(ExplodingLLM(), ANSWERS, PROFILE)


def test_generic_question_uses_saved_answer(qa):
    assert qa._lookup_answer("How many years of experience do you have?") == "6"


@pytest.mark.parametrize(
    "question",
    [
        "How many years of experience do you have with Kubernetes?",
        "How many years of experience do you have with COBOL?",
        "Years of experience in Python?",
        "How many years of experience with AWS?",
        "Years of experience using Terraform?",
    ],
)
def test_skill_specific_questions_never_use_generic_answer(qa, question):
    # Answering "6" here would claim 6 years of a named technology.
    assert qa._lookup_answer(question) is None, f"generic answer leaked into: {question}"


def test_skill_specific_question_falls_through_to_grounded_llm(qa):
    answer = qa.get_answer("How many years of experience do you have with COBOL?", "number")
    assert answer == "LLM_ANSWER"
    assert qa.llm.calls, "must consult the profile-grounded path instead of guessing"
    assert "Do NOT fabricate" in qa.llm.calls[0]


def test_current_and_expected_salary_are_distinct(qa):
    assert qa._lookup_answer("What is your current salary?") == "2000000"
    assert qa._lookup_answer("What is your expected salary?") == "2500000"


def test_longer_pattern_wins_over_shorter(qa):
    answers = [
        {"pattern": "salary", "answer": "GENERIC"},
        {"pattern": "expected salary", "answer": "SPECIFIC"},
    ]
    specific = QuestionAnswerer(ExplodingLLM(), answers, PROFILE)
    assert specific._lookup_answer("What is your expected salary?") == "SPECIFIC"


def test_exclude_if_contains_blocks_match(qa):
    answers = [
        {"pattern": "notice period", "answer": "30 days", "exclude_if_contains": ["negotiable"]}
    ]
    guarded = QuestionAnswerer(ExplodingLLM(), answers, PROFILE)
    assert guarded._lookup_answer("What is your notice period?") == "30 days"
    assert guarded._lookup_answer("Is your notice period negotiable?") is None


def test_answers_are_audited(qa):
    qa.get_answer("How many years of experience do you have?", "number")
    qa.get_answer("Describe a hard problem you solved", "textarea")

    assert [a["source"] for a in qa.audit] == ["saved", "llm"]
    assert qa.audit[0]["answer"] == "6"


def test_llm_failure_returns_blank_rather_than_guessing():
    class DeadLLM:
        def complete(self, **kwargs):
            raise RuntimeError("provider down")

    answerer = QuestionAnswerer(DeadLLM(), ANSWERS, PROFILE)
    # A blank field gets the job queued for manual review; a guess gets submitted.
    assert answerer.get_answer("Something unmapped?", "text") == ""


def test_missing_profile_skills_does_not_crash():
    answerer = QuestionAnswerer(ExplodingLLM(), ANSWERS, {})
    assert answerer._lookup_answer("How many years of experience do you have?") == "6"
