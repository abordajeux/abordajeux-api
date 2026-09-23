import sqlite3

import httpx

from app import db as db_mod
from app import signups
from app.config import load_settings
from app.email import SENDER_NAME, BrevoSender, build_promotion_email

_DELETE_EXPIRED_SQL = ("DELETE FROM signups WHERE confirmed_at IS NULL "
                       "AND created_at <= datetime('now', '-24 hours')")


def purge_expired(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(_DELETE_EXPIRED_SQL)
    return cursor.rowcount


def _send_promotion(sender: BrevoSender, promotion: signups.Promotion) -> None:
    sender.send(to_email=promotion.contact_email,
                content=build_promotion_email(
                    activity_title=promotion.activity_title,
                    starts_at=promotion.activity_starts_at,
                ))


def main() -> int:
    settings = load_settings()
    conn = db_mod.connect(settings.database_path)
    try:
        db_mod.init_schema(conn)
        deleted = purge_expired(conn)
        with httpx.Client(timeout=10.0) as client:
            sender = BrevoSender(
                client,
                api_key=settings.mail_api_key,
                sender_email=settings.mail_sender,
                sender_name=SENDER_NAME,
            )
            report = signups.promote_waitlisted(
                conn, lambda p: _send_promotion(sender, p))
    finally:
        conn.close()
    print(f"purged {deleted} expired signups")
    print(f"promoted {len(report.promoted)} waitlisted signups")
    for promotion in report.failed:
        print(f"promotion email failed for {promotion.contact_email} "
              f"({promotion.activity_id}); seat kept, will retry next run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
