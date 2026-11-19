import json
from pathlib import Path

import pytest

from nlp_support_case_routing.casebook import CaseBook
from nlp_support_case_routing.dialogue import Understander
from nlp_support_case_routing.dialogue_cli import run_case

FIXTURES = Path(__file__).parents[1] / 'fixtures'


def build_book(messages, events=()):
    registry = json.loads((FIXTURES / 'business.json').read_text(encoding='utf-8'))
    understander = Understander.from_registry(registry)
    book = CaseBook(registry)
    for index, text in enumerate(messages, start=1):
        book.apply_utterances(understander.feed({'id': f'U-{index}', 'speaker': '客户', 'text': text}))
        book.settle()
    for event in events:
        book.apply_event(event)
    return book


def scenario_view():
    return run_case(FIXTURES / 'dialogue.json', FIXTURES / 'business.json')


def by_id(view, ticket_id):
    return next(item for item in view['agent_view'] if item['id'] == ticket_id)


def test_scenario_retracted_refund_is_executed_not_withdrawn():
    view = scenario_view()
    refund = by_id(view, 'T-1')
    assert refund['state'] == '已执行'
    assert refund['note'] == '按已执行结果交给坐席协调'
    assert [receipt['ref'] for receipt in refund['receipts']] == ['B-17', 'B-21']
    assert refund['source']['text'] == '把8814那笔退了'
    retraction = [event for event in refund['events'] if event['type'] == '撤回']
    assert retraction[0]['text'] == '刚刚那笔不用退'
    assert '已撤回' not in json.dumps(refund, ensure_ascii=False)


def test_scenario_does_not_open_refund_for_the_other_order():
    view = scenario_view()
    refunds = [item for item in view['agent_view'] if item['action'] == '退款']
    assert [item['target'] for item in refunds] == ['8814']
    for item in view['agent_view']:
        if item['action'] == '查账':
            assert item['refund_authorized'] is False
            assert item['note'] != '已撤回'


def test_scenario_correction_keeps_old_receipts_and_new_request_waits():
    view = scenario_view()
    old = by_id(view, 'T-3')
    assert old['state'] == '已更正'
    assert old['team'] == '团队海风'
    assert [receipt['ref'] for receipt in old['receipts']] == ['B-23']
    assert old['confirmations'][0]['target'] == '8815'
    new = by_id(view, 'T-5')
    assert new['state'] == '待确认'
    assert new['team'] is None
    assert new['receipts'] == []
    assert view['supervisor_view'][0]['id'] == 'T-5'


def test_scenario_account_verification_stays_per_account():
    view = scenario_view()
    old_account = by_id(view, 'T-4')
    assert old_account['state'] == '已受理'
    assert old_account['team'] == '团队信标'
    new_account = by_id(view, 'T-2')
    assert new_account['state'] == '待核验'
    assert new_account['team'] is None
    linked = [event for event in new_account['events'] if event['type'] == '后续修改']
    assert linked[0]['ticket'] == 'T-4'


def test_retraction_before_dispatch_closes_directly():
    book = build_book(['把8815那笔退了，不用退了。'])
    ticket = book.tickets[0]
    assert ticket.state == '已关闭'
    assert ticket.team is None
    assert ticket.note == '未交办团队，撤回即关闭'


def test_retraction_after_acceptance_only_asks_team_to_stop():
    book = build_book(['把8814那笔退了。', '刚刚那笔不用退。'])
    ticket = book.tickets[0]
    assert ticket.state == '撤回中'
    assert ticket.note == '正在请账务停止'
    book.apply_event({'type': 'receipt', 'ref': 'B-21', 'status': 'executed', 'order': '8814'})
    assert ticket.state == '已执行'
    assert ticket.note == '按已执行结果交给坐席协调'


def test_supervisor_sees_candidates_while_agent_reports_the_rest():
    book = build_book(['把8814那笔退了，新账号先停用。', '刚刚那笔不用退，查下另一笔。旧账号还是停掉。'])
    pending = book.supervisor_view()
    assert [item['id'] for item in pending] == ['T-3']
    assert [candidate['number'] for candidate in pending[0]['candidates']] == ['8815', '6920']
    view = {item['id']: item['state'] for item in book.agent_view()}
    assert view['T-1'] == '撤回中'
    assert view['T-2'] == '待核验'
    assert view['T-4'] == '已交办'


def test_confirmed_candidate_dispatches_and_correction_needs_new_confirmation():
    book = build_book(
        ['把8814那笔退了。', '查下另一笔。'],
        [{'type': 'confirm', 'ticket': 'T-2', 'target': '8815', 'by': '主管'}],
    )
    old = book.tickets[1]
    assert old.state == '已交办'
    assert old.team == '团队海风'
    book.apply_event({'type': 'correct', 'ticket': 'T-2', 'target': '6920', 'by': '主管'})
    assert old.state == '已更正'
    new = book.tickets[2]
    assert new.state == '待确认'
    assert new.target == '6920'
    book.apply_event({'type': 'confirm', 'ticket': 'T-3', 'by': '主管'})
    assert new.state == '已交办'
    assert new.team == '团队松木'


def test_confirmation_cannot_bypass_account_verification():
    book = build_book(['新账号先停用。'])
    ticket = book.tickets[0]
    assert ticket.state == '待核验'
    with pytest.raises(ValueError):
        book.apply_event({'type': 'confirm', 'ticket': 'T-1', 'target': '新帐号-19', 'by': '主管'})
    assert ticket.team is None


def test_unmatched_retraction_is_reported():
    book = build_book(['把8814那笔退了。', '8815不用退了。'])
    assert book.notices == [{'type': '未匹配撤回', 'message': 'U-2', 'text': '8815不用退了'}]
    assert book.tickets[0].state == '已受理'
