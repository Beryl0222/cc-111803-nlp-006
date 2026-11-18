import json
from pathlib import Path

def load_facts(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def summarize(facts):
    product = facts['product']
    return {
        'queues': facts['routes'][product],
        'orders': [order['number'] for order in facts['orders'] if order['product'] == product],
    }
