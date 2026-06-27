"""Secret-scrubbing helpers used when persisting :class:`Config` to disk.

Background
----------
``femtobot.config.schema.Config`` inherits from ``pydantic_settings.BaseSettings``
with ``env_prefix="FEMTOBOT_"`` and ``env_nested_delimiter="__"``. That means a
plain ``Config()`` instantiation silently reads env vars like
``FEMTOBOT_PROVIDERS__MINIMAX__API_KEY`` into the matching field. Before the
addition of this module, those env-loaded values were dumped verbatim into
``config.json`` by ``write_default_config()`` and ``save_config()``, so a user
who happened to have ``*_API_KEY`` env vars in their shell (e.g. inherited from
an IDE process) ended up with their credentials persisted in plain text on
disk — and tracked by git if ``!config.json`` was un-ignored.

This module is the second line of defense. Even if a future change un-ignores
``config.json`` again, the secret values themselves are scrubbed to ``None``
before they ever reach disk. The first line of defense is the corrected
``.gitignore`` (see ``create_instance_gitignore``); the second line is here.

Public API
----------
- :data:`DEFAULT_SENSITIVE_FIELDS` — explicit set of field names auto-scrubbed.
- :func:`is_sensitive_field_name` — case-insensitive membership check.
- :func:`count_secrets` — count non-null sensitive values in a JSON-like tree.
- :func:`scrub_secrets` — return a deep-copied tree with sensitive values
  replaced by ``None``; returns ``(scrubbed_copy, scrubbed_count)``.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Sensitive-field catalog
# ---------------------------------------------------------------------------
# Explicit list — NOT a regex — so we never accidentally scrub a legitimate
# field like ``max_tokens`` or ``context_window_tokens``. Extend this set when
# the schema gains new sensitive fields.
DEFAULT_SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "api_key",
        "api_secret",
        "secret",
        "secret_key",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "auth_token",
        "bearer_token",
        "private_key",
        "credential",
        "credentials",
    }
)


def is_sensitive_field_name(name: str, sensitive_names: frozenset[str] | None = None) -> bool:
    """Return True when *name* matches a sensitive field.

    Match rules:
      * case-insensitive
      * underscores stripped (``api_key`` == ``apiKey`` == ``API_KEY``)
      * ``-`` collapsed to ``_`` before comparison (``api-key`` == ``api_key``)

    Args:
        name: Field name to test.
        sensitive_names: Override the catalog. Defaults to
            :data:`DEFAULT_SENSITIVE_FIELDS`.
    """
    catalog = sensitive_names or DEFAULT_SENSITIVE_FIELDS
    return _normalize(name) in {_normalize(n) for n in catalog}


def _normalize(name: str) -> str:
    """Canonical form for field-name comparison.

    Strips ``-`` and ``_`` and lowercases, so all of ``api_key``, ``apiKey``,
    ``Api-Key``, ``API_KEY`` map to the same string ``apikey``.
    """
    return name.replace("-", "_").lower().replace("_", "")


# ---------------------------------------------------------------------------
# Recursive walker
# ---------------------------------------------------------------------------
def _scrub_in_place(
    node: Any,
    sensitive_normalized: set[str],
    out_count: list[int],
) -> Any:
    """Return a scrubbed copy of *node*; increment ``out_count[0]`` per scrub."""
    if isinstance(node, dict):
        scrubbed_dict: dict[Any, Any] = {}
        for key, value in node.items():
            if (
                isinstance(key, str)
                and _normalize(key) in sensitive_normalized
                and value is not None
                and value != ""
            ):
                # Replace the secret value with None. We use None (not "") so
                # downstream code that checks `if p.api_key` keeps working.
                scrubbed_dict[key] = None
                out_count[0] += 1
            else:
                scrubbed_dict[key] = _scrub_in_place(value, sensitive_normalized, out_count)
        return scrubbed_dict
    if isinstance(node, list):
        scrubbed_list: list[Any] = []
        for item in node:
            scrubbed_list.append(_scrub_in_place(item, sensitive_normalized, out_count))
        return scrubbed_list
    return node


def scrub_secrets(
    data: Any,
    sensitive_names: frozenset[str] | None = None,
) -> tuple[Any, int]:
    """Deep-copy *data*, replacing sensitive values with ``None``.

    Args:
        data: JSON-like structure (dict/list/scalar). **Not mutated.**
        sensitive_names: Override catalog. Defaults to
            :data:`DEFAULT_SENSITIVE_FIELDS`.

    Returns:
        Tuple ``(scrubbed_copy, count_of_scrubbed_values)``. ``None`` values
        and empty strings are NOT counted (they are already safe).
    """
    catalog = sensitive_names or DEFAULT_SENSITIVE_FIELDS
    sensitive_normalized = {_normalize(n) for n in catalog}
    counter: list[int] = [0]
    scrubbed = _scrub_in_place(data, sensitive_normalized, counter)
    return scrubbed, counter[0]


def count_secrets(
    data: Any,
    sensitive_names: frozenset[str] | None = None,
) -> int:
    """Count non-null sensitive values in *data* without copying it.

    Useful for emitting warnings before persisting a config: "your config
    contains N secrets; they will be scrubbed from disk".
    """
    _, count = scrub_secrets(data, sensitive_names=sensitive_names)
    return count
