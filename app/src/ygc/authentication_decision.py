"""Versioned provisional evidence acceptance, without ownership or DB mutation."""
RULE_VERSION = 'evidence-acceptance-v2-no-contradiction'
REASONS = {
    'serial_not_matched': 'シリアルが期待値と一致していません（未読を含む）。',
    'challenge_not_matched': '両画像のチャレンジが期待値と一致していません（未読を含む）。',
    'reference_missing': '個体比較の対象がありません。',
    'clear_contradiction': '個体の一致を妨げる明確な矛盾があります。',
    'classification_missing': '相違の分類が不足しています。',
}


def apply_decision(result):
    images = result['images']
    comparison = result.get('comparison')
    reasons = []
    identity_unconfirmed = False
    if not images or images[0]['serial'].get('match_status') != 'matched':
        reasons.append('serial_not_matched')
    if len(images) != 2 or any(i['challenge'].get('match_status') != 'matched' for i in images):
        reasons.append('challenge_not_matched')
    if not comparison or not result.get('reference'):
        reasons.append('reference_missing')
    else:
        identity = comparison['identity']
        # Lack of positive identification is not a clear contradiction.
        # Keep the observations intact; this is an acceptance policy, not a
        # claim that uncertain images identify the same physical instrument.
        identity_unconfirmed = (identity.get('status') != 'supported'
            or identity.get('comparison_coverage') != 'sufficient'
            or not any(f.get('location', '').strip() and f.get('observation', '').strip()
                       for f in identity.get('supporting_features', [])))
        if identity.get('status') == 'contradicted' or identity.get('differences'):
            reasons.append('clear_contradiction')
        if (identity.get('status') not in ('supported', 'uncertain', 'contradicted')
                or identity.get('comparison_coverage') not in ('sufficient', 'insufficient')
                or not isinstance(identity.get('differences'), list)
                or not isinstance(identity.get('ambiguous_differences'), list)
                or not isinstance(identity.get('supporting_features'), list)):
            reasons.append('classification_missing')
    accepted = not reasons
    success_code = 'criteria_met_identity_unconfirmed' if identity_unconfirmed else 'criteria_met'
    success_reason = ('文字照合は一致。個体比較は明確な矛盾がないため条件通過。同一個体の確証は得られていません。'
                      if identity_unconfirmed else '文字照合は一致し、個体比較に明確な矛盾がないため採用条件を満たしました。')
    result['adjudication'] = {
        'accepted': accepted, 'provisional': True, 'rule_version': RULE_VERSION,
        'reason_codes': reasons or [success_code],
        'reasons': [REASONS[r] for r in reasons] or [success_reason],
        'identity_probability': None, 'probability_status': 'uncalibrated',
    }
    result['decision'] = ('暫定判定: ' + ('True（採用）' if accepted else 'False（不採用）')
                          + '。Falseは虚偽の断定ではありません。Claim・Evidence・所有権は変更していません。')
