"""Registro `nombre de adaptador -> clase` (HU002 RF-04)."""

from collections.abc import Callable, Iterator, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from availability_hotel.providers.base import BaseProvider


class RegistryError(RuntimeError):
    pass


class ProviderRegistry(Mapping[str, type["BaseProvider"]]):
    """Busqueda O(1) por diccionario; los nombres duplicados fallan al arranque."""

    def __init__(self) -> None:
        self._adapters: dict[str, type[BaseProvider]] = {}

    def register(
        self, name: str
    ) -> Callable[[type["BaseProvider"]], type["BaseProvider"]]:
        def decorator(cls: type["BaseProvider"]) -> type["BaseProvider"]:
            if name in self._adapters:
                raise RegistryError(f"adaptador '{name}' registrado dos veces")
            self._adapters[name] = cls
            return cls

        return decorator

    def __getitem__(self, name: str) -> type["BaseProvider"]:
        return self._adapters[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._adapters)

    def __len__(self) -> int:
        return len(self._adapters)


registry = ProviderRegistry()
register_provider = registry.register
