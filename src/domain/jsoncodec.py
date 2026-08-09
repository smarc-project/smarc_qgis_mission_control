from enum import Enum
from typing import Any, get_args, get_origin

from .schema import SchemaMixin


class JsonCodec:
    @staticmethod
    def encodeSchema(obj: SchemaMixin):
        data = {}
        for field in obj.schema().fields:
            value = field.value(obj)
            data[field.jsonName()] = JsonCodec.encode(value, field.baseType)

        return data

    @staticmethod
    def decodeSchema(cls, data: dict, /, extra_kwargs: dict[str, Any] | None = None):
        kwargs = dict(extra_kwargs or {})
        for field in cls.schema().fields:
            raw = data[field.jsonName()]
            kwargs[field.name] = JsonCodec.decode(raw, field.baseType)

        return cls(**kwargs)

    @staticmethod
    def encode(value: Any, typ: Any):
        if get_origin(typ) is list:
            (innerType,) = get_args(typ)
            return [JsonCodec.encode(item, innerType) for item in value]

        if isinstance(typ, type):
            if issubclass(typ, Enum):
                return value.value
            if issubclass(typ, SchemaMixin):
                return value.toJson()

        if typ in (str, int, float, bool):
            return value

        raise TypeError(f"Cannot encode type: {typ!r}")

    @staticmethod
    def decode(raw: Any, typ: Any):
        if get_origin(typ) is list:
            (innerType,) = get_args(typ)
            return [JsonCodec.decode(item, innerType) for item in raw]

        if isinstance(typ, type):
            if issubclass(typ, Enum):
                return typ(raw)
            if issubclass(typ, SchemaMixin):
                return typ.fromJson(raw)

        if typ in (int, float, str, bool):
            return typ(raw)

        raise TypeError(f"Cannot decode type: {typ!r}")
