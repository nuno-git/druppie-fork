"""Dev VM repository for database access.

Mirrors the project_repository.py pattern: extends BaseRepository, returns
domain models via private ``_to_summary`` / ``_to_detail`` mappers, and uses
the inherited ``self.db`` session.
"""

from uuid import UUID

from ..db.models import DevVM
from ..domain import DevVMDetail, DevVMSummary
from .base import BaseRepository


class DevVMRepository(BaseRepository):
    """Database access for dev VMs."""

    def get_by_id(self, vm_id: UUID) -> DevVM | None:
        """Get raw dev VM model."""
        return self.db.query(DevVM).filter_by(id=vm_id).first()

    def create(
        self,
        name: str,
        branch: str,
        owner_id: UUID,
        status: str = "creating",
    ) -> DevVM:
        """Create a new dev VM record."""
        vm = DevVM(
            name=name,
            branch=branch,
            owner_id=owner_id,
            status=status,
        )
        self.db.add(vm)
        self.db.flush()
        return vm

    def update(self, vm_id: UUID, **fields: object) -> None:
        """Update dev VM fields by id."""
        if not fields:
            return
        self.db.query(DevVM).filter_by(id=vm_id).update(fields)

    def list_for_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DevVMSummary], int]:
        """List dev VMs for a user."""
        query = self.db.query(DevVM).filter_by(owner_id=user_id)
        total = query.count()
        vms = (
            query.order_by(DevVM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(vm) for vm in vms], total

    def list_all(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DevVMSummary], int]:
        """List all dev VMs (for admin)."""
        query = self.db.query(DevVM)
        total = query.count()
        vms = (
            query.order_by(DevVM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(vm) for vm in vms], total

    def get_detail(self, vm_id: UUID) -> DevVMDetail | None:
        """Get full dev VM detail (without Guacamole URL — service fills that)."""
        vm = self.get_by_id(vm_id)
        if not vm:
            return None
        return self._to_detail(vm)

    def delete(self, vm_id: UUID) -> None:
        """Delete dev VM record."""
        self.db.query(DevVM).filter_by(id=vm_id).delete()

    def _to_summary(self, vm: DevVM) -> DevVMSummary:
        """Convert dev VM model to summary domain object."""
        return DevVMSummary(
            id=vm.id,
            name=vm.name,
            branch=vm.branch,
            status=vm.status,
            created_at=vm.created_at,
            guacamole_connection_id=vm.guacamole_connection_id,
        )

    def _to_detail(self, vm: DevVM) -> DevVMDetail:
        """Convert dev VM model to detail domain object."""
        return DevVMDetail(
            id=vm.id,
            name=vm.name,
            branch=vm.branch,
            status=vm.status,
            created_at=vm.created_at,
            owner_id=vm.owner_id,
            container_id=vm.container_id,
            container_name=vm.container_name,
            guacamole_connection_id=vm.guacamole_connection_id,
            ssh_port=vm.ssh_port,
            rdp_port=vm.rdp_port,
            rdp_username=vm.rdp_username,
            # rdp_password is not surfaced through the domain layer (secret).
            guacamole_url=None,  # filled by service from guacamole_connection_id
            updated_at=vm.updated_at,
        )
