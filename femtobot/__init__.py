"""
femtobot - A lightweight AI agent framework
"""

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path


def _read_pyproject_version() -> str | None:
    """Read the source-tree version when package metadata is unavailable."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("project", {}).get("version")


def _resolve_version() -> str:
    try:
        return _pkg_version("femtobot")
    except PackageNotFoundError:
        # Source checkouts often import femtobot without installed dist-info.
        return _read_pyproject_version() or "0.0.2"


__version__ = _resolve_version()
__logo__ = r"""
 ███████╗ ███████╗ ███╗   ███╗ ████████╗  ██████╗  ██████╗   ██████╗  ████████╗
 ██╔════╝ ██╔════╝ ████╗ ████║ ╚══██╔══╝ ██╔═══██╗ ██╔══██╗ ██╔═══██╗ ╚══██╔══╝
 █████╗   █████╗   ██╔████╔██║    ██║    ██║   ██║ ██████╔╝ ██║   ██║    ██║
 ██╔══╝   ██╔══╝   ██║╚██╔╝██║    ██║    ██║   ██║ ██╔══██╗ ██║   ██║    ██║
 ██║      ███████╗ ██║ ╚═╝ ██║    ██║    ╚██████╔╝ ██████╔╝ ╚██████╔╝    ██║
 ╚═╝      ╚══════╝ ╚═╝     ╚═╝    ╚═╝     ╚═════╝  ╚═════╝   ╚═════╝     ╚═╝
"""

_LAZY_EXPORTS = {
    "Femtobot": ".femtobot",
    "RunResult": ".femtobot",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is not None:
        from importlib import import_module

        mod = import_module(module_path, __name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val

    # Dynamically import submodules to avoid breaking import lookup under pytest / lazy schema resolution
    submodules = {
        "agent", "api", "bus", "channels", "cli", "command", "config",
        "pairing", "providers", "security", "session", "skills", "templates", "utils"
    }
    if name in submodules:
        from importlib import import_module
        mod = import_module(f".{name}", __name__)
        globals()[name] = mod
        return mod

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Femtobot", "RunResult"]
