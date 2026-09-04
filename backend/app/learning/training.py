import os
import uuid
import joblib
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, precision_score, recall_score
from sqlalchemy.orm import Session

from app.db.repository import AssuranceRepository
from app.db.models import ModelVersionModel
from app.learning.features import OutcomeFeatures
from app.learning.external_model import ExternalBehaviorModel, get_latest_external_model
from app.learning.adapters.paysim_adapter import PaySimAdapter
from app.learning.adapters.ieee_cis_adapter import IeeeCisAdapter

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")

class InsufficientDataError(Exception):
    pass

class TrainingService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AssuranceRepository(db)

    def get_learning_status(self) -> dict:
        # 1. Get Verified Outcomes
        records = self.repo.get_memory_records()
        verified_incidents = [r for r in records if r.final_status == "ASSURED" and r.outcome_verified]
        
        # 2. Get Verified Patterns
        from app.db.models import PatternRecordModel
        patterns = self.db.query(PatternRecordModel).all()
        
        # 3. Clean Observations (Risk=0)
        clean_obs = self.repo.get_clean_observations()

        # 4. Active Model
        active_model = self.db.query(ModelVersionModel).filter(ModelVersionModel.status == "ACTIVE").order_by(ModelVersionModel.trained_at.desc()).first()

        risk_1_count = len(verified_incidents)
        risk_0_count = len(clean_obs)
        total_examples = risk_1_count + risk_0_count

        if risk_1_count < 5 or risk_0_count < 5:
            status = "INSUFFICIENT ML TRAINING DATA"
        else:
            status = "READY"

        candidate = self.db.query(ModelVersionModel).filter(ModelVersionModel.status == "CANDIDATE").order_by(ModelVersionModel.trained_at.desc()).first()
        validated = self.db.query(ModelVersionModel).filter(ModelVersionModel.status == "VALIDATED").order_by(ModelVersionModel.trained_at.desc()).first()
        
        pending_model = validated or candidate
        ext_model = get_latest_external_model()

        return {
            "status": status,
            "verified_outcomes": len(verified_incidents),
            "verified_patterns": len(patterns),
            "ml_training_examples": total_examples,
            "active_version": active_model.model_version if active_model else "v1.0.0 (Base)",
            "pending_model": {
                "version": pending_model.model_version,
                "status": pending_model.status,
                "f1": pending_model.validation_f1,
                "precision": pending_model.precision,
                "recall": pending_model.recall,
            } if pending_model else None,
            "external_model": {
                "version": ext_model.version,
                "status": "ACTIVE (Advisory)"
            } if ext_model else None
        }

    def train_candidate_model(self) -> dict:
        records = self.repo.get_memory_records()
        verified_incidents = [r for r in records if r.final_status == "ASSURED" and r.outcome_verified]
        clean_obs = self.repo.get_clean_observations()

        if len(verified_incidents) < 5 or len(clean_obs) < 5:
            raise InsufficientDataError("Insufficient verified data for training.")

        X = []
        y = []

        for r in verified_incidents:
            X.append(r.features.to_vector())
            y.append(1)

        for c in clean_obs:
            X.append(c["features"].to_vector())
            y.append(0)

        # Fixed validation gate: random_state=42 ensures reproducibility for comparison
        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

        clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
        clf.fit(X_train, y_train)

        y_pred = clf.predict(X_val)
        
        # We need zero_division=0 to handle cases where it predicts only 1 class
        f1 = f1_score(y_val, y_pred, zero_division=0)
        precision = precision_score(y_val, y_pred, zero_division=0)
        recall = recall_score(y_val, y_pred, zero_division=0)

        version = f"v_candidate_{uuid.uuid4().hex[:6]}"
        os.makedirs(MODEL_DIR, exist_ok=True)
        artifact_path = os.path.join(MODEL_DIR, f"risk_model_{version}.joblib")
        joblib.dump(clf, artifact_path)

        # Gate Evaluation
        # We require Recall >= 0.80 and Precision >= 0.70
        # For a real system we'd compare to ACTIVE model's metrics on this exact same validation set.
        
        status = "VALIDATED"
        if recall < 0.80 or precision < 0.70:
            status = "REJECTED"

        model_record = ModelVersionModel(
            model_version=version,
            status=status,
            training_example_count=len(X),
            validation_f1=float(f1),
            precision=float(precision),
            recall=float(recall),
            artifact_path=artifact_path
        )
        self.db.add(model_record)
        self.db.commit()

        return {
            "version": version,
            "status": status,
            "f1": f1,
            "precision": precision,
            "recall": recall
        }

    def promote_model(self, version: str) -> None:
        model = self.db.query(ModelVersionModel).filter(ModelVersionModel.model_version == version).first()
        if not model or model.status != "VALIDATED":
            raise ValueError(f"Model {version} cannot be promoted.")
        
        # Demote current ACTIVE
        active = self.db.query(ModelVersionModel).filter(ModelVersionModel.status == "ACTIVE").all()
        for a in active:
            a.status = "ARCHIVED"
            
        model.status = "ACTIVE"
        self.db.commit()

        # Update the symlink or copy to the standard path so RiskModel loads it
        standard_path = os.path.join(MODEL_DIR, "risk_model.joblib")
        import shutil
        shutil.copy2(model.artifact_path, standard_path)
