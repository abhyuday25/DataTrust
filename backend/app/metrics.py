"""Small process-local operational counters, without prompts or result data."""

from collections import Counter, defaultdict
from threading import Lock


class Metrics:
    def __init__(self):
        self.lock = Lock()
        self.counts = Counter()
        self.latencies = defaultdict(list)

    def count(self, name: str, amount: int = 1):
        with self.lock:
            self.counts[name] += amount

    def observe(self, stage: str, duration_ms: float):
        with self.lock:
            self.latencies[stage].append(duration_ms)
            if len(self.latencies[stage]) > 1000:
                self.latencies[stage] = self.latencies[stage][-1000:]

    def snapshot(self):
        with self.lock:
            return {'counts': dict(self.counts), 'stage_latency_ms': {
                name: {'count': len(values), 'average': round(sum(values) / len(values), 2)}
                for name, values in self.latencies.items() if values}}
