from app import app, db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    # 1. PAPASON TANANG USER PARA WALAY SAMOK
    User.query.delete()
    db.session.commit()
    
    # 2. MAGHIMO OG BAG-ONG ADMIN ACCOUNT
    # Pwede nimo usbon ang 'admin' sa imong gusto nga username
    hashed_pw = generate_password_hash('admin123')
    new_admin = User(username='admin', password=hashed_pw, is_admin=True)
    
    db.session.add(new_admin)
    db.session.commit()
    
    print("\n" + "="*30)
    print("✅ MASTER RESET SUCCESSFUL!")
    print("Username: admin")
    print("Password: admin733")
    print("Status: FULL ADMIN")
    print("="*30)
    print("\nI-run na ang 'python app.py' ug i-login ni.")
