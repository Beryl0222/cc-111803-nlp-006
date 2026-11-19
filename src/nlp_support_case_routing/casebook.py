"""诉求案件簿：把会话理解的结果落成诉求，并维护各团队进度。

状态约定：
- 待确认：指代有多个候选，等主管确认；
- 待核验：账号诉求的身份核验未通过，不能交办；
- 待交办：对象明确，尚未交给团队；
- 已交办 / 已受理：已交给团队 / 团队已接单（以回执为准）；
- 撤回中：已交账务的退款收到撤回，只能请账务停止；
- 已执行：团队回执确认已处理，交给坐席协调，不按撤回处理；
- 已关闭：未交团队的明确撤回，直接关闭；
- 已更正：主管更正了对象，交办与回执仍属本事项，新对象另立诉求。
"""

from dataclasses import dataclass, field

from .desk import AssignmentDesk

READY_STATES = ('待确认', '待核验', '待交办')
OPEN_STATES = ('已交办', '已受理')
TERMINAL_STATES = ('已关闭', '已执行', '已更正')


@dataclass
class Ticket:
    id: str
    action: str
    topic: str
    state: str
    target: str = None
    product: str = None
    team: str = None
    candidates: list = field(default_factory=list)
    refund_authorized: bool = False
    note: str = None
    source: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    def confirmations(self):
        return [event for event in self.events if event['type'] == '确认']

    def receipts(self):
        return [event for event in self.events if event['type'] == '回执']


