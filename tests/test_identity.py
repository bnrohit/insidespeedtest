from pathlib import Path
from app.identity import IdentityMatcher


def test_school_fallback_and_exact_vlan(tmp_path):
    f = tmp_path / 'ranges.csv'
    f.write_text('scope,school,vlan,cidr,label\nschool,GPHS,,10.44.0.0/20,Campus\nvlan,GPHS,48,10.44.1.0/24,Staff\nvlan,GPHS,56,10.44.2.0/24,Secondary\n')
    mapping = IdentityMatcher.from_csv(f)
    assert mapping.lookup('10.44.1.19')['vlan'] == '48'
    assert mapping.lookup('10.44.1.19')['school'] == 'GPHS'
    assert mapping.lookup('10.44.3.19')['vlan'] == 'Unknown'
    assert mapping.lookup('10.44.3.19')['school'] == 'GPHS'
    assert mapping.lookup('192.0.2.30')['school'] == 'Unknown'


def test_reject_conflicting_ranges(tmp_path):
    f = tmp_path / 'ranges.csv'
    f.write_text('scope,school,vlan,cidr,label\nvlan,GPHS,48,10.44.1.0/24,Staff\nvlan,OTHER,56,10.44.1.0/24,Other\n')
    import pytest
    with pytest.raises(ValueError, match='Conflicting'):
        IdentityMatcher.from_csv(f)
