import tempfile

from signalforge.config import Settings, ensure_data_dir


def test_settings_default_to_demo_without_api_key(tmp_path) -> None:
    settings = Settings(_env_file=None, model_api_key=None, data_dir=tmp_path)

    assert settings.demo_mode is True


def test_settings_enable_live_mode_with_key(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        model_api_key="test-key",
        signalforge_demo_mode=False,
        data_dir=tmp_path,
    )

    assert settings.demo_mode is False


def test_flow_defaults_to_v1_and_blob_selects_v2(tmp_path) -> None:
    local = Settings(_env_file=None, data_dir=tmp_path)
    assert local.serverless_mode is False
    assert local.flow == "v1"

    serverless = Settings(
        _env_file=None, data_dir=tmp_path, storage_backend="blob"
    )
    assert serverless.serverless_mode is True
    assert serverless.flow == "v2"

    forced = Settings(_env_file=None, data_dir=tmp_path, web_flow="v2")
    assert forced.flow == "v2"


def test_ensure_data_dir_uses_configured_directory(tmp_path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "runs")
    assert ensure_data_dir(settings) == tmp_path / "runs"
    assert (tmp_path / "runs").is_dir()


def test_ensure_data_dir_falls_back_to_tmp(tmp_path, monkeypatch) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    settings = Settings(_env_file=None, data_dir=blocker / "runs")
    fake_tmp = tmp_path / "tmp"
    fake_tmp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_tmp))
    result = ensure_data_dir(settings)
    assert result == fake_tmp / "signalforge-runs"
    assert result.is_dir()
