from datetime import UTC, datetime, timedelta

from database import RadarDatabase
from schemas import ManualReview, Snapshot


def test_first_snapshot_has_no_growth(tmp_path):
    database = RadarDatabase(str(tmp_path / "radar.db"))
    database.save_snapshot(
        Snapshot(
            repo_full_name="owner/repo",
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            stars=10,
            forks=2,
        )
    )
    growth = database.get_growth("owner/repo")
    assert growth.available is False
    assert growth.reason == "暂无历史快照"


def test_two_snapshots_calculate_real_changes_and_times(tmp_path):
    database = RadarDatabase(str(tmp_path / "radar.db"))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=7)
    database.save_snapshot(
        Snapshot(repo_full_name="owner/repo", captured_at=start, stars=10, forks=2)
    )
    database.save_snapshot(
        Snapshot(repo_full_name="owner/repo", captured_at=end, stars=17, forks=5)
    )
    growth = database.get_growth("owner/repo")
    assert growth.available is True
    assert growth.star_change == 7
    assert growth.fork_change == 3
    assert growth.start_at == start
    assert growth.end_at == end


def test_precision_at_10_requires_ten_labels(tmp_path):
    database = RadarDatabase(str(tmp_path / "radar.db"))
    now = datetime.now(UTC)
    for index in range(9):
        database.save_manual_review(
            ManualReview(
                repo_full_name=f"owner/repo-{index}",
                relevant=True,
                worth_following=True,
                priority="High",
                reviewed_at=now + timedelta(seconds=index),
            )
        )
    assert database.precision_at_10() is None
    database.save_manual_review(
        ManualReview(
            repo_full_name="owner/repo-9",
            relevant=False,
            worth_following=False,
            priority="Low",
            reviewed_at=now + timedelta(seconds=9),
        )
    )
    assert database.precision_at_10() == 0.9
