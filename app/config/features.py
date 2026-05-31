"""Feature flag system for Phase 2 features.

All Phase 2 features are gated behind environment variables.
Default is OFF for safe customer deployments.
User's personal Railway deployment sets these to true.
"""
import os


def _flag(name: str, default: str = 'false') -> bool:
    return os.environ.get(name, default).lower() == 'true'


FEATURES = {
    'event_recording': _flag('FEATURE_EVENTS'),
    'pattern_engine': _flag('FEATURE_PATTERNS'),
    'insight_surfacing': _flag('FEATURE_INSIGHTS'),
}


def is_enabled(feature: str) -> bool:
    return FEATURES.get(feature, False)
