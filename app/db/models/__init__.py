"""Model package.

Importing this package registers every mapping on ``Base.metadata`` — which is
what Alembic autogeneration and the metadata-level tests rely on.
"""

from __future__ import annotations

from app.db.models.audit import AuditLog
from app.db.models.call import Call
from app.db.models.contact import Contact
from app.db.models.deal import Deal
from app.db.models.finance import BankStatement, BankTransaction
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.rbac import Permission, Role, RolePermission, UserRole
from app.db.models.setting import OrganizationSetting
from app.db.models.ticket import Ticket, TicketStatusLog
from app.db.models.user import Session, User
from app.db.models.warehouse import StockLevel, StockMovement, Warehouse

__all__ = [
    "AuditLog",
    "BankStatement",
    "BankTransaction",
    "Call",
    "Contact",
    "Deal",
    "Order",
    "OrderItem",
    "OrganizationSetting",
    "Permission",
    "Product",
    "Role",
    "RolePermission",
    "Session",
    "StockLevel",
    "StockMovement",
    "Ticket",
    "TicketStatusLog",
    "User",
    "UserRole",
    "Warehouse",
]
