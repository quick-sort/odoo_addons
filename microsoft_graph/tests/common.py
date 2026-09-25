import json as jsonlib
from unittest import mock


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, reason="reason"):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.reason = reason
        self.content = b"" if payload is None else jsonlib.dumps(payload).encode()
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("no payload")
        return self._payload

    def close(self):
        pass


def _service_module():
    import odoo.addons.microsoft_graph.models.microsoft_graph_service as module

    return module


def patch_requests_post(responses):
    """Patch ``requests.post`` as seen by the graph service module."""
    if isinstance(responses, FakeResponse):
        responses = [responses]
    return mock.patch.object(
        _service_module().requests, "post", side_effect=list(responses)
    )


def patch_requests_get(responses):
    if isinstance(responses, FakeResponse):
        responses = [responses]
    return mock.patch.object(
        _service_module().requests, "get", side_effect=list(responses)
    )


def patch_requests_request(responses):
    if isinstance(responses, FakeResponse):
        responses = [responses]
    return mock.patch.object(
        _service_module().requests, "request", side_effect=list(responses)
    )
