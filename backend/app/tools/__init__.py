"""Importing this package registers every tool in the registry."""
from app.tools import ingest, output, processing, retrieval  # noqa: F401
from app.tools.registry import TOOLS, ToolRunner, list_tools  # noqa: F401
