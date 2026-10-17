"""LLM repairs must preserve supplied facts, including numeric claims."""
import pytest

from resume_agent.agents.resume_generator import _guard_structure, _render_template
from resume_agent.schemas import PersonalInfo, Project, Role, UserResume


@pytest.fixture
def draft():
    return _render_template(UserResume(
        personal=PersonalInfo(full_name="Test Candidate", email="test@example.com"),
        experience=[Role(company="Example", title="Engineer", start="2024", bullets=[
            "Build Python automation for operations.", "Reduced latency from 450ms to 90ms.",
        ])],
    ))


def test_rejects_new_unconfirmed_numeric_claim(draft):
    candidate = draft.replace("Build Python automation for operations.",
                              r"Build Python automation for operations, saving 30\% of processing time.")
    assert _guard_structure(candidate, fallback=draft) == draft


def test_rejects_removed_numeric_facts(draft):
    candidate = draft.replace("from 450ms to 90ms", "to 90ms")
    assert _guard_structure(candidate, fallback=draft) == draft


def test_allows_wording_changes_with_same_numeric_facts(draft):
    candidate = draft.replace("Build Python automation", "Develop Python automation")
    assert _guard_structure(candidate, fallback=draft) == candidate


def test_allows_body_spacing_changes_without_changing_facts(draft):
    candidate = draft.replace(r"\vspace{4pt}", r"\vspace{6pt}")
    assert _guard_structure(candidate, fallback=draft) == candidate


def test_avoids_description_that_repeats_project_bullet():
    resume = UserResume(personal=PersonalInfo(full_name="Test", email="test@example.com"), projects=[
        Project(name="Example tool", description="Installable analytics application integrating five agents.",
                bullets=["Shipped an installable analytics application integrating five agents; added regression tests."]),
        Project(name="Example library", description="Open-source contributions to Example library.",
                bullets=["Fixed serialization failures and added regression tests."]),
    ])
    result = _render_template(resume)
    assert r"\resumeItem{Installable analytics application integrating five agents.}" not in result
    assert "Open-source contributions to Example library." not in result
    assert "Shipped an installable analytics" in result
    assert "Fixed serialization failures" in result


def test_preserves_distinct_project_description():
    resume = UserResume(personal=PersonalInfo(full_name="Test", email="test@example.com"), projects=[
        Project(name="Example", description="Tool serving public health researchers.",
                bullets=["Built an asynchronous import pipeline."]),
    ])
    assert "Tool serving public health researchers." in _render_template(resume)


def test_rejects_added_claim_reusing_existing_number(draft):
    candidate = draft.replace("Build Python automation for operations.",
                              "Build Python automation for operations, saving 90ms.")
    assert _guard_structure(candidate, fallback=draft) == draft


def test_rejects_removed_repeated_numeric_fact(draft):
    repeated = draft.replace("Build Python automation for operations.",
                             "Build Python automation serving 90 users.")
    candidate = repeated.replace("Build Python automation serving 90 users.",
                                 "Build Python automation for operations.")
    assert _guard_structure(candidate, fallback=repeated) == repeated
