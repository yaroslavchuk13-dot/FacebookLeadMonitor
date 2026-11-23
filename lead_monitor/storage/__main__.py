"""Shows database statistics and the latest leads: `python -m lead_monitor.storage [N]`."""

import sys

from lead_monitor.core.config import get_settings
from lead_monitor.storage.database import Database


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10
    settings = get_settings()
    if not settings.database_path.exists():
        print(f"База ще не створена: {settings.database_path}")
        print("Запустіть сервер і моніторинг у розширенні — база з'явиться після перших дописів.")
        return 0

    db = Database(settings.database_path)
    try:
        s = db.stats()
        print(f"База: {settings.database_path}")
        print(
            f"Дописів: {s['total']} | лідів: {s['leads']} | дублікатів: {s['duplicates']} "
            f"| груп: {s['groups']}"
        )
        leads = db.recent_leads(limit)
        print(f"\nОстанні ліди ({len(leads)}):")
        for lead in leads:
            keywords = ", ".join(lead["matched_keywords"]) or "фільтр вимкнено"
            text = lead["text"].replace("\n", " ")
            print(
                f"\n#{lead['id']}  {lead['saved_at']}  [{lead['group_name'] or lead['group_id']}]\n"
                f"  Автор: {lead['author_name'] or '(анонімно)'}  |  ключові: {keywords}\n"
                f"  {text[:200]}{'…' if len(text) > 200 else ''}\n"
                f"  {lead['post_url']}"
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
