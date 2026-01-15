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
cloudinary.config(
    cloud_name = "dzwn8b3ax",
    api_key = "179391797818159",
    api_secret = "DfNDDAsqR2dAy4KH8sZa2_P7x2g",
    secure = True
)

# --- 2. DATABASE CONFIG (NEON) ---
raw_url = "postgresql://neondb_owner:npg_kqEm6hxCyWj2@ep-fragrant-moon-a18v84gz-pooler.ap-southeast-1.aws.neon.tech/neondb"

def fix_uri(uri):
    if not uri: return None
    uri = uri.strip()
    if "?" in uri: uri = uri.split("?")[0]
    return uri.replace("postgres://", "postgresql+pg8000://", 1).replace("postgresql://", "postgresql+pg8000://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = fix_uri(raw_url)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"connect_args": {"ssl_context": True}, "pool_pre_ping": True}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 3. MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    profile_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/d_avatar.png/v1/avatar.png')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationship para sa reactions sa user
    reactions = db.relationship('Reaction', backref='user', lazy=True)

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
    # KANI ANG GI-ADD PARA MA-FIX ANG ERROR:
    reactions = db.relationship('Reaction', backref='post', lazy='dynamic', cascade="all, delete-orphan")

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    type = db.Column(db.String(20), default='like')

with app.app_context():
    db.create_all()

# --- 4. HELPERS ---
@app.context_processor
def utility_processor():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()

    def get_read_time(content):
        if not content: return 1
        words = len(content.split())
        return max(1, words // 200)

    def time_ago(dt):
        if not dt: return ""
        now = datetime.utcnow()
        diff = now - dt
        if diff.days > 0:
            return f"{diff.days}d ago"
        if diff.seconds >= 3600:
            return f"{diff.seconds // 3600}h ago"
        if diff.seconds >= 60:
            return f"{diff.seconds // 60}m ago"
        return "just now"

    return dict(
        get_user_by_username=get_user_by_username, 
        get_read_time=get_read_time, 
        time_ago=time_ago
    )

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# --- 5. ROUTES ---
@app.route('/')
def public_home():
    posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).all()
    user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    return render_template('home_public.html', posts=posts, user=user)

@app.route('/dashboard')
@login_required
def dashboard():
    user = db.session.get(User, session['user_id'])
    posts = Post.query.all() if user.is_admin else Post.query.filter_by(author=user.username).all()
    return render_template('my_dashboard.html', posts=posts, user=user)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        slug = re.sub(r'[^a-zA-Z0-9 ]', '', title).replace(" ", "-").lower() + "-" + str(int(datetime.utcnow().timestamp()))
        media_url, media_type = None, None
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename != '':
                res = cloudinary.uploader.upload(file, resource_type="auto")
                media_url = res.get('secure_url')
                media_type = 'video' if 'video' in str(res.get('resource_type')) else 'image'
        
        new_post = Post(title=title, content=content, slug=slug, author=user.username,
                        approved=user.is_admin, media_file=media_url, media_type=media_type)
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('create_post.html')

@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    user = db.session.get(User, session['user_id'])
    if post.author != user.username and not user.is_admin:
        return "Unauthorized", 403
    if request.method == 'POST':
        post.title = request.form.get('title')
        post.content = request.form.get('content')
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('edit_post.html', post=post)

@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    user = db.session.get(User, session['user_id'])
    if post.author == user.username or user.is_admin:
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/approve/<int:post_id>')
@login_required
def approve_post(post_id):
    user = db.session.get(User, session['user_id'])
    if user.is_admin:
        post = Post.query.get_or_404(post_id)
        post.approved = True
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/reject/<int:post_id>')
@login_required
def reject_post(post_id):
    user = db.session.get(User, session['user_id'])
    if user.is_admin:
        post = Post.query.get_or_404(post_id)
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        hashed_pw = generate_password_hash(request.form['password'])
        is_first = User.query.count() == 0
        new_user = User(username=username, password=hashed_pw, is_admin=is_first)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
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

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
