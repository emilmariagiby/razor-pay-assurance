import csv
from typing import List, Dict, Any
from .base import ExternalDatasetAdapter, ExternalBehavioralRecord


class PaySimAdapter(ExternalDatasetAdapter):
    
    @property
    def dataset_name(self) -> str:
        return "PaySim"
        
    @property
    def dataset_version(self) -> str:
        return "1.0"
        
    def load(self, filepath: str) -> List[Dict[str, Any]]:
        records = []
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(row)
        return records

    def normalize(self, raw_records: List[Dict[str, Any]]) -> List[ExternalBehavioralRecord]:
        normalized = []
        
        # Valid transaction types to consider for features
        # Just simple mapping to float
        type_mapping = {
            "CASH_IN": 1.0,
            "CASH_OUT": 2.0,
            "DEBIT": 3.0,
            "PAYMENT": 4.0,
            "TRANSFER": 5.0
        }
        
        for i, row in enumerate(raw_records):
            try:
                # Required columns validation
                required_cols = ["step", "type", "amount", "oldbalanceOrg", "newbalanceOrig", "isFraud"]
                if not all(k in row for k in required_cols):
                    continue
                    
                # Basic behavioral features mapping
                t_type = row["type"]
                type_encoded = type_mapping.get(t_type, 0.0)
                amount = float(row["amount"])
                old_bal = float(row["oldbalanceOrg"])
                new_bal = float(row["newbalanceOrig"])
                balance_delta = new_bal - old_bal
                step = float(row["step"])
                
                # We specifically avoid passing "isFraud" into behavioral_features.
                # The label is strictly isolated.
                is_fraud = int(row["isFraud"])
                
                features = {
                    "paysim_step": step,
                    "paysim_type_enc": type_encoded,
                    "paysim_amount": amount,
                    "paysim_oldbalance": old_bal,
                    "paysim_newbalance": new_bal,
                    "paysim_balance_delta": balance_delta
                }
                
                record = ExternalBehavioralRecord(
                    record_id=f"paysim_{i}_{row.get('nameOrig', 'unknown')}",
                    dataset_name=self.dataset_name,
                    dataset_version=self.dataset_version,
                    source_record_id=row.get("nameOrig", f"row_{i}"),
                    behavioral_features=features,
                    external_fraud_label=is_fraud,
                    external_label_name="isFraud",
                    provenance="data/external/fixtures/paysim_sample.csv" # Simplified provenance
                )
                normalized.append(record)
                
            except (ValueError, TypeError, KeyError):
                # Reject malformed rows
                continue
                
        return normalized
