from cli import cmd_web
from config import Config
from models import Position
from state.store import StateStore


def test_cmd_web_restores_state_and_stops_runtime(monkeypatch, tmp_path):
    import web.app as web_app

    path = tmp_path / "state.sqlite"
    StateStore(path).save_position(Position("AAPL", 1, 100.0))
    config = Config()
    config.broker = "mock"
    config.state_db_path = str(path)
    captured = {}

    class FakeRuntime:
        started = False
        stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    runtime = FakeRuntime()

    class FakeApp:
        extensions = {"trading_runtime": runtime}

        def run(self, **kwargs):
            captured["run"] = kwargs

    def fake_build_broker(cfg, initial_positions=None):
        captured["positions"] = list(initial_positions or [])
        return object()

    def fake_create_app(cfg, broker=None, store=None):
        captured["store"] = store
        return FakeApp()

    monkeypatch.setattr(web_app, "build_broker", fake_build_broker)
    monkeypatch.setattr(web_app, "create_app", fake_create_app)

    cmd_web(config)

    assert [position.symbol for position in captured["positions"]] == ["AAPL"]
    assert captured["store"].path == str(path)
    assert runtime.started is True
    assert runtime.stopped is True
    assert captured["run"]["debug"] is False


def test_web_module_entrypoint_uses_managed_cli_lifecycle(monkeypatch):
    import cli
    import web.app as web_app

    config = Config()
    called = []
    monkeypatch.setattr(web_app, "load_config", lambda: config)
    monkeypatch.setattr(cli, "cmd_web", lambda cfg: called.append(cfg))

    class UnmanagedApp:
        def run(self, **kwargs):
            raise AssertionError("unmanaged Flask lifecycle used")

    monkeypatch.setattr(web_app, "create_app", lambda cfg: UnmanagedApp())

    web_app.run()

    assert called == [config]


def test_cmd_web_restores_moomoo_positions_before_connect(monkeypatch, tmp_path):
    import web.app as web_app

    path = tmp_path / "state.sqlite"
    StateStore(path).save_position(Position("AAPL", 1, 100.0, 103.0, 98.0))
    config = Config()
    config.broker = "moomoo"
    config.data_source = "yfinance"
    config.state_db_path = str(path)
    captured = {}

    class FakeBroker:
        def connect(self):
            captured["connected"] = True

    class FakeRuntime:
        def start(self):
            pass

        def stop(self):
            pass

    class FakeApp:
        extensions = {"trading_runtime": FakeRuntime()}

        def run(self, **kwargs):
            pass

    def fake_build_broker(cfg, initial_positions=None):
        captured["positions"] = list(initial_positions or [])
        return FakeBroker()

    monkeypatch.setattr(web_app, "build_broker", fake_build_broker)
    monkeypatch.setattr(web_app, "create_app", lambda cfg, broker=None, store=None: FakeApp())

    cmd_web(config)

    assert [position.symbol for position in captured["positions"]] == ["AAPL"]
    assert captured["connected"] is True
