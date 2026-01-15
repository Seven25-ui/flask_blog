from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime
from functools import wraps
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")

# --- 1. CLOUDINARY CONFIG ---
# Mogamit ni sa CLOUDINARY_URL variable sa Render, pero naay backup
cloudinary.config(
    cloudinary_url=os.environ.get("CLOUDINARY_URL", "cloudinary://179391797818159:DfNDDAsqR2dAy4KH8sZa2_P7x2g@dzwn8b3ax"),
    secure=True
)

# --- 2. DATABASE CONFIG ---
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Kani ang importante para sa Neon + Termux/Render compatibility
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+pg8000://", 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    print("✅ RENDER LOG: CONNECTED TO NEON POSTGRESQL!")
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
    print("⚠️ WARNING: DATABASE_URL NOT FOUND! USING SQLITE...")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- 3. INITIALIZE DB ---
db = SQLAlchemy(app)

# --- 4. MODELS ---
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    type = db.Column(db.String(20))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id])

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='messages')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    profile_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/d_avatar.png/v1/avatar.png')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notifications = db.relationship('Notification', foreign_keys=[Notification.recipient_id], backref='recipient', lazy='dynamic')

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    author = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved = db.Column(db.Boolean, default=False)
    media_file = db.Column(db.String(500), nullable=True)
    media_type = db.Column(db.String(10), nullable=True)
    reactions = db.relationship('Reaction', backref='post', lazy='dynamic', cascade="all, delete-orphan")
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade="all, delete-orphan")

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='user_comments')

# Kani mag-create sa tables sa Neon kon wala pa
with app.app_context():
    db.create_all()

# --- 5. HELPERS ---
@app.context_processor
def utility_processor():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()
    def get_read_time(content):
        if not content: return 0
        words = len(content.split())
        return max(1, round(words / 200))
    def time_ago(dt):
        if not dt: return ""
        now = datetime.utcnow()
        diff = now - dt
        if diff.days > 30: return dt.strftime('%b %d')
        if diff.days > 0: return f"{diff.days}d ago"
        if diff.seconds > 3600: return f"{diff.seconds // 3600}h ago"
        if diff.seconds > 60: return f"{diff.seconds // 60}m ago"
        return "Just now"
    return dict(get_user_by_username=get_user_by_username, get_read_time=get_read_time, time_ago=time_ago)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# --- 6. ROUTES ---
@app.route('/')
def public_home():
    posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).all()
    user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    return render_template('home_public.html', posts=posts, user=user)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        try:
            title = request.form.get('title')
            content = request.form.get('content')
            slug = re.sub(r'[^a-zA-Z0-9 ]', '', title).replace(" ", "-").lower() + "-" + str(int(datetime.utcnow().timestamp()))
            media_url, media_type = None, None
            
            if 'media_file' in request.files:
                file = request.files['media_file']
                if file and file.filename != '':
                    upload_result = cloudinary.uploader.upload(file, resource_type="auto")
                    media_url = upload_result.get('secure_url')
                    media_type = 'video' if 'video' in str(upload_result.get('resource_type', '')) else 'image'
            
            new_post = Post(title=title, content=content, slug=slug, author=user.username,
                            approved=user.is_admin, media_file=media_url, media_type=media_type)
            db.session.add(new_post)
            db.session.commit()
            flash("Post created successfully!")
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}")
            return redirect(url_for('create_post'))
    return render_template('create_post.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = db.session.get(User, session.get('user_id'))
    if user.is_admin:
        posts = Post.query.order_by(Post.created_at.desc()).all()
    else:
        posts = Post.query.filter_by(author=user.username).order_by(Post.created_at.desc()).all()
    return render_template('my_dashboard.html', posts=posts, user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        if User.query.filter_by(username=username).first():
            flash("Username already exists!")
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(request.form['password'])
        is_first = User.query.count() == 0
        new_user = User(username=username, password=hashed_pw, is_admin=is_first)
        db.session.add(new_user)
        db.session.commit()
        flash("Registered successfully! Please login.")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        flash("Sayop imong username o password!")
    return render_template('login.html')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        user.bio = request.form.get('bio')
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename != '':
                res = cloudinary.uploader.upload(file)
                user.profile_pic = res.get('secure_url')
        db.session.commit()
        flash("Profile updated!")
        return redirect(url_for('dashboard'))
    return render_template('profile_settings.html', user=user)

@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()
    return render_template('view_post.html', post=post)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('public_home'))

@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    user = db.session.get(User, session['user_id'])
    if post.author == user.username or user.is_admin:
        db.session.delete(post)
        db.session.commit()
        flash("Post deleted!")
    return redirect(url_for('dashboard'))

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
