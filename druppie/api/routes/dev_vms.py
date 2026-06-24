"""Dev VMs API routes.

Manages the lifecycle of developer dev VMs (sysbox containers fronted by
Guacamole remote-desktop connections).

Architecture:
    Route (this file)
      │
      └──▶ DevEnvService ──▶ DevVMRepository ──▶ Database
                            └──▶ GuacamoleClient
                            └──▶ docker (sysbox-runc)
"""

from uuid import UUID

from fastapi import APIRouter, Depends
import structlog

from druppie.api.deps import (
    get_current_user,
    get_dev_env_service,
    get_user_roles,
    require_any_role,
)
from druppie.domain import DevVMCreate, DevVMDetail, DevVMListResponse
from druppie.services import DevEnvService

logger = structlog.get_logger()

router = APIRouter()


@router.post("/dev-vms", response_model=DevVMDetail, status_code=201)
async def create_dev_vm(
    body: DevVMCreate,
    service: DevEnvService = Depends(get_dev_env_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> DevVMDetail:
    """Launch a new dev VM.

    Creates a sysbox container with the requested git branch checked out,
    registers a Guacamole RDP connection, and grants the caller READ access.
    Returns the full VM detail including the Guacamole deep-link.
    """
    user_id = UUID(user["sub"])
    username = user.get("preferred_username") or user.get("email")
    user_roles = get_user_roles(user)

    return await service.create_dev_vm(
        owner_id=user_id,
        name=body.name,
        branch=body.branch,
        username=username,
        user_roles=user_roles,
    )


@router.get("/dev-vms", response_model=DevVMListResponse)
async def list_dev_vms(
    page: int = 1,
    limit: int = 20,
    service: DevEnvService = Depends(get_dev_env_service),
    user: dict = Depends(get_current_user),
) -> DevVMListResponse:
    """List dev VMs.

    Admin users see all dev VMs, others see only their own.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    items, total = service.list_dev_vms(
        owner_id=user_id,
        user_roles=user_roles,
        page=page,
        limit=limit,
    )

    return DevVMListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/dev-vms/{vm_id}", response_model=DevVMDetail)
async def get_dev_vm(
    vm_id: UUID,
    service: DevEnvService = Depends(get_dev_env_service),
    user: dict = Depends(get_current_user),
) -> DevVMDetail:
    """Get a single dev VM detail.

    Includes the Guacamole deep-link when a connection has been registered.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    return service.get_dev_vm(
        vm_id=vm_id,
        owner_id=user_id,
        user_roles=user_roles,
    )


@router.delete("/dev-vms/{vm_id}", status_code=204)
async def delete_dev_vm(
    vm_id: UUID,
    service: DevEnvService = Depends(get_dev_env_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
):
    """Stop and remove a dev VM.

    Removes the sysbox container, deletes the Guacamole connection, and marks
    the VM record as stopped. Owner or admin only.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    await service.stop_dev_vm(
        vm_id=vm_id,
        owner_id=user_id,
        user_roles=user_roles,
    )

    return None
