"""Audition scorer to evaluate worker execution statistics and calculate scores."""

from typing import Dict, Any


class AuditionScorer:
    @staticmethod
    def calculate_scores(
        worker_id: str,
        role: str,
        is_success: bool,
        cost_usd: float,
        latency_s: float,
        worker_risk: str = "medium"
    ) -> dict[str, float]:
        """Compute the scores across the 8 required dimensions."""
        
        # 1. success_rate
        success_rate = 1.0 if is_success else 0.0
        
        # 2. cost_score: Free is 1.0, cheap is 0.8, medium 0.6, high 0.3
        if cost_usd == 0.0:
            cost_score = 1.0
        elif cost_usd < 0.05:
            cost_score = 0.8
        elif cost_usd < 0.15:
            cost_score = 0.6
        else:
            cost_score = 0.3
            
        # 3. latency_score: fast is better
        # 0.2s is 1.0, 10s or more is 0.1
        latency_score = max(0.1, min(1.0, 1.0 - (latency_s / 12.0)))
        
        # 4. safety_score: inversely proportional to worker risk
        if worker_risk.lower() == "low":
            safety_score = 0.95
        elif worker_risk.lower() == "medium":
            safety_score = 0.70
        else:
            safety_score = 0.40
            
        # 5. diff_minimality_score: Coder is scored based on change minimality (simulated here)
        diff_minimality_score = 0.85 if is_success else 0.0
        
        # 6. evidence_quality_score: quality of stdout/evidence artifacts
        evidence_quality_score = 0.90 if is_success else 0.1
        
        # 7. operator_friction_score: interactive prompts have higher friction (simulated here)
        if worker_id in ("claude_code", "aider"):
            operator_friction_score = 0.60
        else:
            operator_friction_score = 0.95  # automated/deterministic has low friction
            
        # 8. role_fit_score: comprehensive score combining all dimensions
        weights = {
            "success_rate": 0.3,
            "cost_score": 0.15,
            "latency_score": 0.15,
            "safety_score": 0.15,
            "diff_minimality_score": 0.05,
            "evidence_quality_score": 0.1,
            "operator_friction_score": 0.1
        }
        
        scores = {
            "success_rate": success_rate,
            "cost_score": cost_score,
            "latency_score": latency_score,
            "safety_score": safety_score,
            "diff_minimality_score": diff_minimality_score,
            "evidence_quality_score": evidence_quality_score,
            "operator_friction_score": operator_friction_score
        }
        
        role_fit_score = sum(scores[dim] * w for dim, w in weights.items())
        scores["role_fit_score"] = round(role_fit_score, 2)
        
        return scores
