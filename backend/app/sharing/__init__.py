"""Viewer-only live sharing through a bounded external relay."""

from .manager import ShareRelayError, ShareRelayManager, sanitize_share_event

__all__ = ["ShareRelayError", "ShareRelayManager", "sanitize_share_event"]
