from copy import deepcopy

import pytest

from ygc.authentication_decision import apply_decision
from authentication_fixtures import measurement


def decide(result):
    apply_decision(result)
    return result['adjudication']


def test_ambiguous_ring_does_not_reject_supported_identity():
    result = measurement()
    result['comparison']['identity']['ambiguous_differences'] = [
        {'location': 'ブリッジ脇', 'observation': '白いリング。反射か付着物か不明'}]
    decision = decide(result)
    assert decision['accepted'] is True
    assert decision['identity_probability'] is None
    assert decision['reason_codes'] == ['criteria_met']


@pytest.mark.parametrize('field,value,reason', [
    ('differences', [{'location': 'ボディ左下', 'observation': '同位置の木目が異なる'}], 'clear_contradiction'),
    ('status', 'contradicted', 'clear_contradiction'),
])
def test_identity_gates(field, value, reason):
    result = measurement()
    result['comparison']['identity'][field] = value
    decision = decide(result)
    assert decision['accepted'] is False
    assert reason in decision['reason_codes']


@pytest.mark.parametrize('index,field', [(0, 'serial'), (0, 'challenge'), (1, 'challenge')])
@pytest.mark.parametrize('status', ['mismatched', 'unconfirmed'])
def test_text_gates(index, field, status):
    result = measurement()
    result['images'][index][field]['match_status'] = status
    assert decide(result)['accepted'] is False


def test_reference_is_required_and_legacy_classification_is_not_accepted():
    result = measurement()
    result['comparison'] = None
    assert 'reference_missing' in decide(result)['reason_codes']
    result = measurement()
    del result['comparison']['identity']['ambiguous_differences']
    assert 'classification_missing' in decide(result)['reason_codes']


def test_closeup_link_and_photography_are_not_acceptance_conditions():
    result = measurement()
    result['comparison']['closeup_link']['status'] = 'contradicted'
    result['comparison']['photography']['status'] = 'reuse_suspected'
    before = deepcopy(result['comparison'])
    assert decide(result)['accepted'] is True
    assert result['comparison'] == before


@pytest.mark.parametrize('coverage',['sufficient','insufficient'])
def test_uncertain_identity_passes_without_inventing_support(coverage):
    result=measurement()
    identity=result['comparison']['identity']
    identity.update(status='uncertain',supporting_features=[],comparison_coverage=coverage,
        ambiguous_differences=[{'location':'B/C ボディ','observation':'暗い塗装と反射で木目を照合できない'}])
    before=deepcopy(identity)
    decision=decide(result)
    assert decision['accepted'] is True
    assert decision['reason_codes']==['criteria_met_identity_unconfirmed']
    assert '確証は得られていません' in decision['reasons'][0]
    assert identity==before
    assert decision['identity_probability'] is None


def test_uncertain_identity_does_not_override_text_or_clear_contradictions():
    result=measurement()
    result['comparison']['identity'].update(status='uncertain',supporting_features=[],comparison_coverage='insufficient')
    result['images'][0]['serial']['match_status']='mismatched'
    assert decide(result)['accepted'] is False
    result['images'][0]['serial']['match_status']='matched'
    result['comparison']['identity']['differences']=[{'location':'B/C ボディ','observation':'対応位置の木目が明確に異なる'}]
    assert 'clear_contradiction' in decide(result)['reason_codes']
