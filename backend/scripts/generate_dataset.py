import os
import sys
import random
from datetime import timedelta
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.ensemble import RandomForestClassifier, IsolationForest

# Adjust path so we can import backend modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simulator.scenarios import all_scenarios
from app.learning.features import extract_features
from app.learning.risk_model import train_risk_model, MODEL_DIR, RISK_MODEL_PATH
from app.learning.anomaly import train_anomaly_model, ANOMALY_MODEL_PATH
import joblib

def generate_synthetic_data(num_samples=1000):
    streams = list(all_scenarios().values())
    X = []
    y = [] # 1 for risk/unresolved, 0 for resolved
    
    print(f"Generating {num_samples} synthetic samples from {len(streams)} base scenarios...")
    
    from app.engine import AssuranceEngine
    engine = AssuranceEngine()
    
    for i in range(num_samples):
        # Pick a base stream
        stream = random.choice(streams)
        
        # Evaluate to get the case
        cases = engine.investigate(stream)
        case = cases[0] if cases else None
        
        if not case:
            continue
            
        features = extract_features(case, stream)
        vec = features.to_vector()
        
        # Add random noise to continuous features to simulate variation
        vec[2] += random.randint(-1, 2)
        if vec[2] < 1: vec[2] = 1
        
        vec[7] += random.uniform(-1000.0, 5000.0) # exposure jitter
        if vec[7] < 0: vec[7] = 0
        
        # Label heuristic - we must be careful not to make this too perfect, 
        # but for this simulation we use severity as a proxy for true risk.
        if features.severity in ["HIGH", "CRITICAL"] or features.has_timeout:
            label = 1 if random.random() < 0.9 else 0
        else:
            label = 1 if random.random() < 0.1 else 0
            
        X.append(vec)
        y.append(label)
        
    return X, y

def generate_anomalies(num_samples=50):
    """Generate pure nonsense vectors to test Isolation Forest."""
    X_anom = []
    for _ in range(num_samples):
        # Completely random vector matching 10-feature shape:
        # [workflow, severity, event_count, payment_count, capture_count,
        #  agent_action_count, has_timeout, exposure, has_reversal, has_dispute]
        vec = [
            random.uniform(-1, 5),      # workflow (random float instead of valid 0-3)
            random.uniform(-1, 5),      # severity (random float instead of valid 0-3)
            random.randint(20, 100),    # event_count (unnaturally high)
            random.randint(5, 10),      # payment_count (unnaturally high)
            random.randint(5, 10),      # capture_count (unnaturally high)
            random.randint(5, 20),      # agent_action_count
            random.randint(0, 1),       # has_timeout
            random.uniform(-50000, -1), # exposure (negative exposure is anomalous)
            random.randint(0, 1),       # has_reversal
            random.randint(0, 1),       # has_dispute
        ]
        X_anom.append(vec)
    return X_anom

if __name__ == "__main__":
    X, y = generate_synthetic_data(1000)
    
    # Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print("--- 1. Training Known-Action Risk Model (Random Forest) ---")
    clf = train_risk_model(X_train, y_train)
    
    print("Evaluating Risk Model on unseen data...")
    y_pred = clf.predict(X_test)
    print(classification_report(y_test, y_pred, target_names=["Resolved (0)", "Risk (1)"]))
    
    print("--- 2. Training Unknown-Pattern Detector (Isolation Forest) ---")
    # Train Isolation Forest on normal data
    # (Assuming the original scenarios are the 'known' world)
    iso = train_anomaly_model(X)
    
    print("Testing Isolation Forest...")
    # Test on known data
    pred_known = iso.predict(X_test)
    known_flagged = sum(1 for p in pred_known if p == -1)
    print(f"Known scenarios flagged as anomalies: {known_flagged}/{len(X_test)} ({known_flagged/len(X_test):.1%})")
    
    # Test on true anomalies
    X_anom = generate_anomalies(100)
    pred_anom = iso.predict(X_anom)
    anom_flagged = sum(1 for p in pred_anom if p == -1)
    print(f"Pure noise flagged as anomalies: {anom_flagged}/{len(X_anom)} ({anom_flagged/len(X_anom):.1%})")
    
    print("\nModels trained, evaluated, and saved successfully in data/models/.")
