from clef_extractor.calibration import ThresholdStats, Trial, recommend, summarize


def trial(truthful, score):
    return Trial("s", "f", "v", truthful, score, True)


def test_summarize_counts_errors_per_threshold():
    trials = [trial(True, 0.95), trial(True, 0.45), trial(False, 0.02), trial(False, 0.6)]
    stats = {s.threshold: s for s in summarize(trials, thresholds=(0.3, 0.5, 0.7))}
    assert stats[0.3] == ThresholdStats(0.3, false_accepts=1, false_flags=0, wrong_total=2, true_total=2)
    assert stats[0.5] == ThresholdStats(0.5, false_accepts=1, false_flags=1, wrong_total=2, true_total=2)
    assert stats[0.7] == ThresholdStats(0.7, false_accepts=0, false_flags=1, wrong_total=2, true_total=2)
    assert stats[0.5].false_accept_rate == 0.5 and stats[0.5].false_flag_rate == 0.5


def test_recommend_prefers_zero_false_accepts_then_fewest_flags_then_higher_threshold():
    stats = [ThresholdStats(0.3, 1, 0, 2, 2), ThresholdStats(0.5, 0, 1, 2, 2),
             ThresholdStats(0.6, 0, 1, 2, 2), ThresholdStats(0.9, 0, 2, 2, 2)]
    assert recommend(stats).threshold == 0.6


def test_recommend_falls_back_to_fewest_false_accepts():
    stats = [ThresholdStats(0.3, 2, 0, 2, 2), ThresholdStats(0.7, 1, 1, 2, 2)]
    assert recommend(stats).threshold == 0.7


def test_rates_handle_empty_sets():
    s = ThresholdStats(0.5, 0, 0, 0, 0)
    assert s.false_accept_rate == 0.0 and s.false_flag_rate == 0.0
