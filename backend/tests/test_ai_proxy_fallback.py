import httpx
import pytest

from app.ai import provider as P


def test_proxy_error_is_always_eligible(monkeypatch):
    monkeypatch.setattr(P, "_system_proxy_url", lambda: "")
    exc = httpx.ProxyError("proxy dead")
    assert P._is_proxy_eligible_failure(exc) is True


def test_connect_error_eligible_only_when_proxy_configured(monkeypatch):
    exc = httpx.ConnectError("refused")

    monkeypatch.setattr(P, "_system_proxy_url", lambda: "http://127.0.0.1:7890")
    assert P._is_proxy_eligible_failure(exc) is True

    monkeypatch.setattr(P, "_system_proxy_url", lambda: "")
    assert P._is_proxy_eligible_failure(exc) is False


def test_read_timeout_not_proxy_eligible(monkeypatch):
    monkeypatch.setattr(P, "_system_proxy_url", lambda: "http://127.0.0.1:7890")
    exc = httpx.ReadTimeout("slow")
    assert P._is_proxy_eligible_failure(exc) is False


def test_auth_status_error_not_proxy_eligible(monkeypatch):
    monkeypatch.setattr(P, "_system_proxy_url", lambda: "http://127.0.0.1:7890")
    resp = httpx.Response(401, text="bad key", request=httpx.Request("POST", "https://x"))
    exc = httpx.HTTPStatusError("401", request=resp.request, response=resp)
    assert P._is_proxy_eligible_failure(exc) is False


def test_retry_after_seconds_parses_integer():
    resp = httpx.Response(
        429, headers={"Retry-After": "3"}, request=httpx.Request("GET", "https://x")
    )
    assert P._retry_after_seconds(resp) == 3.0


def test_retry_after_seconds_missing_returns_none():
    resp = httpx.Response(429, request=httpx.Request("GET", "https://x"))
    assert P._retry_after_seconds(resp) is None


def test_retry_after_seconds_http_date(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(
        P,
        "datetime",
        type(
            "FixedDateTime",
            (),
            {
                "now": staticmethod(
                    lambda tz=None: datetime(2026, 10, 21, 7, 27, 50, tzinfo=timezone.utc)
                )
            },
        ),
    )
    resp = httpx.Response(
        429,
        headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
        request=httpx.Request("GET", "https://x"),
    )
    assert P._retry_after_seconds(resp) == pytest.approx(10.0)


def test_retry_after_seconds_garbage_returns_none():
    resp = httpx.Response(
        429,
        headers={"Retry-After": "not-a-delay"},
        request=httpx.Request("GET", "https://x"),
    )
    assert P._retry_after_seconds(resp) is None


def test_rate_limit_delay_respects_retry_after_capped():
    resp = httpx.Response(
        429, headers={"Retry-After": "100"}, request=httpx.Request("GET", "https://x")
    )
    assert P._rate_limit_delay(resp, attempt=1) == P.PROBE_RATE_LIMIT_CAP


def test_rate_limit_delay_exponential_with_jitter_capped(monkeypatch):
    monkeypatch.setattr(P, "PROBE_RATE_LIMIT_CAP", 8.0)
    monkeypatch.setattr(P, "PROBE_RETRY_DELAY", 0.6)
    resp = httpx.Response(429, request=httpx.Request("GET", "https://x"))
    for attempt in (1, 2, 3, 4):
        delay = P._rate_limit_delay(resp, attempt)
        assert 0 < delay <= P.PROBE_RATE_LIMIT_CAP


def test_backoff_seconds_uses_retry_after_for_429():
    resp = httpx.Response(
        429, headers={"Retry-After": "2"}, request=httpx.Request("GET", "https://x")
    )
    exc = httpx.HTTPStatusError("429", request=resp.request, response=resp)
    assert P._backoff_seconds(exc, attempt=3) == 2.0


def test_backoff_seconds_linear_for_non_rate_limit(monkeypatch):
    monkeypatch.setattr(P, "PROBE_RETRY_DELAY", 0.6)
    exc = httpx.ConnectError("reset")
    assert P._backoff_seconds(exc, attempt=2) == pytest.approx(1.2)


def test_backoff_seconds_falls_back_when_no_response():
    exc = httpx.ConnectError("reset")
    assert P._backoff_seconds(exc, attempt=1) > 0
