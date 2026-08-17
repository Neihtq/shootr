"""XMP writeback tests (design 07). The highest data-loss-risk module —
every safety rule gets a test."""

import pytest

from shootr.xmp import (
    apply_export,
    export_csv,
    plan_export,
    read_sidecar_state,
    sidecar_path_for,
)

# A sidecar as LrC would write it: develop settings, keywords, and a
# third-party field we must not touch.
LRC_SIDECAR = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmp:Rating="1"
    crs:ProcessVersion="15.4"
    crs:Exposure2012="+0.55"
    crs:Contrast2012="-10">
   <dc:subject><rdf:Bag><rdf:li>wedding</rdf:li></rdf:Bag></dc:subject>
   <plugin:Data xmlns:plugin="http://example.com/">precious</plugin:Data>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""

PLAIN_SIDECAR = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmp:Rating="5">
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


@pytest.fixture
def lib(tmp_path):
    d = tmp_path / "lib"
    d.mkdir()
    return d


@pytest.fixture
def backups(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    return d


def raw(lib, name="IMG_1.CR3"):
    p = lib / name
    p.write_bytes(b"rawdata")
    return p


class TestPlan:
    def test_new_sidecar_planned(self, lib):
        plan = plan_export([(raw(lib), "pick")])
        assert len(plan.new_sidecars) == 1
        assert plan.new_sidecars[0].new_rating == 3

    def test_reject_writes_nothing(self, lib):
        """design 06 §1 — a mis-scored good photo must not get hidden."""
        plan = plan_export([(raw(lib), "reject")])
        assert not plan.new_sidecars and not plan.updates
        assert not plan.conflicts

    def test_dng_skipped_with_warning(self, lib):
        """A .dng.xmp is a no-op; never embed into the user's RAW
        (design 07 §3.1)."""
        plan = plan_export([(raw(lib, "IMG_1.DNG"), "pick")])
        assert plan.skipped_dng == [str(lib / "IMG_1.DNG")]
        assert not plan.new_sidecars

    def test_existing_develop_settings_is_conflict(self, lib):
        r = raw(lib)
        sidecar_path_for(r).write_text(LRC_SIDECAR)
        plan = plan_export([(r, "pick")])
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0].has_develop_settings
        assert not plan.updates  # not silently classified as safe

    def test_plain_sidecar_is_update_not_conflict(self, lib):
        r = raw(lib)
        sidecar_path_for(r).write_text(PLAIN_SIDECAR)
        plan = plan_export([(r, "pick")])
        assert len(plan.updates) == 1 and not plan.conflicts
        assert plan.updates[0].old_rating == 5

    def test_no_change_detected(self, lib):
        r = raw(lib)
        sidecar_path_for(r).write_text(
            PLAIN_SIDECAR.replace('xmp:Rating="5"',
                                  'xmp:Rating="2"'))
        plan = plan_export([(r, "alt")])  # alt → rating 2 = no change
        assert plan.unchanged and not plan.updates


class TestApply:
    def test_writes_new_sidecar(self, lib, backups):
        r = raw(lib)
        plan = plan_export([(r, "pick")])
        written = apply_export(plan, backups)
        assert written
        rating, label, _ = read_sidecar_state(sidecar_path_for(r))
        assert rating == 3 and label == "Shootr Pick"

    def test_conflicts_not_written_without_confirm(self, lib, backups):
        """Never a silent default-yes (design 07 §1 step 4)."""
        r = raw(lib)
        sidecar_path_for(r).write_text(LRC_SIDECAR)
        plan = plan_export([(r, "pick")])
        apply_export(plan, backups, confirm_conflicts=False)
        rating, _, _ = read_sidecar_state(sidecar_path_for(r))
        assert rating == 1  # untouched

    def test_confirmed_conflict_preserves_unowned_fields(self, lib, backups):
        """THE test for design 07 §1 step 6: develop settings, keywords, and
        third-party data survive our write byte-for-byte."""
        r = raw(lib)
        sidecar_path_for(r).write_text(LRC_SIDECAR)
        plan = plan_export([(r, "pick")])
        apply_export(plan, backups, confirm_conflicts=True)
        text = sidecar_path_for(r).read_text()
        assert 'xmp:Rating="3"' in text  # our field updated
        assert 'crs:Exposure2012="+0.55"' in text  # develop settings intact
        assert 'crs:ProcessVersion="15.4"' in text
        assert "<rdf:li>wedding</rdf:li>" in text  # keywords intact
        assert ">precious<" in text  # third-party plugin data intact

    def test_backup_created_before_overwrite(self, lib, backups):
        r = raw(lib)
        sidecar_path_for(r).write_text(LRC_SIDECAR)
        plan = plan_export([(r, "pick")])
        apply_export(plan, backups, confirm_conflicts=True)
        saved = list(backups.rglob("*.xmp"))
        assert len(saved) == 1
        assert saved[0].read_text() == LRC_SIDECAR  # pristine original

    def test_new_sidecar_needs_no_backup(self, lib, backups):
        plan = plan_export([(raw(lib), "pick")])
        apply_export(plan, backups)
        assert list(backups.rglob("*.xmp")) == []

    def test_atomic_no_temp_left_behind(self, lib, backups):
        r = raw(lib)
        plan = plan_export([(r, "pick")])
        apply_export(plan, backups)
        leftovers = [p for p in lib.iterdir() if ".tmp" in p.name]
        assert leftovers == []


class TestCsv:
    def test_only_picks_and_alts_listed(self, lib, tmp_path):
        out = tmp_path / "selects.csv"
        export_csv(
            [(lib / "a.CR3", "pick"), (lib / "b.CR3", "reject"),
             (lib / "c.CR3", "alt")],
            out,
        )
        text = out.read_text()
        assert "a.CR3,pick" in text and "c.CR3,alt" in text
        assert "b.CR3" not in text
