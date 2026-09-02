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


def apply_iap_result(session, request_uuid, result):
    """Exercise the durable receipt and continuation boundaries in model tests."""
    result = normalize_iap_result(result)
    if session._store_request_result(request_uuid, result):
        return session._continue(request_uuid)
    return {
        'kind': 'stable',
        'response': {
            'request_uuid': request_uuid,
            'responseState': session._get_response_state(),
        },
    }
