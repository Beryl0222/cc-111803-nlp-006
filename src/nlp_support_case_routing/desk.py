class CustomerRequests:
    def __init__(self, messages, orders):
        self.messages = {message['id']: message for message in messages}
        self.orders = {order['number']: order['product'] for order in orders}

    def check(self, request):
        message = self.messages[request['message']]
        if message['speaker'] != '客户':
            raise ValueError('分派需要客户的诉求记录')
        if request['kind'] not in {'billing', 'account'}:
            raise ValueError('未知诉求种类')
        if request['kind'] == 'billing' and self.orders[request['target']] != request['product']:
            raise ValueError('订单和产品不符')


class AssignmentDesk:
    def __init__(self, routes, account_checks):
        self.routes = routes
        self.verified = {check['account'] for check in account_checks if check['verified']}

    def assign(self, request):
        if request['kind'] == 'account' and request['target'] not in self.verified:
            return None
        return self.routes[request['product']][request['kind']]


class WorkReceipts:
    def __init__(self, receipts):
        self.accepted = {receipt['order']: receipt['ref'] for receipt in receipts if receipt['status'] == 'accepted'}

    def progression(self, request, team):
        ref = self.accepted.get(request['target']) if request['kind'] == 'billing' else None
        if ref:
            return '已交由账务', ref
        return ('待分派' if team else '待核验'), None


def assess(case, registry):
    requests = CustomerRequests(case['messages'], registry['orders'])
    assignments = AssignmentDesk(registry['routes'], registry['account_checks'])
    receipts = WorkReceipts(registry['receipts'])
    results = []
    for request in case['requests']:
        requests.check(request)
        team = assignments.assign(request)
        progress, receipt = receipts.progression(request, team)
        results.append({'id': request['id'], 'team': team, 'progress': progress, 'receipt': receipt})
    return results
