import csv
from typing import List, Dict, Any
from .base import ExternalDatasetAdapter, ExternalBehavioralRecord


class IeeeCisAdapter(ExternalDatasetAdapter):
    
    @property
    def dataset_name(self) -> str:
        return "IEEE-CIS"
        
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
        
        # Product code mapping
        prod_mapping = {
            "W": 1.0,
            "H": 2.0,
            "C": 3.0,
            "S": 4.0,
            "R": 5.0
        }
        
        for i, row in enumerate(raw_records):
            try:
                # Required columns validation
                required_cols = ["TransactionID", "isFraud", "TransactionDT", "TransactionAmt"]
                if not all(k in row for k in required_cols):
                    continue
                    
                # Behavioral feature subset mapping
                # We don't ingest all hundreds of columns. We extract time, amount, product type.
                dt = float(row["TransactionDT"])
                amt = float(row["TransactionAmt"])
                
                prod_cd = row.get("ProductCD", "")
                prod_encoded = prod_mapping.get(prod_cd, 0.0)
                
                # Card fields if present
                card1 = float(row["card1"]) if row.get("card1") else 0.0
                card2 = float(row["card2"]) if row.get("card2") else 0.0
                
                is_fraud = int(row["isFraud"])
                
                features = {
                    "ieee_dt": dt,
                    "ieee_amt": amt,
                    "ieee_prod_enc": prod_encoded,
                    "ieee_card1": card1,
                    "ieee_card2": card2
                }
                
                record = ExternalBehavioralRecord(
                    record_id=f"ieee_{row['TransactionID']}",
                    dataset_name=self.dataset_name,
                    dataset_version=self.dataset_version,
                    source_record_id=row["TransactionID"],
                    behavioral_features=features,
                    external_fraud_label=is_fraud,
                    external_label_name="isFraud",
                    provenance="data/external/fixtures/ieee_cis_sample.csv"
                )
                normalized.append(record)
                
            except (ValueError, TypeError, KeyError):
                # Reject malformed rows
                continue
                
        return normalized
