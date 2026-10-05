from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import OfferCandidate, SearchIntent


class DiscoveryProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, intent: SearchIntent, limit: int = 20) -> list[OfferCandidate]:
        raise NotImplementedError
