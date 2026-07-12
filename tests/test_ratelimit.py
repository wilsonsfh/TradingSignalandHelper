from web.ratelimit import RateLimiter


def test_allows_up_to_limit_then_blocks():
    t = {"v": 0.0}
    rl = RateLimiter(per_min=2, now=lambda: t["v"])
    assert rl.allow("ip") is True
    assert rl.allow("ip") is True
    assert rl.allow("ip") is False
    t["v"] = 61.0  # window elapsed
    assert rl.allow("ip") is True


def test_keys_are_independent():
    rl = RateLimiter(per_min=1, now=lambda: 0.0)
    assert rl.allow("a") is True
    assert rl.allow("b") is True
    assert rl.allow("a") is False
