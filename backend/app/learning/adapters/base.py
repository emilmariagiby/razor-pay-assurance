from dataclasses import dataclass
from typing import Dict, Any, List
from abc import ABC, abstractmethod


@dataclass
class ExternalBehavioralRecord:
    record_id: str
    dataset_name: str
    dataset_version: str
    source_record_id: str
    
    behavioral_features: Dict[str, Any]
    
    external_fraud_label: int
    external_label_name: str
    
    provenance: str

    def to_vector(self) -> List[float]:
        """
        Converts behavioral_features to a consistent float vector for the External Model.
        The exact ordering depends on how the adapter defines features, so it's 
        best handled by standardizing the features dict keys or sorting them.
        """
        keys = sorted(self.behavioral_features.keys())
        return [float(self.behavioral_features[k]) for k in keys]


class ExternalDatasetAdapter(ABC):
    
    @property
    @abstractmethod
    def dataset_name(self) -> str:
        pass

    @property
    @abstractmethod
    def dataset_version(self) -> str:
        pass

    @abstractmethod
    def load(self, filepath: str) -> List[Dict[str, Any]]:
        """Loads raw data from source (e.g. CSV)."""
        pass
        
    @abstractmethod
    def normalize(self, raw_records: List[Dict[str, Any]]) -> List[ExternalBehavioralRecord]:
        """Maps raw rows into canonical behavioral representations."""
        pass
        
    def validate(self, records: List[ExternalBehavioralRecord]) -> List[ExternalBehavioralRecord]:
        """Filters out malformed or incomplete records."""
        valid = []
        for r in records:
            if r.external_fraud_label not in [0, 1]:
                continue
            if not isinstance(r.behavioral_features, dict):
                continue
            # Optionally validate all feature values are numeric
            try:
                for k, v in r.behavioral_features.items():
                    float(v)
                valid.append(r)
            except (ValueError, TypeError):
                continue
        return valid

    def ingest(self, filepath: str) -> List[ExternalBehavioralRecord]:
        """Full pipeline: load -> normalize -> validate"""
        raw = self.load(filepath)
        records = self.normalize(raw)
        return self.validate(records)
