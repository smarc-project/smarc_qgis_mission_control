from dataclasses import MISSING, dataclass, fields
from enum import Enum
from typing import Annotated, Any, Sequence, get_args, get_origin, get_type_hints

__all__ = [
    "Unit",
    "Column",
    "JsonKey",
    "FieldSpec",
    "Schema",
    "SchemaMixin"
]


@dataclass(frozen=True)
class Unit:
    unit: str


@dataclass(frozen=True)
class Column:
    short: str
    long: str | None = None


@dataclass(frozen=True)
class JsonKey:
    name: str


@dataclass(frozen=True)
class FieldSpec:
    name: str
    baseType: Any
    column: Column | None
    unit: Unit | None
    jsonKey: JsonKey | None

    def label(self, preferLong: bool = True) -> str:
        if not self.column:
            return self.name
        if preferLong and self.column.long is not None:
            return self.column.long
        return self.column.short

    def withUnit(self, text: str) -> str:
        if self.unit:
            return f"{text} [{self.unit.unit}]"
        return text

    def header(self, preferLong = True, unit: bool = True):
        if unit:
            return self.withUnit(self.label(preferLong))
        return self.label(preferLong)

    def type(self) -> Any:
        return self.baseType

    def jsonName(self) -> str:
        if self.jsonKey is None:
            # Automatically convert snake_case to kebab-case
            return self.name.replace("_", "-")
        return self.jsonKey.name

    def choices(self) -> list[Enum] | None:
        if isinstance(self.baseType, type) and issubclass(self.baseType, Enum):
            return list(self.baseType)
        return None

    def value(self, obj: object) -> Any:
        return getattr(obj, self.name)

    def setValue(self, obj: object, value: Any):
        if isinstance(self.baseType, type) and issubclass(self.baseType, Enum):
            try:
                value = self.baseType(value)
            except ValueError: # TODO: enum classes still required though?
                pass # do nothing if entry not a named enum member
        setattr(obj, self.name, value)

# TODO: cache somehow
@dataclass(frozen=True)
class Schema:
    fields: Sequence[FieldSpec]

    # TODO: cache
    @classmethod
    def fromDataclass(cls, dtCls) -> 'Schema':
        def unwrapAnnotated(t: Any):
            meta = []
            while get_origin(t) is Annotated:
                t, *rest = get_args(t)
                meta += rest
            return t, meta

        hints = get_type_hints(dtCls, include_extras=True)
        specs = []
        # Iterating using `fields` retains the field order from class definition
        for f in fields(dtCls):
            hint = hints[f.name]
            # Only `Annotated` fields should be considered
            if hint is None or get_origin(hint) is not Annotated:
                continue
            baseType, meta = unwrapAnnotated(hint)
            # Process annotations from inside out, i.e. outermost takes priority
            unit = None
            column = None
            jsonKey = None
            for arg in reversed(meta):
                if isinstance(arg, Column):
                    column = arg
                elif isinstance(arg, Unit):
                    unit = arg
                elif isinstance(arg, JsonKey):
                    jsonKey = arg

            specs.append(FieldSpec(f.name, baseType, column, unit, jsonKey))

        return cls(specs)

class SchemaMixin:
    """Mixin for classes that are intended to provide a Schema."""
    @classmethod
    def schema(cls) -> Schema:
        """Get a Schema for editing annotated datafields of this class."""
        return Schema.fromDataclass(cls)

    @classmethod
    def requiredFields(cls) -> list[FieldSpec]:
        dataclassFields = {f.name: f for f in fields(cls)}
        return [
            spec for spec in cls.schema().fields
            if dataclassFields[spec.name].default is MISSING
            and dataclassFields[spec.name].default_factory is MISSING
        ]

    def toJson(self) -> dict:
        from .jsoncodec import JsonCodec
        return JsonCodec.encodeSchema(self)

    @classmethod
    def fromJson(cls, data: dict):
        from .jsoncodec import JsonCodec
        return JsonCodec.decodeSchema(cls, data)
