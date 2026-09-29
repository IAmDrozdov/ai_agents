"""The Classifier port and its implementations; the provider is a configuration value."""

from __future__ import annotations

from notes.classify.port import Classifier
from shared.config import Settings


def make_classifier(settings: Settings) -> Classifier:
    if settings.notes_classifier_provider == "fake":
        from notes.classify.fake import FakeClassifier

        return FakeClassifier()
    raise ValueError(f"unknown classifier provider: {settings.notes_classifier_provider}")
