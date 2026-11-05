"""
Unit tests for app.config.features — the Phase 2 feature-flag gate.

Every Phase 2 capability ships OFF by default so a fresh customer deployment
is safe, and only turns on when the environment variable is explicitly "true"
(case-insensitive). These tests pin exactly that contract.
"""

from app.config import features


class TestFlag:
    def test_true_string_enables(self, monkeypatch):
        monkeypatch.setenv("FEATURE_X", "true")
        assert features._flag("FEATURE_X") is True

    def test_uppercase_true_enables(self, monkeypatch):
        monkeypatch.setenv("FEATURE_X", "TRUE")
        assert features._flag("FEATURE_X") is True

    def test_false_string_disables(self, monkeypatch):
        monkeypatch.setenv("FEATURE_X", "false")
        assert features._flag("FEATURE_X") is False

    def test_unset_defaults_to_disabled(self, monkeypatch):
        monkeypatch.delenv("FEATURE_X", raising=False)
        assert features._flag("FEATURE_X") is False

    def test_arbitrary_value_is_not_true(self, monkeypatch):
        monkeypatch.setenv("FEATURE_X", "1")
        assert features._flag("FEATURE_X") is False

    def test_custom_default(self, monkeypatch):
        monkeypatch.delenv("FEATURE_X", raising=False)
        assert features._flag("FEATURE_X", default="true") is True


class TestIsEnabled:
    def test_unknown_feature_is_false(self):
        assert features.is_enabled("does_not_exist") is False

    def test_known_feature_keys_present(self):
        for key in ("event_recording", "pattern_engine", "insight_surfacing"):
            assert key in features.FEATURES
