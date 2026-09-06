# Part of Odoo. See LICENSE file for full copyright and licensing details.


def normalize_iap_result(result):
    if result.get('kind'):
        return result
    if result.get('status') == 'success':
        return {'kind': 'success', 'message': result['result']}
    return {
        'kind': 'failure',
        'code': result.get('error') or 'request_failed',
    }


def apply_iap_result(session, request_uuid, result, *, deliver_child=False):
    """Exercise the durable receipt and continuation boundaries in model tests."""
    result = normalize_iap_result(result)
    owner = session._get_continuation_owner()
    outcome = session._continue(request_uuid, result)
    if outcome is None:
        outcome = {
            "prepared_requests": [],
            "response": {
                "request_uuid": request_uuid,
                "responseState": session._get_response_state(),
            },
        }
    if deliver_child and (child_result := outcome.get('child_result')):
        return owner.parent_session_id._merge_child_result(owner, child_result) or outcome
    return outcome
