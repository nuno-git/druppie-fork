"""Dev VM domain models.

Naming convention (matches the rest of the codebase):
- DevVMSummary: lightweight, for list views
- DevVMDetail: full data, for single-item views (inherits Summary)
- DevVMCreate: request body for creating a dev VM
- DevVMListResponse: paginated list wrapper
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DevVMSummary(BaseModel):
    """Lightweight dev VM for lists and embedding."""

    id: UUID
    name: str
    branch: str
    status: str
    created_at: datetime


class DevVMDetail(DevVMSummary):
    """Full dev VM with container + Guacamole details. Inherits from DevVMSummary."""

    owner_id: UUID
    container_id: str | None = None
    container_name: str | None = None
    guacamole_connection_id: str | None = None
    ssh_port: int | None = None
    rdp_port: int | None = None
    guacamole_url: str | None = None  # deep-link to open the VM in Guacamole
    updated_at: datetime | None = None


class DevVMCreate(BaseModel):
    """Request body for creating a new dev VM."""

    name: str
    branch: str


class DevVMListResponse(BaseModel):
    """Paginated dev VM list response."""

    items: list[DevVMSummary]
    total: int
    page: int
    limit: int
