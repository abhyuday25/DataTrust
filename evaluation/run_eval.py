"""Reproducible end-to-end evaluation with a scripted provider and real guard/executor."""

import argparse
import hashlib
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.agents import PlannerAgent, RouterAgent, SQLAgent
from app.core import Settings, create_app
from app.query_models import GeneratedSQL, PlannerResult, RouterResult, Route, Synthesis
from app.query_service import QueryOrchestrator
from app.rag import RagIndex


class ScriptedEmbeddings:
    model = 'eval-hash-16'

    def embed_batch(self, texts):
        return [[(byte - 127.5) / 127.5 for byte in hashlib.sha256(text.encode()).digest()[:16]] for text in texts]


class ScriptedLLM:
    def __init__(self, table, case):
        self.table, self.case = table, case

    def generate_structured(self, system, user, output):
        if output is RouterResult:
            route = Route(self.case.get('route', 'analytics_query'))
            return RouterResult(route=route, requires_database=route == Route.analytics_query,
                requires_visualization=True, confidence=1)
        if output is PlannerResult:
            return PlannerResult(objective=self.case['question'], tables_needed=[self.table], dimensions=[],
                measures=[], filters=[], joins=[], group_by=[], order_by=[], limit=None, assumptions=[])
        if output is GeneratedSQL:
            sql = self.case.get('repair_sql', self.case['sql']) if 'failed_sql' in user else self.case['sql']
            return GeneratedSQL(sql=sql.format(table='"' + self.table + '"'),
                referenced_tables=[self.table], referenced_columns=[], assumptions=[])
        if output is Synthesis:
            return Synthesis(answer='Executed result is shown in the table.', findings=[], assumptions=[])
        raise AssertionError(output)


def equivalent(actual, expected):
    if len(actual) != len(expected):
        return False
    def cell(value):
        return round(value, 6) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    return sorted(json.dumps([cell(v) for v in row]) for row in actual) == sorted(json.dumps([cell(v) for v in row]) for row in expected)


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(q * len(ordered)) - 1], 2)


