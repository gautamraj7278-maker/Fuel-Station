"""
Quick Admin Setup Script
Run this script to create your first admin user easily!
"""
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app import models
from app.auth import get_password_hash

def init_admin():
    """Create initial admin user"""
    db = SessionLocal()
    
    try:
        # Check if admin already exists
        existing_admin = db.query(models.User).filter(
            models.User.username == "admin"
        ).first()
        
        if existing_admin:
            print("✓ Admin user already exists!")
            print(f"  Username: {existing_admin.username}")
            print(f"  Email: {existing_admin.email}")
            print(f"  Role: {existing_admin.role}")
            return
        
        # Create admin user
        admin_user = models.User(
            username="admin",
            email="admin@fuelstation.com",
            hashed_password=get_password_hash("admin123"),
            full_name="System Administrator",
            role=models.UserRole.ADMIN,
            is_active=True
        )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        print("\n" + "="*50)
        print("✓ Admin User Created Successfully!")
        print("="*50)
        print(f"\n  Username: admin")
        print(f"  Password: admin123")
        print(f"  Email: admin@fuelstation.com")
        print(f"\n  Login at: http://localhost:3000/login")
        print(f"  API Docs: http://localhost:8000/docs")
        print("\n" + "="*50)
        print("\n⚠️  IMPORTANT: Change the password after first login!")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        db.rollback()
    finally:
        db.close()


def init_inventory():
    """Initialize default fuel inventory"""
    db = SessionLocal()
    
    try:
        fuel_types = [
            {
                "fuel_type": models.FuelType.PETROL,
                "current_stock": 0.0,
                "price_per_liter": 0.0,
                "reorder_level": 0.0
            },
            {
                "fuel_type": models.FuelType.DIESEL,
                "current_stock": 0.0,
                "price_per_liter": 0.0,
                "reorder_level": 0.0
            },
            {
                "fuel_type": models.FuelType.PREMIUM,
                "current_stock": 0.0,
                "price_per_liter": 0.0,
                "reorder_level": 0.0
            }
        ]
        
        print("\nInitializing Fuel Inventory...")
        
        for fuel_data in fuel_types:
            existing = db.query(models.FuelInventory).filter(
                models.FuelInventory.fuel_type == fuel_data["fuel_type"]
            ).first()
            
            if existing:
                print(f"  • {fuel_data['fuel_type'].value.upper()}: Already exists")
            else:
                inventory = models.FuelInventory(**fuel_data)
                db.add(inventory)
                
                # Log the initialization
                log = models.InventoryLog(
                    fuel_type=fuel_data["fuel_type"],
                    action="initialize",
                    quantity=fuel_data["current_stock"],
                    previous_stock=0,
                    new_stock=fuel_data["current_stock"],
                    notes="Initial inventory setup"
                )
                db.add(log)
                print(f"  ✓ {fuel_data['fuel_type'].value.upper()}: {fuel_data['current_stock']} liters @ ${fuel_data['price_per_liter']}/L")
        
        db.commit()
        print("✓ Inventory initialized successfully!\n")
        
    except Exception as e:
        print(f"❌ Error initializing inventory: {e}")
        db.rollback()
    finally:
        db.close()


def init_pumps():
    """Initialize default pumps"""
    db = SessionLocal()
    
    try:
        dispensers_data = [
            {"dispenser_number": "P001", "fuel_type": models.FuelType.PETROL},
            {"dispenser_number": "P002", "fuel_type": models.FuelType.PETROL},
            {"dispenser_number": "D001", "fuel_type": models.FuelType.DIESEL},
            {"dispenser_number": "D002", "fuel_type": models.FuelType.DIESEL},
            {"dispenser_number": "PR01", "fuel_type": models.FuelType.PREMIUM},
        ]
        
        print("Initializing Pumps...")
        
        for dispenser_data in dispensers_data:
            existing = db.query(models.Dispenser).filter(
                models.Dispenser.dispenser_number == dispenser_data["dispenser_number"]
            ).first()
            
            if existing:
                print(f"  • {dispenser_data['dispenser_number']}: Already exists")
            else:
                dispenser = models.Dispenser(**dispenser_data, is_active=True)
                db.add(dispenser)
                print(f"  ✓ {dispenser_data['dispenser_number']}: {dispenser_data['fuel_type'].value.upper()}")
        
        db.commit()
        print("✓ Pumps initialized successfully!\n")
        
    except Exception as e:
        print(f"❌ Error initializing pumps: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("\n" + "="*50)
    print("FUEL STATION - QUICK SETUP")
    print("="*50 + "\n")
    
    # Create all tables
    print("Creating database tables...")
    models.Base.metadata.create_all(bind=engine)
    print("✓ Database tables ready!\n")
    
    # Initialize everything
    init_admin()
    init_inventory()
    init_pumps()
    
    print("\n" + "="*50)
    print("🎉 SETUP COMPLETE!")
    print("="*50)
    print("\nYou can now:")
    print("  1. Start the backend: uvicorn main:app --reload")
    print("  2. Start the frontend: cd frontend && npm run dev")
    print("  3. Login with username 'admin' and password 'admin123'")
    print("\n" + "="*50 + "\n")
