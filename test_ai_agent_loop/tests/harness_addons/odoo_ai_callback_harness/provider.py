import requests


PROVIDER_URL = 'http://127.0.0.1:18280/completion'


def run_completion(messages, instructions, tools, options):
    response = requests.post(
        PROVIDER_URL,
        json={
            'messages': messages,
            'instructions': instructions,
            'tools': tools,
            'options': options,
        },
        timeout=15,
    )
    response.raise_for_status()
    return {
        'status': 'success',
        'result': response.json()['result'],
    }, 0.0
