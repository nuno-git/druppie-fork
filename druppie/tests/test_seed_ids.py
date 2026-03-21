"""Tests for deterministic UUID generation."""

import uuid
from druppie.testing.seed_ids import fixture_uuid, FIXTURE_NAMESPACE


def test_same_inputs_produce_same_uuid():
    a = fixture_uuid("todo-app")
    b = fixture_uuid("todo-app")
    assert a == b


def test_different_inputs_produce_different_uuids():
    a = fixture_uuid("todo-app")
    b = fixture_uuid("weather-app")
    assert a != b


def test_parts_produce_different_uuids():
    session = fixture_uuid("todo-app")
    project = fixture_uuid("todo-app", "project")
    run0 = fixture_uuid("todo-app", "run", 0)
    run1 = fixture_uuid("todo-app", "run", 1)
    assert len({session, project, run0, run1}) == 4


def test_valid_uuid5():
    result = fixture_uuid("test")
    assert isinstance(result, uuid.UUID)
    assert result.version == 5


def test_mixed_part_types():
    result = fixture_uuid("session", "run", 0, "tc", 1)
    assert isinstance(result, uuid.UUID)


def test_namespace_is_valid_uuid():
    assert isinstance(FIXTURE_NAMESPACE, uuid.UUID)
