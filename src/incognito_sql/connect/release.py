"""Which published release a client's entry may fetch: none for a development install."""

import json
from importlib.metadata import PackageNotFoundError, distribution


def release() -> str | None:
    """Return the installed version if it is a published release, else None.

    An editable install (a checkout), the checkout's 0.0.0, a development or local
    version is no release: uvx would fetch something else under that name, or nothing.
    """
    try:
        dist = distribution("incognito-sql")
    except PackageNotFoundError:
        return None
    try:
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
    except ValueError:
        return None
    info = direct.get("dir_info") if isinstance(direct, dict) else None
    version = dist.version
    if (isinstance(info, dict) and info.get("editable")) or version == "0.0.0":
        return None
    return None if "dev" in version or "+" in version else version
