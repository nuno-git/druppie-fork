"""Service-level tests for ProjectService.

Covers the owner-or-admin authz gate on set_house_style. The enum/column/template
layers are tested in test_house_style.py; this file targets the service layer only.
"""

from uuid import UUID
from unittest.mock import MagicMock

import pytest

from druppie.api.errors import AuthorizationError, NotFoundError
from druppie.domain import DocumentHouseStyle
from druppie.services.project_service import ProjectService


OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
ADMIN_ID = UUID("22222222-2222-2222-2222-222222222222")
STRANGER_ID = UUID("33333333-3333-3333-3333-333333333333")
PROJECT_ID = UUID("44444444-4444-4444-4444-444444444444")


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def service(mock_repo):
    return ProjectService(mock_repo)


@pytest.fixture
def existing_project():
    """A project owned by OWNER_ID with the default rijnland style."""
    project = MagicMock()
    project.id = PROJECT_ID
    project.name = "Test Project"
    project.owner_id = OWNER_ID
    project.house_style = DocumentHouseStyle.RIJNLAND
    return project


class TestSetHouseStyle:
    """Owner-or-admin gate for the document house style mutation."""

    def test_owner_can_set_house_style(self, service, mock_repo, existing_project):
        mock_repo.get_by_id.return_value = existing_project
        mock_repo.get_detail.return_value = MagicMock()

        detail = service.set_house_style(
            PROJECT_ID,
            DocumentHouseStyle.HHSK,
            OWNER_ID,
            [],
        )

        mock_repo.set_house_style.assert_called_once_with(PROJECT_ID, DocumentHouseStyle.HHSK)
        mock_repo.commit.assert_called_once()
        assert detail is not None

    def test_admin_can_set_house_style(self, service, mock_repo, existing_project):
        mock_repo.get_by_id.return_value = existing_project
        mock_repo.get_detail.return_value = MagicMock()

        detail = service.set_house_style(
            PROJECT_ID,
            DocumentHouseStyle.HHSK,
            ADMIN_ID,
            ["admin"],
        )

        mock_repo.set_house_style.assert_called_once_with(PROJECT_ID, DocumentHouseStyle.HHSK)
        mock_repo.commit.assert_called_once()
        assert detail is not None

    def test_stranger_is_denied(self, service, mock_repo, existing_project):
        mock_repo.get_by_id.return_value = existing_project

        with pytest.raises(AuthorizationError) as exc_info:
            service.set_house_style(
                PROJECT_ID,
                DocumentHouseStyle.HHSK,
                STRANGER_ID,
                [],
            )

        assert "owner or admin" in str(exc_info.value).lower()
        mock_repo.set_house_style.assert_not_called()
        mock_repo.commit.assert_not_called()

    def test_missing_project_raises_not_found(self, service, mock_repo):
        mock_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            service.set_house_style(
                PROJECT_ID,
                DocumentHouseStyle.HHSK,
                OWNER_ID,
                [],
            )

        assert "project" in str(exc_info.value).lower()
        mock_repo.set_house_style.assert_not_called()
        mock_repo.commit.assert_not_called()

    def test_returns_get_detail_after_update(self, service, mock_repo, existing_project):
        expected_detail = MagicMock()
        mock_repo.get_by_id.return_value = existing_project
        mock_repo.get_detail.return_value = expected_detail

        detail = service.set_house_style(
            PROJECT_ID,
            DocumentHouseStyle.HHSK,
            OWNER_ID,
            [],
        )

        assert detail is expected_detail
        mock_repo.get_detail.assert_called_once_with(PROJECT_ID)
