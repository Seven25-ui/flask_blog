from app import app, db, User

with app.app_context():
    # ILISI NI SA IMONG USERNAME:
    user = User.query.filter_by(username='aloy').first()
    if user:
        user.is_admin = True
        db.session.commit()
        print(f"✅ Success! {user.username} is now an ADMIN.")
    else:
        print("❌ Error: Username not found.")
