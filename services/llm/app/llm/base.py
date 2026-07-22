from abc import ABC, abstractmethod

from k8s_llm_shared import EvidencePackage, IncidentReport


class BaseLLMProvider(ABC):
    @abstractmethod
    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        ...
