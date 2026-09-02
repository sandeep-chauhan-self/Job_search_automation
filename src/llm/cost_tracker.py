from sqlalchemy.sql import func
from src.database.models import LLMUsage

class CostTracker:
    def __init__(self, db_session):
        self.db = db_session

    def get_run_cost(self, run_id: str) -> float:
        cost = self.db.query(func.sum(LLMUsage.cost_usd)).filter(LLMUsage.run_id == run_id).scalar()
        return cost or 0.0

    def get_job_cost(self, job_id: str) -> float:
        cost = self.db.query(func.sum(LLMUsage.cost_usd)).filter(LLMUsage.job_id == job_id).scalar()
        return cost or 0.0

    def get_total_cost(self) -> float:
        cost = self.db.query(func.sum(LLMUsage.cost_usd)).scalar()
        return cost or 0.0
