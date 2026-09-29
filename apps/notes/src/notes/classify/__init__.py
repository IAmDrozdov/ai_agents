"""The Classifier port and its implementations; the provider is a configuration value."""

from __future__ import annotations

from notes.classify.port import Classifier
from shared.config import Settings
from shared.pricing import DEFAULT_TRANSLATE_MODEL


def make_classifier(settings: Settings) -> Classifier:
    provider = settings.notes_classifier_provider
    if provider == "fake":
        from notes.classify.fake import FakeClassifier

        return FakeClassifier()
    if provider == "openai":
        from notes.classify.openai_adapter import OpenAIClassifier

        if settings.openai_api_key is None:
            raise ValueError("NOTES_CLASSIFIER_PROVIDER=openai needs OPENAI_API_KEY")
        model = settings.notes_classifier_model or DEFAULT_TRANSLATE_MODEL
        return OpenAIClassifier(settings.openai_api_key.get_secret_value(), model)
    raise ValueError(f"unknown classifier provider: {provider}")
