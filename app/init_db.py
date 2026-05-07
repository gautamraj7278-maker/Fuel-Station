from app.database import engine, Base
from app import models

def init_db():
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("Done!")

if __name__ == "__main__":
    init_db()