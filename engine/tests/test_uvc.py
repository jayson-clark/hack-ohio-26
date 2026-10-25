from vision import uvc


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("CAMERA_EXPOSURE", "10")
    monkeypatch.setenv("CAMERA_FOCUS", "0")
    assert uvc.settings_from_env() == [
        ("auto_exposure_mode", 1),
        ("absolute_exposure_time", 10),
        ("auto_focus", 0),
        ("absolute_focus", 0),
    ]


def test_empty_or_bad_values_keep_auto(monkeypatch):
    monkeypatch.setenv("CAMERA_EXPOSURE", "")
    monkeypatch.setenv("CAMERA_FOCUS", "near")
    assert uvc.settings_from_env() == []
    monkeypatch.delenv("CAMERA_EXPOSURE")
    monkeypatch.delenv("CAMERA_FOCUS")
    assert uvc.settings_from_env() == []


def test_apply_never_raises(monkeypatch):
    monkeypatch.setattr(uvc, "UVCC", ["/nonexistent/uvcc"])
    uvc.apply([("absolute_exposure_time", 10)])  # logged, not raised
