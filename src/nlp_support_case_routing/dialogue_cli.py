import argparse
import json
from pathlib import Path

from .casebook import CaseBook
from .dialogue import Understander


def run_case(case_path, registry_path):
    conversation = json.loads(Path(case_path).read_text(encoding='utf-8'))
    registry = json.loads(Path(registry_path).read_text(encoding='utf-8'))
    understander = Understander.from_registry(registry)
    book = CaseBook(registry)
    for message in conversation['messages']:
        book.apply_utterances(understander.feed(message))
        book.settle()
    for event in conversation.get('events', []):
        book.apply_event(event)
    return {
        'agent_view': book.agent_view(),
        'supervisor_view': book.supervisor_view(),
        'notices': book.notices,
    }


def main():
    parser = argparse.ArgumentParser(description='会话诉求分派与进度')
    parser.add_argument('--case', type=Path, default=Path('fixtures/dialogue.json'))
    parser.add_argument('--registry', type=Path, default=Path('fixtures/business.json'))
    args = parser.parse_args()
    try:
        result = run_case(args.case, args.registry)
    except (OSError, KeyError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
