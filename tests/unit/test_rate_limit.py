import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from availability_hotel.core.rate_limit import (
    RateLimiter,
    SlidingWindowLimiter,
    TokenBucketLimiter,
    parse_retry_after,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_disabled_limiter_never_waits():
    limiter = RateLimiter()
    results = await asyncio.gather(*(limiter.acquire(float("inf")) for _ in range(50)))
    assert all(results)


async def test_sliding_window_never_exceeds_quota_in_any_window():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(10, 1.0, clock)
    granted = []
    for step in range(40):
        clock.now = 1000.0 + step * 0.05
        if await limiter.acquire(deadline=clock.now):
            granted.append(clock.now)
    for start in granted:
        in_window = [t for t in granted if start <= t < start + 1.0]
        assert len(in_window) <= 10
    assert len(granted) == 20


async def test_sliding_window_waits_until_slot_within_deadline():
    limiter = SlidingWindowLimiter(2, 0.2)
    loop = asyncio.get_running_loop()
    start = loop.time()
    results = [await limiter.acquire(loop.time() + 1) for _ in range(3)]
    assert results == [True, True, True]
    assert loop.time() - start >= 0.18


async def test_sliding_window_gives_up_when_deadline_too_close():
    limiter = SlidingWindowLimiter(1, 10.0)
    assert await limiter.acquire(float("inf"))
    loop = asyncio.get_running_loop()
    assert not await limiter.acquire(loop.time() + 0.1)


async def test_token_bucket_allows_burst_then_refills():
    clock = FakeClock()
    limiter = TokenBucketLimiter(10, 1.0, burst=3, clock=clock)
    assert [await limiter.acquire(clock.now) for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]
    clock.now += 0.1
    assert await limiter.acquire(clock.now)


def test_factory_selects_algorithm_and_margin():
    from availability_hotel.config.schema import RateLimitConfig
    from availability_hotel.providers.factory import build_rate_limiter

    clock = FakeClock()
    disabled = build_rate_limiter(RateLimitConfig(), clock)
    bucket = build_rate_limiter(
        RateLimitConfig(
            enabled=True, requests=5, per_seconds=1, algorithm="token_bucket"
        ),
        clock,
    )
    window = build_rate_limiter(
        RateLimitConfig(enabled=True, requests=5, per_seconds=1, safety_margin_s=0.1),
        clock,
    )
    assert type(disabled) is RateLimiter
    assert isinstance(bucket, TokenBucketLimiter)
    assert isinstance(window, SlidingWindowLimiter)
    assert window._per_seconds == pytest.approx(1.1)


async def test_block_for_rejects_immediately():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(10, 1.0, clock)
    limiter.block_for(1.0)
    assert limiter.is_blocked()
    assert not await limiter.acquire(clock.now + 5)
    clock.now += 1.01
    assert not limiter.is_blocked()
    assert await limiter.acquire(clock.now)


@pytest.mark.parametrize(
    ("value", "expected"), [("1", 1.0), ("2.5", 2.5), ("-3", 0.0), (None, None)]
)
def test_parse_retry_after_seconds(value, expected):
    assert parse_retry_after(value) == expected


def test_parse_retry_after_http_date():
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    header = format_datetime(now + timedelta(seconds=3), usegmt=True)
    assert parse_retry_after(header, now=now) == pytest.approx(3.0)


def test_parse_retry_after_garbage():
    assert parse_retry_after("soon") is None
