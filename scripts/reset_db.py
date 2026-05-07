import os
from sqlalchemy import create_engine

from app import models
from app.config import settings


def main() -> None:
    url = os.getenv("DATABASE_URL", settings.database_url)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if "sqlite" in url else {},
    )
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
    print("Database reset complete.")


if __name__ == "__main__":
    main()
