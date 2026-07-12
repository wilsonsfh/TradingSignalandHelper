import pytest

from config import Config


def test_invalid_broker_fails_closed():
    cfg = Config()
    cfg.broker = "typo"
    with pytest.raises(ValueError, match="BROKER"):
        cfg.validate()


def test_invalid_trading_environment_fails_closed():
    cfg = Config()
    cfg.trd_env = "REL"
    with pytest.raises(ValueError, match="TRD_ENV"):
        cfg.validate()


def test_webhook_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WEBHOOK_ENABLED", raising=False)
    assert Config().webhook_enabled is False


def test_new_settings_use_safe_defaults(monkeypatch):
    for name in (
        "STATE_DB_PATH",
        "SOFT_STOP_POLL_SECONDS",
        "WEBHOOK_ENABLED",
        "WEBHOOK_MAX_AGE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    cfg = Config()

    assert cfg.state_db_path == "state/trading.sqlite"
    assert cfg.soft_stop_poll_seconds == 4.0
    assert cfg.webhook_enabled is False
    assert cfg.webhook_max_age_seconds == 300


def test_max_alert_quantity_default(monkeypatch):
    monkeypatch.delenv("MAX_ALERT_QUANTITY", raising=False)
    assert Config().max_alert_quantity == 100


def test_nonpositive_max_alert_quantity_fails_closed():
    cfg = Config()
    cfg.max_alert_quantity = 0
    with pytest.raises(ValueError, match="MAX_ALERT_QUANTITY"):
        cfg.validate()


def test_bridge_security_defaults(monkeypatch):
    for name in (
        "USE_BROKER_STOP_ORDER",
        "WEBHOOK_SIGNATURE_REQUIRED",
        "WEBHOOK_IP_ALLOWLIST",
        "WEBHOOK_RATE_PER_MIN",
    ):
        monkeypatch.delenv(name, raising=False)
    cfg = Config()
    assert cfg.use_broker_stop_order is False
    assert cfg.webhook_signature_required is False
    assert cfg.webhook_ip_allowlist == []  # opt-in; edge/WAF handles it in prod
    assert cfg.webhook_rate_per_min == 5


def test_nonpositive_rate_limit_fails_closed():
    cfg = Config()
    cfg.webhook_rate_per_min = 0
    with pytest.raises(ValueError, match="WEBHOOK_RATE_PER_MIN"):
        cfg.validate()


@pytest.mark.parametrize(
    ("attribute", "value"),
    [("quantity", 0), ("soft_stop_poll_seconds", 0.0)],
)
def test_nonpositive_quantity_or_soft_stop_polling_fails_closed(attribute, value):
    cfg = Config()
    setattr(cfg, attribute, value)

    with pytest.raises(ValueError, match="QUANTITY and SOFT_STOP_POLL_SECONDS"):
        cfg.validate()


def test_moomoo_requires_yfinance_strategy_data():
    cfg = Config()
    cfg.broker = "moomoo"
    cfg.data_source = "demo"

    with pytest.raises(ValueError, match="DATA_SOURCE=yfinance"):
        cfg.validate()
