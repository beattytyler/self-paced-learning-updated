"""Tests for scoped teacher subject assignments in admin authoring flows."""

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import User  # noqa: E402
from services import get_user_service  # noqa: E402


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.app_context():
        with app.test_client() as test_client:
            yield test_client


def _create_teacher_user() -> User:
    token = uuid.uuid4().hex[:8]
    teacher = User(
        username=f"teacher_{token}",
        email=f"teacher_{token}@example.com",
        password_hash="fakehash",
        role="teacher",
        code=f"T{token[:5].upper()}",
        token_balance=0,
    )
    db.session.add(teacher)
    db.session.commit()
    return teacher


def _clear_assignment_store() -> None:
    user_service = get_user_service()
    path = user_service._get_teacher_topic_assignment_store_path()  # noqa: SLF001
    if os.path.exists(path):
        os.remove(path)


def test_admin_can_assign_and_unassign_teacher_subject(client, monkeypatch):
    with app.app_context():
        teacher = _create_teacher_user()
        _clear_assignment_store()

    with client.session_transaction() as sess:
        sess["user_id"] = 999999
        sess["username"] = "admin"
        sess["is_admin"] = True
        sess["role"] = "admin"

    monkeypatch.setattr(
        "blueprints.admin_routes._list_assignable_subjects",
        lambda: [{"subject": "python", "subject_name": "Python"}],
    )

    assign_response = client.post(
        "/admin/teacher-topic-assignments",
        json={"teacher_id": teacher.id, "subject": "python"},
    )
    assert assign_response.status_code == 200
    assert assign_response.get_json().get("success") is True

    list_response = client.get("/admin/teacher-topic-assignments")
    assert list_response.status_code == 200
    payload = list_response.get_json()
    assert payload.get("success") is True
    assignments = payload.get("assignments", [])
    assert any(
        item.get("teacher_id") == teacher.id
        and item.get("subject") == "python"
        for item in assignments
    )

    delete_response = client.delete(
        "/admin/teacher-topic-assignments",
        json={"teacher_id": teacher.id, "subject": "python"},
    )
    assert delete_response.status_code == 200
    assert delete_response.get_json().get("success") is True


def test_scoped_teacher_admin_routes_are_limited_to_assigned_subject(client):
    with app.app_context():
        teacher = _create_teacher_user()
        _clear_assignment_store()
        user_service = get_user_service()
        user_service.assign_teacher_topic(teacher.id, "python")

    with client.session_transaction() as sess:
        sess["user_id"] = teacher.id
        sess["username"] = teacher.username
        sess["is_admin"] = False
        sess["role"] = "teacher"

    allowed = client.get("/admin/quiz/python/functions")
    denied = client.get("/admin/quiz/python/loops")

    assert allowed.status_code == 200
    assert denied.status_code == 403


def test_scoped_teacher_tag_and_subtopic_apis_are_subject_scoped(client):
    with app.app_context():
        teacher = _create_teacher_user()
        _clear_assignment_store()
        user_service = get_user_service()
        user_service.assign_teacher_topic(teacher.id, "python")

    with client.session_transaction() as sess:
        sess["user_id"] = teacher.id
        sess["username"] = teacher.username
        sess["is_admin"] = False
        sess["role"] = "teacher"

    allowed_tags = client.get("/api/subjects/python/tags")
    denied_tags = client.get("/api/subjects/calculus/tags")
    assert allowed_tags.status_code == 200
    assert denied_tags.status_code == 403

    subtopics_response = client.get("/api/subjects/python/subtopics")
    assert subtopics_response.status_code == 200
    subtopics_payload = subtopics_response.get_json()
    subtopics = subtopics_payload.get("subtopics", {})
    assert "functions" in subtopics
    assert all(subtopic_id == "functions" for subtopic_id in subtopics.keys())
