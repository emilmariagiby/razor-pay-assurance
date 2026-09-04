import os
import joblib
from typing import List

from app.learning.features import OutcomeFeatures

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")
RISK_MODEL_PATH = os.path.join(MODEL_DIR, "risk_model.joblib")

class KnownActionRiskModel:
    def __init__(self):
        self.model = None
        self._load_model()
        
    def _load_model(self):
        if os.path.exists(RISK_MODEL_PATH):
            self.model = joblib.load(RISK_MODEL_PATH)
            
    def predict_risk(self, features: OutcomeFeatures) -> float:
        if self.model is None:
            return -1.0
        try:
            vec = [features.to_vector()]
            probas = self.model.predict_proba(vec)
            if len(probas[0]) > 1:
                return float(probas[0][1])
            else:
                return 0.0 if self.model.classes_[0] == 0 else 1.0
        except Exception:
            return 0.5
            
    def evaluate_risk(self, features: OutcomeFeatures, deterministic_status: str) -> dict:
        """
        Returns separate fields for Assurance risk and external behavioral signal.
        The external signal is advisory only and NEVER overrides deterministic_status.
        """
        from app.learning.external_model import get_latest_external_model
        
        assurance_risk = self.predict_risk(features)
        
        # Get external advisory signal
        ext_model = get_latest_external_model()
        ext_signal = None
        if ext_model:
            # We pass a dict mapping of the features
            ext_signal = ext_model.predict_signal(features.to_dict())
            
        return {
            "assurance_risk": assurance_risk,
            "external_behavior_signal": ext_signal,
            "deterministic_status": deterministic_status
        }

def train_risk_model(X: List[List[float]], y: List[int]):
    """Trains a Random Forest and saves it."""
    from sklearn.ensemble import RandomForestClassifier
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    clf.fit(X, y)
    joblib.dump(clf, RISK_MODEL_PATH)
    return clf
