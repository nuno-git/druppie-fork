"""Dev VM database model.

A dev VM is a sysbox-runc container that gives a developer an isolated
remote-desktop-capable environment (SSH, RDP/xrdp, code-server) provisioned
on demand and fronted by a Guacamole connection.
"""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class DevVM(Base):
    """A developer dev VM backed by a sysbox container + Guacamole connection."""

    __tablename__ = "dev_vms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)  # human label, e.g. "dev-jan-vm"
    branch = Column(String(255), nullable=False)  # git branch checked out in the VM
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    container_id = Column(String(128), nullable=True)  # docker container short ID
    container_name = Column(String(255), nullable=True)  # docker container name
    guacamole_connection_id = Column(String(128), nullable=True)  # Guacamole connection identifier
    status = Column(String(32), default="creating")  # creating, running, stopped, error
    ssh_port = Column(Integer, nullable=True)  # host-side SSH port (optional)
    rdp_port = Column(Integer, nullable=True)  # host-side RDP port (for Guacamole)
    rdp_username = Column(String(100), nullable=True)  # per-VM RDP username
    rdp_password = Column(String(255), nullable=True)  # per-VM RDP password
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "branch": self.branch,
            "owner_id": str(self.owner_id) if self.owner_id else None,
            "container_id": self.container_id,
            "container_name": self.container_name,
            "guacamole_connection_id": self.guacamole_connection_id,
            "status": self.status,
            "ssh_port": self.ssh_port,
            "rdp_port": self.rdp_port,
            "rdp_username": self.rdp_username,
            "rdp_password": self.rdp_password,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
