from app import pipeline

def test_measure_loudnorm_and_ebur128(sine_file):
    ln = pipeline.measure_loudnorm_json(sine_file)
    assert 'input_i' in ln and 'input_tp' in ln
    tl = pipeline.ebur128_timeline(sine_file)
    assert len(tl['sec']) == len(tl['short_term']) and len(tl['sec']) > 0
