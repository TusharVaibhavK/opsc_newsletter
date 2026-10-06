"""content/ validation: the real files pass, and broken ones fail loudly with every problem."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from collectors.config import CONTENT_DIR
from collectors.content import Content, ContentError, Cycle, CycleEvent, load_content


def test_real_content_is_valid(content: Content) -> None:
    assert len(content.programs) >= 20
    assert len(content.orgs) >= 20
    assert {w.org for w in content.watchlist} <= {o.slug for o in content.orgs}
    assert content.guide_slugs, "guides should exist"


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    target = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, target)
    return target


def test_malformed_yaml_is_reported(copy: Path) -> None:
    (copy / "programs" / "gsoc.yaml").write_text("slug: gsoc\nname: [unclosed\n", encoding="utf-8")
    with pytest.raises(ContentError) as err:
        load_content(copy)
    assert any("gsoc.yaml" in p for p in err.value.problems)


def test_cross_references_are_checked(copy: Path) -> None:
    watch = copy / "watchlist.yaml"
    watch.write_text(
        watch.read_text(encoding="utf-8")
        + "- org: no-such-org\n  status: exploring\n  priority: 2\n  next_action: x\n",
        encoding="utf-8",
    )
    org = copy / "orgs" / "kubeflow.yaml"
    org.write_text(
        org.read_text(encoding="utf-8").replace("- lfx-mentorship", "- not-a-program"),
        encoding="utf-8",
    )
    with pytest.raises(ContentError) as err:
        load_content(copy)
    problems = "\n".join(err.value.problems)
    assert "unknown org 'no-such-org'" in problems
    assert "unknown program 'not-a-program'" in problems


def test_slug_must_match_file_name(copy: Path) -> None:
    (copy / "programs" / "gsoc.yaml").rename(copy / "programs" / "google.yaml")
    with pytest.raises(ContentError) as err:
        load_content(copy)
    assert any("must match the file name" in p for p in err.value.problems)


def test_flow_must_link_to_existing_guides(copy: Path) -> None:
    (copy / "guides" / "proposal-kit.md").unlink()
    with pytest.raises(ContentError) as err:
        load_content(copy)
    assert any("missing guide 'proposal-kit'" in p for p in err.value.problems)


def test_cycle_dates_must_be_in_order() -> None:
    with pytest.raises(ValidationError):
        Cycle(
            name="Broken",
            events=[
                CycleEvent(kind="apply_open", date=dt.date(2027, 3, 31)),
                CycleEvent(kind="apply_close", date=dt.date(2027, 3, 1)),
            ],
        )


def test_month_precision_uses_first_of_month() -> None:
    with pytest.raises(ValidationError):
        CycleEvent(kind="start", date=dt.date(2027, 6, 15), precision="month")
    assert (
        CycleEvent(kind="start", date=dt.date(2027, 6, 1), precision="month").precision == "month"
    )


def test_crowded_orgs_need_a_reason(copy: Path) -> None:
    org = copy / "orgs" / "zulip.yaml"
    text = "\n".join(
        line
        for line in org.read_text(encoding="utf-8").splitlines()
        if not line.startswith("crowded_reason")
    )
    org.write_text(text + "\n", encoding="utf-8")
    with pytest.raises(ContentError) as err:
        load_content(copy)
    assert any("crowded_reason" in p for p in err.value.problems)
