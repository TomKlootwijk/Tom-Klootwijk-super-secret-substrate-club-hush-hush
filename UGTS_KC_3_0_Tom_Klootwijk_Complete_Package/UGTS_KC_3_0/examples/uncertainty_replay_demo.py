"""Interval, error-budget and event-chain example."""
from ugts_kc3.uncertainty import ErrorBudget, Interval, merkle_event_chain

position = Interval(0.99, 1.01)
velocity = Interval(-0.02, 0.02)
print("position", position)
print("velocity", velocity)

budget = ErrorBudget()
budget.add("model", 1e-3)
budget.add("solver", 1e-5)
budget.add("quantization", 2e-4)
print("worst_case", budget.worst_case())
print("rss", budget.root_sum_square())

print("chain", merkle_event_chain([{"id": "e1", "time": 1.0}, {"id": "e2", "time": 2.0}]))
