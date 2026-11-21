"""Central helper for writing ActivityLog rows."""
from __future__ import annotations

import logging

from apps.operations.models import ActivityLog

logger = logging.getLogger("sitesmart.activity")


def get_client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45] or None
    return request.META.get("REMOTE_ADDR") or None


def log_activity(action: str, description: str, *, actor=None, train=None, booking=None,
                 metadata: dict | None = None, request=None) -> ActivityLog:
    """Record an auditable event. Never raises: logging must not break a workflow."""
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    category = ActivityLog.CATEGORY_FOR_ACTION.get(str(action), ActivityLog.Category.ADMIN)
    try:
        return ActivityLog.objects.create(
            actor=actor,
            action=action,
            category=category,
            description=description[:300],
            train=train,
            booking=booking,
            metadata=metadata or {},
            ip_address=get_client_ip(request),
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not write activity log for %s", action)
        return None