class CaseBook:
    def __init__(self, registry):
        self.registry = registry
        self.desk = AssignmentDesk(registry['routes'], registry.get('account_checks', []))
        self.orders = {order['number']: order['product'] for order in registry['orders']}
        self.accounts = {account['id']: account['product'] for account in registry.get('accounts', [])}
        self.tickets = []
        self.notices = []
        self.receipt_pool = {}
        for receipt in registry.get('receipts', []):
            self._pool(receipt)
        self._seq = 0

    # ---- 会话入口 -----------------------------------------------------

    def apply_utterances(self, utterances):
        for utterance in utterances:
            if utterance.speaker != '客户':
                continue
            if utterance.act in ('请求', '修改'):
                self._open(utterance)
            elif utterance.act == '撤回':
                self._retract(utterance)

    def _open(self, utterance):
        self._seq += 1
        ticket = Ticket(
            id=f'T-{self._seq}',
            action=utterance.action,
            topic=utterance.topic,
            state='待交办',
            source={'message': utterance.message_id, 'utterance': utterance.id, 'text': utterance.text},
        )
        ticket.events.append({
            'type': '创建',
            'act': utterance.act,
            'message': utterance.message_id,
            'utterance': utterance.id,
            'text': utterance.text,
        })
        if utterance.topic == 'billing':
            ticket.refund_authorized = utterance.action == '退款'
            if not ticket.refund_authorized:
                ticket.note = '查账不包含退款授权'
            if utterance.target is not None:
                ticket.target = utterance.target
                ticket.product = self.orders.get(ticket.target)
            else:
                ticket.state = '待确认'
                ticket.note = '指代待主管确认'
                ticket.candidates = [
                    {'number': number, 'product': self.orders.get(number)}
                    for number in utterance.candidates
                ]
        else:
            ticket.target = utterance.target
            ticket.product = self.accounts.get(ticket.target)
        if utterance.act == '修改':
            self._link_modification(ticket)
        self.tickets.append(ticket)
        return ticket

    def _link_modification(self, ticket):
        """修改类话语沿用同一话题的在办诉求，互相留痕但不改动其状态。"""
        for other in reversed(self.tickets):
            if other.topic == ticket.topic and other.state not in TERMINAL_STATES:
                ticket.events[0]['modifies'] = other.id
                other.events.append({
                    'type': '后续修改',
                    'ticket': ticket.id,
                    'message': ticket.source['message'],
                    'text': ticket.source['text'],
                })
                return

    def _retract(self, utterance):
        ticket = self._match(utterance)
        if ticket is None:
            self.notices.append({
                'type': '未匹配撤回',
                'message': utterance.message_id,
                'text': utterance.text,
            })
            return
        ticket.events.append({
            'type': '撤回',
            'message': utterance.message_id,
            'utterance': utterance.id,
            'text': utterance.text,
        })
        if ticket.state in READY_STATES:
            ticket.state = '已关闭'
            ticket.note = '未交办团队，撤回即关闭'
        elif ticket.state in OPEN_STATES:
            ticket.state = '撤回中'
            ticket.note = '正在请账务停止' if ticket.topic == 'billing' else '正在请团队停止'
        elif ticket.state == '已执行':
            ticket.note = '团队已执行，不能按撤回处理'

    def _match(self, utterance):
        for ticket in reversed(self.tickets):
            if ticket.state in TERMINAL_STATES:
                continue
            if ticket.topic != utterance.topic or ticket.action != utterance.action:
                continue
            if utterance.target is not None and ticket.target != utterance.target:
                continue
            return ticket
        return None

    # ---- 交办与回执 ---------------------------------------------------

    def settle(self):
        for ticket in self.tickets:
            if ticket.state == '待交办':
                self._dispatch(ticket)
            self._apply_receipts(ticket)

    def _dispatch(self, ticket):
        if ticket.product not in self.desk.routes:
            ticket.state = '待确认'
            ticket.note = '产品未登记，待主管确认'
            return
        team = self.desk.assign({'kind': ticket.topic, 'target': ticket.target, 'product': ticket.product})
        if team is None:
            ticket.state = '待核验'
            ticket.note = '账号未通过身份核验'
            ticket.events.append({'type': '核验未过', 'account': ticket.target})
            return
        ticket.team = team
        ticket.state = '已交办'
        ticket.events.append({'type': '交办', 'team': team})

    def _pool(self, receipt):
        key = receipt.get('order') or receipt.get('account')
        self.receipt_pool.setdefault(key, []).append(receipt)

    def _apply_receipts(self, ticket):
        if ticket.target is None or ticket.state not in OPEN_STATES + ('撤回中',):
            return
        pending = self.receipt_pool.get(ticket.target)
        while pending and ticket.state in OPEN_STATES + ('撤回中',):
            receipt = pending.pop(0)
            event = {'type': '回执', 'ref': receipt['ref'], 'status': receipt['status']}
            ticket.events.append(event)
            if receipt['status'] == 'accepted':
                if ticket.state != '撤回中':
                    ticket.state = '已受理'
            elif receipt['status'] == 'executed':
                if ticket.state == '撤回中':
                    ticket.note = '按已执行结果交给坐席协调'
                ticket.state = '已执行'

    # ---- 主管与团队事件 -----------------------------------------------

    def apply_event(self, event):
        kind = event['type']
        if kind == 'receipt':
            self._pool(event)
        elif kind == 'confirm':
            self._confirm(event['ticket'], event.get('target'), event.get('by', '主管'))
        elif kind == 'correct':
            self._correct(event['ticket'], event['target'], event.get('by', '主管'))
        else:
            raise ValueError(f'未知事件类型: {kind}')
        self.settle()

    def _confirm(self, ticket_id, target, by):
        ticket = self._ticket(ticket_id)
        if ticket.state != '待确认':
            raise ValueError('仅待确认的诉求可以确认')
        if target is not None:
            known = [candidate['number'] for candidate in ticket.candidates]
            if known and target not in known:
                raise ValueError('确认对象不在候选中')
            ticket.target = target
        if ticket.target is None:
            raise ValueError('确认需要明确对象')
        ticket.product = self.orders.get(ticket.target) or self.accounts.get(ticket.target)
        ticket.candidates = []
        ticket.state = '待交办'
        ticket.note = None
        ticket.events.append({'type': '确认', 'by': by, 'target': ticket.target})

    def _correct(self, ticket_id, new_target, by):
        old = self._ticket(ticket_id)
        if old.state in TERMINAL_STATES:
            raise ValueError('已结束的诉求不能更正')
        self._seq += 1
        new = Ticket(
            id=f'T-{self._seq}',
            action=old.action,
            topic=old.topic,
            state='待确认',
            target=new_target,
            product=self.orders.get(new_target) or self.accounts.get(new_target),
            refund_authorized=old.refund_authorized,
            note='更正产生的新请求，需要独立确认',
            source=dict(old.source),
        )
        new.events.append({
            'type': '创建',
            'act': '更正',
            'from_ticket': old.id,
            'message': old.source.get('message'),
            'text': old.source.get('text'),
        })
        old.events.append({
            'type': '更正',
            'by': by,
            'old_target': old.target,
            'new_target': new_target,
            'new_ticket': new.id,
        })
        old.state = '已更正'
        old.note = '对象已更正，交办与回执仍属本事项'
        self.tickets.append(new)
        return new

    def _ticket(self, ticket_id):
        for ticket in self.tickets:
            if ticket.id == ticket_id:
                return ticket
        raise KeyError(f'未知诉求: {ticket_id}')

    # ---- 视图 ---------------------------------------------------------

    def agent_view(self):
        """坐席看到的每项进度，可追到原话、确认和团队回执。"""
        return [
            {
                'id': ticket.id,
                'action': ticket.action,
                'target': ticket.target,
                'product': ticket.product,
                'state': ticket.state,
                'team': ticket.team,
                'note': ticket.note,
                'refund_authorized': ticket.refund_authorized if ticket.topic == 'billing' else None,
                'source': ticket.source,
                'confirmations': ticket.confirmations(),
                'receipts': ticket.receipts(),
                'events': list(ticket.events),
            }
            for ticket in self.tickets
        ]

    def supervisor_view(self):
        """主管看到的待确认诉求及候选对象。"""
        return [
            {
                'id': ticket.id,
                'action': ticket.action,
                'state': ticket.state,
                'target': ticket.target,
                'candidates': list(ticket.candidates),
                'source': ticket.source,
            }
            for ticket in self.tickets
            if ticket.state == '待确认'
        ]
