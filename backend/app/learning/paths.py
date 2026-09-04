from __future__ import annotations

from typing import Any
from app.learning.memory import OutcomeRecord
from app.cases.assurance import AssuranceCase

class RecommendationEngine:
    def __init__(self, repository) -> None:
        self.repository = repository

    def recommend(self, case: AssuranceCase) -> dict[str, Any]:
        """
        Historical outcome retrieval + similarity + solution-path ranking.
        Does NOT use ML yet, it's deterministic retrieval of verified historical outcomes.
        """
        all_records = self.repository.get_memory_records()
        
        # 1. Similarity: Filter by exact violation type
        # We only consider records that have been resolved and VERIFIED.
        # Unverified records should not contribute to the "success" history.
        similar_records = [
            r for r in all_records
            if case.violation_type and r.violation_type == case.violation_type.value
            and r.case_id != case.case_id
        ]
        
        if not similar_records:
            return {
                "similar_cases": 0,
                "confidence": None,
                "reason": "Insufficient verified historical outcomes"
            }

        # 2. Path Statistics
        paths: dict[str, dict] = {}
        for r in similar_records:
            # We must have an actual action taken to evaluate the path
            action = r.actual_action
            if not action:
                continue
                
            if action not in paths:
                paths[action] = {
                    "attempts": 0,
                    "successes": 0,
                    "durations": []
                }
                
            paths[action]["attempts"] += 1
            if r.outcome_verified and r.final_status == "ASSURED":
                paths[action]["successes"] += 1
                if r.resolution_duration_seconds is not None:
                    paths[action]["durations"].append(r.resolution_duration_seconds)
                    
        if not paths:
            return {
                "similar_cases": len(similar_records),
                "confidence": None,
                "reason": "Similar cases found, but none have actionable resolution paths."
            }

        # 3. Ranking
        best_action = None
        best_success_rate = -1.0
        best_stats = None
        
        for action, stats in paths.items():
            success_rate = stats["successes"] / stats["attempts"]
            # Rank primarily by success rate, then by number of successes
            if success_rate > best_success_rate or (success_rate == best_success_rate and stats["successes"] > (best_stats["successes"] if best_stats else -1)):
                best_success_rate = success_rate
                best_action = action
                best_stats = stats

        if best_stats is None or best_stats["successes"] == 0:
            return {
                "similar_cases": len(similar_records),
                "confidence": None,
                "reason": "Insufficient verified successful outcomes."
            }
            
        avg_duration = sum(best_stats["durations"]) / len(best_stats["durations"]) if best_stats["durations"] else 0.0

        return {
            "recommended_action": best_action,
            "confidence": round(best_success_rate, 2),
            "similar_cases": len(similar_records),
            "successful_cases": best_stats["successes"],
            "success_rate": round(best_success_rate, 3),
            "average_resolution_seconds": round(avg_duration, 1),
            "reason": f"{best_stats['successes']} of {len(similar_records)} similar verified cases used this path successfully"
        }
