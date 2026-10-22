import httpx
import pytest

from app.clients import ModelClient, ModelUnavailable

GOOD = {"label": "IT Support", "confidence": 0.9, "model_version": "c" * 40,
        "top_k": [{"label": "IT Support", "score": 0.9}]}  # fmt: skip


def client_with(handler, token=""):
    c = ModelClient("http://model", token, 1)
    c._http = httpx.Client(base_url="http://model", headers=c._http.headers,
                           transport=httpx.MockTransport(handler))  # fmt: skip
    return c


def test_sends_token_and_request_id():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200, json=GOOD)

    assert client_with(handler, token="t0k").predict(None, "b", "rid-1").label == "IT Support"
    assert seen["authorization"] == "Bearer t0k"
    assert seen["x-request-id"] == "rid-1"


def test_no_token_no_header():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200, json=GOOD)

    client_with(handler).predict(None, "b", "r")
    assert "authorization" not in seen


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("t")), "timeout"),
        (lambda req: httpx.Response(503, json={"detail": "model_loading"}), "http_error"),
        (lambda req: httpx.Response(200, text="not json"), "bad_response"),
        (lambda req: httpx.Response(200, json={"label": "x"}), "bad_response"),
    ],
)
def test_failures(handler, reason):
    with pytest.raises(ModelUnavailable) as e:
        client_with(handler).predict(None, "b", "r")
    assert e.value.reason == reason
