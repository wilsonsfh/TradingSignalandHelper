import json

import notify.telegram as tg
from notify.telegram import TelegramNotifier
from models import Action, Signal
from broker.mock_broker import MockBroker
from state.store import StateStore
from trader.executor import Executor
from trader.runtime import TradingRuntime


class _Feed:
    def __init__(self, prices):
        self.prices = prices

    def last_price(self, symbol):
        return float(self.prices[symbol])


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def notify(self, text):
        self.messages.append(text)


def test_enabled_requires_both_token_and_chat():
    assert TelegramNotifier("", "").enabled is False
    assert TelegramNotifier("tok", "").enabled is False
    assert TelegramNotifier("", "chat").enabled is False
    assert TelegramNotifier("tok", "chat").enabled is True


def test_send_sync_no_op_when_disabled():
    assert TelegramNotifier("", "")._send_sync("hi") is False


def test_send_sync_posts_to_bot_api(monkeypatch):
    captured = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr(tg.urllib.request, "urlopen", fake_urlopen)
    ok = TelegramNotifier("BOT", "CHAT")._send_sync("hello world")
    assert ok is True
    assert "botBOT/sendMessage" in captured["url"]
    assert captured["body"] == {
        "chat_id": "CHAT",
        "text": "hello world",
        "disable_web_page_preview": True,
    }


def test_send_sync_swallows_errors(monkeypatch):
    def boom(request, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(tg.urllib.request, "urlopen", boom)
    assert TelegramNotifier("BOT", "CHAT")._send_sync("hi") is False


def test_runtime_notifies_on_open_and_auto_exit(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    broker = MockBroker()
    notifier = FakeNotifier()
    runtime = TradingRuntime(
        broker, _Feed({"AAPL": 97.0}), Executor(broker), store, notifier=notifier
    )

    runtime.execute(Signal("AAPL", Action.BUY, 100.0, take_profit=103.0, stop_loss=98.0))
    assert any("AAPL" in m and "Opened" in m for m in notifier.messages)

    notifier.messages.clear()
    runtime.poll_once()  # feed price 97 <= stop 98 -> soft stop
    assert any("auto-exit" in m and "AAPL" in m and "STOP_LOSS" in m for m in notifier.messages)


def test_runtime_without_notifier_is_silent(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    broker = MockBroker()
    runtime = TradingRuntime(broker, _Feed({"AAPL": 100.0}), Executor(broker), store)
    # No notifier configured -> _notify is a no-op and must not raise.
    result = runtime.execute(Signal("AAPL", Action.BUY, 100.0, take_profit=103.0, stop_loss=98.0))
    assert result["status"] == "OPENED"
