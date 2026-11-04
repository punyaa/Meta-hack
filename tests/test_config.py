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
