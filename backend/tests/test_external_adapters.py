import os
import pytest
from app.learning.adapters.paysim_adapter import PaySimAdapter
from app.learning.adapters.ieee_cis_adapter import IeeeCisAdapter
from app.learning.external_model import ExternalBehaviorModel

def test_paysim_adapter():
    adapter = PaySimAdapter()
    filepath = os.path.join(os.path.dirname(__file__), "..", "data", "external", "fixtures", "paysim_sample.csv")
    
    if not os.path.exists(filepath):
        pytest.skip("PaySim fixture not found")
        
    records = adapter.ingest(filepath)
    assert len(records) > 0
    assert records[0].dataset_name == "PaySim"
    assert "paysim_amount" in records[0].behavioral_features
    assert hasattr(records[0], "external_fraud_label")
    
def test_ieee_cis_adapter():
    adapter = IeeeCisAdapter()
    filepath = os.path.join(os.path.dirname(__file__), "..", "data", "external", "fixtures", "ieee_cis_sample.csv")
    
    if not os.path.exists(filepath):
        pytest.skip("IEEE-CIS fixture not found")
        
    records = adapter.ingest(filepath)
    assert len(records) > 0
    assert records[0].dataset_name == "IEEE-CIS"
    assert "ieee_amt" in records[0].behavioral_features
    assert hasattr(records[0], "external_fraud_label")

def test_external_model_inference():
    # ExternalBehaviorModel is strictly inference-only.
    model = ExternalBehaviorModel()
    
    # Should not throw errors even if model is not trained/available
    assert model.version == "unavailable"
    signal = model.predict_signal({"some_feature": 1.0})
    assert signal == 0.0
