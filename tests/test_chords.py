"""Chord recognition for the chord-arpeggio embellisher."""

from spectrumizer.arrange.chords import identify_chord, group_by_onset
from spectrumizer.ir import Note


def test_major_triad_root_position():
    # C E G -> root C (pc 0), major
    assert identify_chord([60, 64, 67]) == (0, 'maj')


def test_minor_triad_root_position():
    # A C E -> root A (pc 9), minor
    assert identify_chord([57, 60, 64]) == (9, 'min')


def test_first_inversion_keeps_root():
    # E G C (C-major, E in the bass) -> root still C, major
    assert identify_chord([64, 67, 72]) == (0, 'maj')


def test_root_plus_third_no_fifth_still_classifies():
    # C E (no fifth) -> major by the third alone
    assert identify_chord([60, 64]) == (0, 'maj')
    # C Eb (no fifth) -> minor by the third alone
    assert identify_chord([60, 63]) == (0, 'min')


def test_power_chord_has_no_third():
    # C G (root + fifth, no third) is not a chord we arp
    assert identify_chord([60, 67]) is None


def test_unison_is_not_a_chord():
    assert identify_chord([60, 72]) is None        # same pitch class
    assert identify_chord([60]) is None


def test_seventh_chords():
    assert identify_chord([60, 64, 67, 70]) == (0, 'dom7')   # C E G Bb
    assert identify_chord([60, 64, 67, 71]) == (0, 'maj7')   # C E G B
    assert identify_chord([57, 60, 64, 67]) == (9, 'min7')   # A C E G
    # the seventh is heard even without the fifth
    assert identify_chord([60, 64, 70]) == (0, 'dom7')       # C E Bb


def test_suspended_chords_need_the_fifth():
    assert identify_chord([60, 62, 67]) == (0, 'sus2')       # C D G, C bass
    assert identify_chord([55, 60, 62]) == (7, 'sus4')       # G C D, G bass
    # a bare fourth with no fifth is not a suspension
    assert identify_chord([60, 65]) is None                  # C F


def test_full_chord_outranks_a_partial_reading():
    # C E G + a stray ninth (D): C-major explains three notes, nothing more
    assert identify_chord([60, 62, 64, 67]) == (0, 'maj')
    # ...but C E G A is Am7 in first inversion: the reading that explains all
    # four notes beats the bare triad (C6 == Am7)
    assert identify_chord([60, 64, 67, 69]) == (9, 'min7')


def test_group_by_onset_buckets_and_sorts():
    notes = [Note(pitch=67, start=1.0, dur=1), Note(pitch=60, start=0.0, dur=1),
             Note(pitch=64, start=0.0, dur=1)]
    groups = group_by_onset(notes)
    assert [g[0].start for g in groups] == [0.0, 1.0]
    assert sorted(n.pitch for n in groups[0]) == [60, 64]


def test_group_by_onset_row_key_merges_humanised_chords():
    # a hand-played chord lands slightly staggered; grouping by the row it
    # quantises to must still see one chord
    notes = [Note(pitch=60, start=0.00, dur=1), Note(pitch=64, start=0.03, dur=1),
             Note(pitch=67, start=0.06, dur=1), Note(pitch=72, start=1.00, dur=1)]
    groups = group_by_onset(notes, key=lambda s: round(s * 4))
    assert len(groups) == 2
    assert sorted(n.pitch for n in groups[0]) == [60, 64, 67]
    assert [n.pitch for n in groups[1]] == [72]
