from app.database import engine, Base
import app.models  # important: ensures all models are loaded

print("Creating database tables...")

Base.metadata.create_all(bind=engine)

print("Done: tables created successfully")