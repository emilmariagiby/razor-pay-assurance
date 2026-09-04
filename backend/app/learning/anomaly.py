import os
import joblib
from typing import List

from app.learning.features import OutcomeFeatures

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")
ANOMALY_MODEL_PATH = os.path.join(MODEL_DIR, "anomaly_model.joblib")

class UnknownPatternDetector:
    def __init__(self):
        self.model = None
        self._load_model()
        
    def _load_model(self):
        if os.path.exists(ANOMALY_MODEL_PATH):
            self.model = joblib.load(ANOMALY_MODEL_PATH)
            
    def is_anomaly(self, features: OutcomeFeatures) -> bool:
        """Returns True if the pattern is unknown/anomalous."""
        if self.model is None:
            return False
            
        try:
            vec = [features.to_vector()]
            # IsolationForest returns -1 for outliers and 1 for inliers
            pred = self.model.predict(vec)
            return bool(pred[0] == -1)
        except Exception:
            return False

def train_anomaly_model(X: List[List[float]]):
    """Trains an Isolation Forest and saves it."""
    from sklearn.ensemble import IsolationForest
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    # Train assuming the provided X are all 'normal' (inliers)
    clf = IsolationForest(contamination=0.05, random_state=42)
    clf.fit(X)
    joblib.dump(clf, ANOMALY_MODEL_PATH)
    return clf
