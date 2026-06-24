class SpendLedger:
    def __init__(self):
        self.entries = []
        
    def record(self, role, worker, model, executor, cost):
        self.entries.append({
            "role": role,
            "worker": worker,
            "model": model,
            "executor": executor,
            "cost": cost
        })
        
    def get_total(self):
        return sum(e["cost"] for e in self.entries)
