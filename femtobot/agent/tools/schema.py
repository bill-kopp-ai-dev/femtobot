"""JSON Schema fragment types: all subclass :class:`~femtobot.agent.tools.base.Schema` for descriptions and constraints on tool parameters.

- ``to_json_schema()``: returns a dict compatible with :meth:`~femtobot.agent.tools.base.Schema.validate_json_schema_value` /
  :class:`~femtobot.agent.tools.base.Tool`.
- ``validate_value(value, path)``: validates a single value against this schema; returns a list of error messages (empty means valid).

Shared validation and fragment normalization are on the class methods of :class:`~femtobot.agent.tools.base.Schema`.

Note: Python does not allow subclassing ``bool``, so booleans use :class:`BooleanSchema`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from femtobot.agent.tools.base import Schema


class StringSchema(Schema):
    """String parameter: ``description`` documents the field; optional length bounds and enum."""

    def __init__(
        self,
        description: str = "",
        *,
        min_length: int | None = None,
        max_length: int | None = None,
        enum: tuple[Any, ...] | list[Any] | None = None,
        nullable: bool = False,
    ) -> None:
        self._description = description
        self._min_length = min_length
        self._max_length = max_length
        self._enum = tuple(enum) if enum is not None else None
        self._nullable = nullable

    def _base_schema(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "string"}
        if self._min_length is not None:
            d["minLength"] = self._min_length
        if self._max_length is not None:
            d["maxLength"] = self._max_length
        return d


class IntegerSchema(Schema):
    """Integer parameter: optional placeholder int (legacy ctor signature), description, and bounds."""

    def __init__(
        self,
        value: int = 0,
        *,
        description: str = "",
        minimum: int | None = None,
        maximum: int | None = None,
        enum: tuple[int, ...] | list[int] | None = None,
        nullable: bool = False,
    ) -> None:
        self._value = value
        self._description = description
        self._minimum = minimum
        self._maximum = maximum
        self._enum = tuple(enum) if enum is not None else None
        self._nullable = nullable

    def _base_schema(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "integer"}
        if self._minimum is not None:
            d["minimum"] = self._minimum
        if self._maximum is not None:
            d["maximum"] = self._maximum
        return d


class NumberSchema(Schema):
    """Numeric parameter (JSON number): description and optional bounds."""

    def __init__(
        self,
        value: float = 0.0,
        *,
        description: str = "",
        minimum: float | None = None,
        maximum: float | None = None,
        enum: tuple[float, ...] | list[float] | None = None,
        nullable: bool = False,
    ) -> None:
        self._value = value
        self._description = description
        self._minimum = minimum
        self._maximum = maximum
        self._enum = tuple(enum) if enum is not None else None
        self._nullable = nullable

    def _base_schema(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "number"}
        if self._minimum is not None:
            d["minimum"] = self._minimum
        if self._maximum is not None:
            d["maximum"] = self._maximum
        return d


class BooleanSchema(Schema):
    """Boolean parameter (standalone class because Python forbids subclassing ``bool``)."""

    def __init__(
        self,
        *,
        description: str = "",
        default: bool | None = None,
        nullable: bool = False,
    ) -> None:
        self._description = description
        self._default = default
        self._nullable = nullable

    def _base_schema(self) -> dict[str, Any]:
        return {"type": "boolean"}


class ArraySchema(Schema):
    """Array parameter: element schema is given by ``items``."""

    def __init__(
        self,
        items: Any | None = None,
        *,
        description: str = "",
        min_items: int | None = None,
        max_items: int | None = None,
        nullable: bool = False,
    ) -> None:
        self._items_schema: Any = items if items is not None else StringSchema("")
        self._description = description
        self._min_items = min_items
        self._max_items = max_items
        self._nullable = nullable

    def _base_schema(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "array",
            "items": Schema.fragment(self._items_schema),
        }
        if self._min_items is not None:
            d["minItems"] = self._min_items
        if self._max_items is not None:
            d["maxItems"] = self._max_items
        return d


class ObjectSchema(Schema):
    """Object parameter: ``properties`` or keyword args are field names; values are child Schema or JSON Schema dicts."""

    def __init__(
        self,
        properties: Mapping[str, Any] | None = None,
        *,
        required: list[str] | None = None,
        description: str = "",
        additional_properties: bool | dict[str, Any] | None = None,
        nullable: bool = False,
        **kwargs: Any,
    ) -> None:
        self._properties = dict(properties or {}, **kwargs)
        self._required = list(required or [])
        self._description = description
        self._additional_properties = additional_properties
        self._nullable = nullable

    def _base_schema(self) -> dict[str, Any]:
        props = {k: Schema.fragment(v) for k, v in self._properties.items()}
        out: dict[str, Any] = {"type": "object", "properties": props}
        if self._required:
            out["required"] = self._required
        if self._additional_properties is not None:
            out["additionalProperties"] = self._additional_properties
        return out


def tool_parameters_schema(
    *,
    required: list[str] | None = None,
    description: str = "",
    **properties: Any,
) -> dict[str, Any]:
    """Build root tool parameters ``{"type": "object", "properties": ...}`` for :meth:`Tool.parameters`."""
    return ObjectSchema(
        required=required,
        description=description,
        **properties,
    ).to_json_schema()
