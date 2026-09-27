from pathlib import Path

from voicepaste.config import Config, load_config, write_default_config


def test_default_config_values():
    cfg = Config()
    assert cfg.backend == "faster-whisper"
    assert cfg.model_tier == "cpu"
    assert cfg.model_id_for_tier("small") == "Systran/faster-whisper-small.en"
    assert cfg.model_id_for_tier("cpu") == "Systran/faster-whisper-small.en"
    assert cfg.model_id_for_tier("accuracy") == "Systran/faster-whisper-large-v3-turbo"
    assert cfg.shortcut.immediate is True
    assert cfg.shortcut.stop_on_silence is True
    assert cfg.shortcut.silence_seconds == 1.2


def test_load_partial_config_merges_defaults(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('model_tier = "fast"\n[insertion]\npaste_key = "ctrl+shift+v"\n')
    cfg = load_config(path)
    assert cfg.model_tier == "fast"
    assert cfg.insertion.paste_key == "ctrl+shift+v"
    assert cfg.models.cpu == "Systran/faster-whisper-small.en"


def test_load_config_recovers_threshold_misplaced_in_models(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[models]\nfast = "local-fast-model"\nvad_threshold = 0.01234\n')

    cfg = load_config(path)

    assert cfg.models.fast == "local-fast-model"
    assert cfg.shortcut.vad_threshold == 0.01234


def test_write_default_config_is_non_destructive(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('model_tier = "accuracy"\n')
    write_default_config(path)
    assert path.read_text() == 'model_tier = "accuracy"\n'
