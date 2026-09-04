import os
import joblib
from typing import Dict, Any, Optional

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")
EXTERNAL_MODEL_PATH = os.path.join(MODEL_DIR, "external_behavior_model.joblib")

class ExternalBehaviorModel:
    """
    A separate ML model that learns strictly from external behavioral representations.
    It produces an advisory external_behavior_signal.
    This class handles inference only. Offline training happens via Notebooks.
    """
    
    def __init__(self):
        self.model = None
        self.load()

    def load(self):
        """Load the offline-trained model if it exists."""
        if os.path.exists(EXTERNAL_MODEL_PATH):
            self.model = joblib.load(EXTERNAL_MODEL_PATH)
            
    @property
    def version(self) -> str:
        return "offline_notebook_v1" if self.model else "unavailable"

    def predict_signal(self, features: Dict[str, Any]) -> float:
        """
        Takes a dict of features matching the external representation
        and returns the advisory probability (external_behavior_signal).
        """
        if not self.model:
            return 0.0
            
        keys = sorted(features.keys())
        vector = [[float(features.get(k, 0.0)) for k in keys]]
        
        try:
            prob = self.model.predict_proba(vector)[0]
            if len(prob) > 1:
                return float(prob[1])
            return 0.0 if self.model.classes_[0] == 0 else 1.0
        except Exception:
            return 0.0
        
def get_latest_external_model() -> Optional[ExternalBehaviorModel]:
    if not os.path.exists(EXTERNAL_MODEL_PATH):
        return None
    
    model = ExternalBehaviorModel()
    return model
