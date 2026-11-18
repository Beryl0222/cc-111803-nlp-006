from pathlib import Path

from nlp_support_case_routing.desk_cli import load_case


def test_billing_receipt_and_account_verification_are_independent():
    fixture = Path(__file__).parents[1] / 'fixtures'
    output = load_case(fixture / 'work.json', fixture / 'business.json')
    assert output[0]['team'] == '团队海风'
    assert output[0]['receipt'] == 'B-17'
    assert output[1]['progress'] == '待核验'
    assert output[1]['team'] is None
