from research_track.track_a.src.normalization import PlateNormalizer
from research_track.track_a.src.pipeline import ANPRPipeline


def test_track_a_config_factory_uses_declared_normalizer_settings():
    pipeline = ANPRPipeline.from_config("research_track/track_a/config.yaml")
    assert pipeline.normalizer.min_length == 6
    assert pipeline.normalizer.max_length == 12
    assert len(pipeline.registry) == 50


def test_track_a_normalization_is_idempotent_and_non_destructive():
    normalizer = PlateNormalizer()
    raw = "  ch-01\u200b ab 1234  "
    first = normalizer.normalize(raw)
    second = normalizer.normalize(first.clean_text)
    assert first.raw_text == raw
    assert first.clean_text == second.clean_text
    assert first.clean_text == "CH01AB1234"


def test_track_a_empty_and_unicode_inputs_do_not_raise():
    normalizer = PlateNormalizer()
    assert not normalizer.normalize(None).is_valid_format
    result = normalizer.normalize("\uff23\uff28\u0966\u0967\u200b")
    assert result.clean_text == ""
    assert not result.is_valid_format
