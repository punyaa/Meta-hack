from signalforge.config import Settings


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
