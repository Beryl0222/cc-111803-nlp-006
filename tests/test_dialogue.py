import json
from pathlib import Path

from nlp_support_case_routing.dialogue import Understander

FIXTURES = Path(__file__).parents[1] / 'fixtures'


def load_understander():
    registry = json.loads((FIXTURES / 'business.json').read_text(encoding='utf-8'))
    return Understander.from_registry(registry)


def feed_all(understander, texts):
    utterances = []
    for index, (speaker, text) in enumerate(texts, start=1):
        utterances.extend(understander.feed({'id': f'M-{index}', 'speaker': speaker, 'text': text}))
    return utterances


def test_negation_retracts_the_order_just_discussed():
    understander = load_understander()
    utterances = feed_all(understander, [
        ('客户', '把8814那笔退了，新账号先停用。'),
        ('客户', '刚刚那笔不用退，查下另一笔。旧账号还是停掉。'),
    ])
    retraction = next(item for item in utterances if item.act == '撤回')
    assert retraction.action == '退款'
    assert retraction.topic == 'billing'
    assert retraction.target == '8814'
    assert retraction.reference['kind'] == 'anaphoric'


def test_other_order_yields_all_remaining_candidates():
    understander = load_understander()
    utterances = feed_all(understander, [
        ('客户', '把8814那笔退了。'),
        ('客户', '查下另一笔。'),
    ])
    investigate = next(item for item in utterances if item.action == '查账')
    assert investigate.act == '请求'
    assert investigate.target is None
    assert investigate.candidates == ['8815', '6920']


def test_reaffirmation_marks_modification_and_resolves_old_account():
    understander = load_understander()
    utterances = feed_all(understander, [
        ('客户', '新账号先停用。'),
        ('客户', '旧账号还是停掉。'),
    ])
    modification = utterances[-1]
    assert modification.act == '修改'
    assert modification.action == '停用'
    assert modification.target == '旧帐号-12'


def test_quotation_is_not_a_request():
    understander = load_understander()
    utterances = feed_all(understander, [
        ('客户', '把8814那笔退了。'),
        ('客户', '短信写着“退款已到账”，可我卡里没见到。'),
    ])
    quotes = [item for item in utterances if item.act == '引述']
    assert [item.text for item in quotes] == ['退款已到账']
    assert quotes[0].quote_of is None
    requests = [item for item in utterances if item.act in ('请求', '撤回', '修改')]
    assert len(requests) == 1


def test_agent_quotation_links_back_to_customer_words():
    understander = load_understander()
    utterances = feed_all(understander, [
        ('客户', '把8814那笔退了。'),
        ('坐席', '您指的是“把8814那笔退了”这笔吗？'),
    ])
    quote = next(item for item in utterances if item.act == '引述')
    assert quote.quote_of == 'M-1#1'
    assert not [item for item in utterances if item.speaker == '坐席' and item.act == '请求']


def test_explicit_account_id_is_normalized():
    understander = load_understander()
    utterances = feed_all(understander, [('客户', '把旧账号-12停掉。')])
    assert utterances[0].target == '旧帐号-12'
