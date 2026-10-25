from vision import uvc


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("CAMERA_EXPOSURE", "10")
    monkeypatch.setenv("CAMERA_GAIN", "0")
    monkeypatch.setenv("CAMERA_WHITE_BALANCE", "5000")
    monkeypatch.setenv("CAMERA_FOCUS", "0")
    assert uvc.settings_from_env() == [
        ("auto_exposure_mode", 1),
        ("absolute_exposure_time", 10),
        ("gain", 0),  # no auto switch of its own
        ("auto_white_balance_temperature", 0),
        ("white_balance_temperature", 5000),
        ("auto_focus", 0),
        ("absolute_focus", 0),
    ]


def test_empty_or_bad_values_keep_auto(monkeypatch):
    monkeypatch.setenv("CAMERA_EXPOSURE", "")
    monkeypatch.setenv("CAMERA_GAIN", "")
    monkeypatch.setenv("CAMERA_WHITE_BALANCE", "warm")
    monkeypatch.setenv("CAMERA_FOCUS", "near")
    assert uvc.settings_from_env() == []
    for var in ("CAMERA_EXPOSURE", "CAMERA_GAIN", "CAMERA_WHITE_BALANCE", "CAMERA_FOCUS"):
        monkeypatch.delenv(var)
    assert uvc.settings_from_env() == []


def test_apply_never_raises(monkeypatch):
    monkeypatch.setattr(uvc, "UVCC", ["/nonexistent/uvcc"])
    uvc.apply([("absolute_exposure_time", 10)])  # logged, not raised
