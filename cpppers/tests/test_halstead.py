import math
from cpppers.halstead import HalsteadMetrics

def test_halstead_metrics_from_counts():
    m = HalsteadMetrics.from_counts(
        element_id="test_id",
        element_kind="Operation",
        n1=12,
        n2=10,
        N1=25,
        N2=15
    )
    
    assert m.element_id == "test_id"
    assert m.element_kind == "Operation"
    assert m.vocabulary == 22
    assert m.length == 40
    
    expected_volume = 40 * math.log2(22)
    assert math.isclose(m.volume, expected_volume)
    
    expected_difficulty = (12 / 2.0) * (15 / 10.0)
    assert math.isclose(m.difficulty, expected_difficulty)
    
    expected_effort = expected_difficulty * expected_volume
    assert math.isclose(m.effort, expected_effort)
    
    assert math.isclose(m.estimated_bugs, expected_volume / 3000.0)

def test_halstead_metrics_aggregate():
    m1 = HalsteadMetrics.from_counts("m1", "Operation", 5, 5, 10, 10)
    m2 = HalsteadMetrics.from_counts("m2", "Operation", 4, 6, 8, 12)
    
    agg = HalsteadMetrics.aggregate("agg", "Type", [m1, m2])
    
    assert agg.element_id == "agg"
    assert agg.element_kind == "Type"
    assert agg.n1 == 0
    assert agg.n2 == 0
    assert agg.vocabulary == -1
    
    assert agg.length == m1.length + m2.length
    assert math.isclose(agg.volume, m1.volume + m2.volume)
    assert math.isclose(agg.effort, m1.effort + m2.effort)
    assert math.isclose(agg.estimated_bugs, (m1.volume + m2.volume) / 3000.0)
    assert math.isnan(agg.difficulty)
