"""SQLite persistence for snapshots, human reviews, and outreach workflow."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from schemas import GrowthMetrics, ManualReview, OutreachRecord, Snapshot


class RadarDatabase:
    def __init__(self, path: str = "ai_builder_radar.db") -> None:
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS repository_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_full_name TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    stars INTEGER,
                    forks INTEGER,
                    open_issues INTEGER,
                    contributors_count INTEGER,
                    pushed_at TEXT,
                    total_score REAL,
                    score_coverage REAL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_repo_time
                    ON repository_snapshots(repo_full_name, captured_at DESC);

                CREATE TABLE IF NOT EXISTS manual_reviews (
                    repo_full_name TEXT PRIMARY KEY,
                    relevant INTEGER NOT NULL,
                    worth_following INTEGER NOT NULL,
                    priority TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    reviewed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS outreach_status (
                    repo_full_name TEXT PRIMARY KEY,
                    builder TEXT NOT NULL,
                    why_relevant TEXT,
                    potential_collaboration TEXT,
                    suggested_outreach_angle TEXT,
                    public_profile_url TEXT,
                    status TEXT NOT NULL DEFAULT 'Not Reviewed',
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )

    def save_snapshot(self, snapshot: Snapshot) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO repository_snapshots (
                    repo_full_name, captured_at, stars, forks, open_issues,
                    contributors_count, pushed_at, total_score, score_coverage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.repo_full_name,
                    _iso(snapshot.captured_at),
                    snapshot.stars,
                    snapshot.forks,
                    snapshot.open_issues,
                    snapshot.contributors_count,
                    _iso(snapshot.pushed_at),
                    snapshot.total_score,
                    snapshot.score_coverage,
                ),
            )
            return int(cursor.lastrowid)

    def get_snapshots(self, repo_full_name: str, limit: int = 50) -> list[Snapshot]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM repository_snapshots
                WHERE repo_full_name = ?
                ORDER BY captured_at DESC LIMIT ?
                """,
                (repo_full_name, max(1, min(limit, 500))),
            ).fetchall()
        return [_snapshot_from_row(row) for row in rows]

    def get_growth(self, repo_full_name: str) -> GrowthMetrics:
        snapshots = self.get_snapshots(repo_full_name, 50)
        if len(snapshots) < 2:
            return GrowthMetrics()
        latest = snapshots[0]
        previous = next(
            (item for item in snapshots[1:] if item.captured_at != latest.captured_at),
            None,
        )
        if previous is None:
            return GrowthMetrics(reason="暂无两个不同时间点的历史快照")
        return GrowthMetrics(
            available=True,
            reason="基于最近两个不同时间点的本地快照",
            start_at=previous.captured_at,
            end_at=latest.captured_at,
            star_change=_difference(latest.stars, previous.stars),
            fork_change=_difference(latest.forks, previous.forks),
        )

    def save_manual_review(self, review: ManualReview) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO manual_reviews VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_full_name) DO UPDATE SET
                    relevant=excluded.relevant,
                    worth_following=excluded.worth_following,
                    priority=excluded.priority,
                    notes=excluded.notes,
                    reviewed_at=excluded.reviewed_at
                """,
                (
                    review.repo_full_name,
                    int(review.relevant),
                    int(review.worth_following),
                    review.priority,
                    review.notes,
                    _iso(review.reviewed_at),
                ),
            )

    def get_manual_reviews(self) -> list[ManualReview]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM manual_reviews ORDER BY reviewed_at DESC"
            ).fetchall()
        return [
            ManualReview(
                repo_full_name=row["repo_full_name"],
                relevant=bool(row["relevant"]),
                worth_following=bool(row["worth_following"]),
                priority=row["priority"],
                notes=row["notes"],
                reviewed_at=datetime.fromisoformat(row["reviewed_at"]),
            )
            for row in rows
        ]

    def precision_at_10(self, ranked_repo_names: list[str] | None = None) -> float | None:
        reviews = self.get_manual_reviews()
        if ranked_repo_names is None:
            if len(reviews) < 10:
                return None
            return sum(review.relevant for review in reviews[:10]) / 10
        top_ten = ranked_repo_names[:10]
        if len(top_ten) < 10:
            return None
        by_name = {review.repo_full_name: review for review in reviews}
        if any(name not in by_name for name in top_ten):
            return None
        return sum(by_name[name].relevant for name in top_ten) / 10

    def save_outreach(self, record: OutreachRecord) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO outreach_status VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_full_name) DO UPDATE SET
                    builder=excluded.builder,
                    why_relevant=excluded.why_relevant,
                    potential_collaboration=excluded.potential_collaboration,
                    suggested_outreach_angle=excluded.suggested_outreach_angle,
                    public_profile_url=excluded.public_profile_url,
                    status=excluded.status,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    record.repo_full_name,
                    record.builder,
                    record.why_relevant,
                    record.potential_collaboration,
                    record.suggested_outreach_angle,
                    record.public_profile_url,
                    record.status,
                    record.notes,
                    _iso(record.updated_at),
                ),
            )

    def get_outreach(self) -> list[OutreachRecord]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM outreach_status ORDER BY updated_at DESC"
            ).fetchall()
        return [OutreachRecord.model_validate(dict(row)) for row in rows]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _difference(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous


def _snapshot_from_row(row: sqlite3.Row) -> Snapshot:
    return Snapshot(
        id=row["id"],
        repo_full_name=row["repo_full_name"],
        captured_at=datetime.fromisoformat(row["captured_at"]),
        stars=row["stars"],
        forks=row["forks"],
        open_issues=row["open_issues"],
        contributors_count=row["contributors_count"],
        pushed_at=(
            datetime.fromisoformat(row["pushed_at"]) if row["pushed_at"] else None
        ),
        total_score=row["total_score"],
        score_coverage=row["score_coverage"],
    )
