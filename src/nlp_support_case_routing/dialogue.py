"""中文会话理解：把客户会话切成话语，识别修改、否定、引述和跨轮指代。

输出的话语（Utterance）保留原话、行为类别和指代解析结果，供案件簿
（casebook）生成可分派的诉求。本模块只做规则化的理解，不替代原始记录。
"""

import re
from dataclasses import dataclass, field

from .text import normalize_text

QUOTE_OPEN = {'「': '」', '“': '”', '‘': '’'}
CLAUSE_SPLIT = re.compile(r'[，。；！？,.;!?]+')

ORDER_NO = re.compile(r'(?<![0-9A-Za-z])\d{4}(?![0-9A-Za-z])')
ACCOUNT_ID = re.compile(r'[新旧][帐账]号-\d+')
ACCOUNT_AGE = re.compile(r'([新旧])[帐账]号')
OTHER_ORDER = re.compile(r'另(外)?一?[笔单]')
ANAPHORA = re.compile(r'(刚刚|刚才|上次|那|这|该)一?[笔单]')

NEGATION = re.compile(r'(不用|不必|别|取消|不退|先不)')
REAFFIRM = re.compile(r'(还是|照样|照旧)')

ACTIONS = (
    ('退款', 'billing', re.compile(r'退')),
    ('查账', 'billing', re.compile(r'查')),
    ('停用', 'account', re.compile(r'停')),
)


def split_segments(text):
    """把一句话切成（是否引述, 文本）段，引号内为引述。"""
    segments = []
    buf = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in QUOTE_OPEN:
            close = QUOTE_OPEN[ch]
            j = text.find(close, i + 1)
            if j != -1:
                if buf:
                    segments.append((False, ''.join(buf)))
                    buf = []
                segments.append((True, text[i + 1:j]))
                i = j + 1
                continue
        buf.append(ch)
        i += 1
    if buf:
        segments.append((False, ''.join(buf)))
    return segments


@dataclass
class Utterance:
    id: str
    message_id: str
    speaker: str
    text: str
    act: str            # 请求 | 撤回 | 修改 | 引述 | 陈述
    topic: str = None   # billing | account
    action: str = None  # 退款 | 查账 | 停用
    reference: dict = field(default_factory=dict)
    target: str = None
    candidates: list = field(default_factory=list)
    quote_of: str = None

    def to_dict(self):
        return {
            'id': self.id,
            'message': self.message_id,
            'speaker': self.speaker,
            'text': self.text,
            'act': self.act,
            'topic': self.topic,
            'action': self.action,
            'reference': self.reference,
            'target': self.target,
            'candidates': self.candidates,
            'quote_of': self.quote_of,
        }


class Understander:
    """按会话顺序理解每条消息，维护跨轮指代所需的上下文。"""

    def __init__(self, orders, accounts):
        self.orders = dict(orders)        # 订单号 -> 产品
        self.accounts = dict(accounts)    # 账号 -> 产品
        self.recent_orders = []           # 会话中至今提到的订单
        self.utterances = []              # 至今的全部话语

    @classmethod
    def from_registry(cls, registry):
        orders = {order['number']: order['product'] for order in registry['orders']}
        accounts = {check['account']: None for check in registry.get('account_checks', [])}
        accounts.update({account['id']: account['product'] for account in registry.get('accounts', [])})
        return cls(orders, accounts)

    def feed(self, message):
        """理解一条消息，返回新产生的话语列表。"""
        text = normalize_text(message['text'])
        speaker = message['speaker']
        fresh = []
        seq = 0
        for quoted, segment in split_segments(text):
            if quoted:
                seq += 1
                utterance = Utterance(
                    id=f"{message['id']}#{seq}",
                    message_id=message['id'],
                    speaker=speaker,
                    text=segment,
                    act='引述',
                    quote_of=self._find_quoted(segment),
                )
                fresh.append(utterance)
                continue
            for clause in CLAUSE_SPLIT.split(segment):
                clause = clause.strip()
                if not clause:
                    continue
                seq += 1
                fresh.append(self._classify(message['id'], speaker, f"{message['id']}#{seq}", clause))
        self.utterances.extend(fresh)
        return fresh

    def _find_quoted(self, segment):
        """引述若与会话前文的原话吻合，则链回该话语，否则视为外部引述。"""
        for utterance in reversed(self.utterances):
            if utterance.act != '引述' and segment and segment in utterance.text:
                return utterance.id
        return None

    def _classify(self, message_id, speaker, uid, clause):
        action = topic = None
        for name, kind, pattern in ACTIONS:
            if pattern.search(clause):
                action, topic = name, kind
                break
        if speaker != '客户':
            act = '陈述'
        elif action is None:
            act = '陈述'
        elif NEGATION.search(clause):
            act = '撤回'
        elif REAFFIRM.search(clause):
            act = '修改'
        else:
            act = '请求'
        reference, target, candidates = self._resolve(clause)
        return Utterance(
            id=uid,
            message_id=message_id,
            speaker=speaker,
            text=clause,
            act=act,
            topic=topic,
            action=action,
            reference=reference,
            target=target,
            candidates=candidates,
        )

    def _resolve(self, clause):
        match = ACCOUNT_ID.search(clause)
        if match:
            account = self._canonical_account(match.group())
            return {'kind': 'explicit', 'hint': match.group()}, account, []
        match = ORDER_NO.search(clause)
        if match:
            number = match.group()
            self.recent_orders.append(number)
            return {'kind': 'explicit', 'hint': number}, number, []
        if OTHER_ORDER.search(clause):
            current = self.recent_orders[-1] if self.recent_orders else None
            candidates = [number for number in self.orders if number != current]
            return {'kind': 'other', 'hint': clause, 'exclude': current}, None, candidates
        if ANAPHORA.search(clause):
            target = self.recent_orders[-1] if self.recent_orders else None
            return {'kind': 'anaphoric', 'hint': clause}, target, []
        match = ACCOUNT_AGE.search(clause)
        if match:
            age = match.group(1)
            for account in self.accounts:
                if account.startswith(age):
                    return {'kind': 'account_age', 'hint': match.group()}, account, []
            return {'kind': 'account_age', 'hint': match.group()}, None, []
        return {'kind': 'none'}, None, []

    def _canonical_account(self, text):
        wanted = text.replace('帐', '账')
        for account in self.accounts:
            if account.replace('帐', '账') == wanted:
                return account
        return text
