"""Trusted source locations derived from the installed pyUltroid package."""

from pathlib import Path


# Executable and trust-policy paths must never depend on the writable cwd or
# service-controlled environment. In managed installs this resolves through
# /opt/boudyos/current to the root-owned release selected by the deployer.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_PLUGINS = SOURCE_ROOT / "plugins"
OFFICIAL_ASSISTANT = SOURCE_ROOT / "assistant"
OFFICIAL_STRINGS = SOURCE_ROOT / "strings"
SOURCE_RESOURCES = SOURCE_ROOT / "resources"
TRUSTED_ADDON_REGISTRY = SOURCE_RESOURCES / "security" / "trusted-addons.json"


def source_resource(*parts: str) -> Path:
    """Return an immutable bundled resource path."""
    return SOURCE_RESOURCES.joinpath(*parts)