def run(cases):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        settings = Settings(duckdb_path=root / 'data.duckdb', data_dir=root / 'uploads',
            faiss_index_path=root / 'faiss', cache_similarity_threshold=0.999)
        app = create_app(settings)
        logging.getLogger().setLevel(logging.WARNING)
        client = TestClient(app)
        uploaded = client.post('/api/datasets/upload', files={'file': ('sample_sales.csv', (ROOT / 'data' / 'sample_sales.csv').read_bytes())})
        assert uploaded.status_code == 201, uploaded.text
        dataset_id = uploaded.json()['dataset']['id']
        table = uploaded.json()['table']['name']
        dataset = uploaded.json()['dataset']
        results = []
        conversations = {}
        for case in cases:
            scripted = ScriptedLLM(table, case)
            app.state.query_service = QueryOrchestrator(app.state.datasets, RouterAgent(scripted), PlannerAgent(scripted),
                RagIndex(settings.faiss_index_path, ScriptedEmbeddings()), SQLAgent(scripted), settings,
                app.state.store, app.state.metrics)
            payload = {'dataset_id': dataset_id, 'question': case['question'], 'visualize': True}
            if 'conversation_from' in case:
                payload['conversation_id'] = conversations[case['conversation_from']]
            body = client.post('/api/query', json=payload).json()
            if body.get('conversation_id'):
                conversations[case['id']] = body['conversation_id']
            expected_rows = case.get('expected_rows')
            guard_columns = {item.rsplit('.', 1)[-1] for item in (body.get('validation') or {}).get('referenced_columns', [])}
            guard_tables = set((body.get('validation') or {}).get('referenced_tables', []))
            results.append({'id': case['id'], 'category': case['category'], 'status': body['status'],
                'expected_status': case['expected_status'], 'route_correct': body['route']['route'] == case.get('route', 'analytics_query'),
                'result_correct': equivalent(body['result']['rows'], expected_rows) if expected_rows is not None and body['result'] else None,
                'schema_correct': (set(case.get('required_columns', [])) <= guard_columns and table in guard_tables) if expected_rows is not None else None,
                'security_correct': (body.get('error') or {}).get('code') == case['expected_error'] if 'expected_error' in case else None,
                'conversation_correct': body.get('conversation_id') == payload['conversation_id'] if 'conversation_id' in payload else None,
                'cache_hit': body['metadata']['cache_hit'], 'cache_expected': case.get('expected_cache_hit'),
                'latency_ms': body['metadata']['latency_ms'], 'repair_attempts': body['metadata']['repair_attempts'],
                'repair_expected': 'repair_sql' in case})
            item = results[-1]
            item['passed'] = (item['status'] == item['expected_status'] and item['route_correct']
                and item['result_correct'] is not False and item['schema_correct'] is not False
                and item['security_correct'] is not False and item['conversation_correct'] is not False
                and (not item['repair_expected'] or item['repair_attempts'] > 0)
                and (item['cache_expected'] is None or item['cache_hit'] == item['cache_expected']))
        analytical = [x for x in results if x['expected_status'] == 'verified']
        unsafe = [x for x in results if x['category'] == 'adversarial']
        repairs = [x for x in results if x['repair_expected']]
        metrics = {'cases': len(results),
            'execution_accuracy': sum(x['status'] == 'verified' for x in analytical) / len(analytical),
            'result_accuracy': sum(x['result_correct'] is True for x in analytical) / len(analytical),
            'schema_accuracy': sum(x['schema_correct'] is True for x in analytical) / len(analytical),
            'security_rejection_rate': sum(x['status'] in ('failed', 'unsupported') for x in unsafe) / len(unsafe),
            'false_block_rate': sum(x['status'] != 'verified' for x in analytical) / len(analytical),
            'cache_hit_rate': sum(x['cache_hit'] for x in analytical) / len(analytical),
            'repair_success_rate': sum(x['status'] == 'verified' and x['repair_attempts'] > 0 for x in repairs) / len(repairs) if repairs else None,
            'p50_latency_ms': percentile([x['latency_ms'] for x in results], .5),
            'p95_latency_ms': percentile([x['latency_ms'] for x in results], .95)}
        categories = {}
        for item in results:
            category = categories.setdefault(item['category'], {'cases': 0, 'passed': 0})
            category['cases'] += 1
            category['passed'] += item['passed']
        return {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                'build_version': os.environ.get('GITHUB_SHA'),
                'benchmark_version': hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()[:12],
                'dataset_version': dataset['version'], 'schema_hash': dataset['schema_hash'],
                'provider': 'scripted_fake', 'llm_model': 'scripted_fake', 'embedding_model': 'eval-hash-16',
                'configuration': {'cache_similarity_threshold': settings.cache_similarity_threshold,
                    'max_result_rows': settings.max_result_rows, 'max_repair_attempts': settings.max_repair_attempts},
                'meaning': 'Measures pipeline controls with scripted model outputs, not Ollama answer quality',
                'metrics': metrics, 'per_category': categories,
                'failed_cases': [item['id'] for item in results if not item['passed']],
                'security_failures': [item['id'] for item in unsafe if not item['passed']],
                'false_blocks': [item['id'] for item in analytical if item['status'] != 'verified'],
                'cases': results}


def markdown(report):
    lines = ['# DataTrust scripted evaluation', '',
        f"Run: {report['timestamp_utc']}", f"Benchmark: {report['benchmark_version']}",
        f"Dataset version: {report['dataset_version']}", f"Schema hash: {report['schema_hash']}",
        '', report['meaning'], '', '## Summary', '']
    lines += [f'- {name}: {value}' for name, value in report['metrics'].items()]
    lines += ['', '## Categories', '']
    lines += [f"- {name}: {value['passed']}/{value['cases']} passed" for name, value in report['per_category'].items()]
    lines += ['', '## Failures', '',
        '- Failed cases: ' + (', '.join(report['failed_cases']) or 'none'),
        '- Security failures: ' + (', '.join(report['security_failures']) or 'none'),
        '- False blocks: ' + (', '.join(report['false_blocks']) or 'none'),
        '- Repair outcomes: ' + (f"{sum(item['status'] == 'verified' and item['repair_attempts'] > 0 for item in report['cases'] if item['repair_expected'])}/{sum(item['repair_expected'] for item in report['cases'])} recovered" if any(item['repair_expected'] for item in report['cases']) else 'no repairable benchmark case'), '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'evaluation' / 'reports' / 'latest.json')
    parser.add_argument('--check', action='store_true', help='Exit nonzero when a gold case fails')
    args = parser.parse_args()
    report = run(json.loads((ROOT / 'evaluation' / 'gold_queries.json').read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    args.output.with_suffix('.md').write_text(markdown(report), encoding='utf-8')
    print(json.dumps(report['metrics'], indent=2))
    if args.check and report['failed_cases']:
        print('Failed gold cases: ' + ', '.join(report['failed_cases']), file=sys.stderr)
        sys.exit(1)
