"""Claims Management System connector interface (spec §8 cms_connector_tool, §10.4)."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session


class CMSConnector(ABC):
    @abstractmethod
    def lookup_policy(self, claim_number: str) -> dict: ...

    @abstractmethod
    def post(self, db: Session, claim_id: str, payload: dict) -> dict: ...


def get_cms_connector() -> CMSConnector:
    kind = os.environ.get("CMS_CONNECTOR", "mock")
    if kind == "mock":
        from app.integrations.cms.mock import MockCMSConnector
        return MockCMSConnector()
    raise RuntimeError(f"CMS connector '{kind}' is not configured")
