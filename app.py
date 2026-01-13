from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime
from functools import wraps
import cloudinary
import cloudinary.uploader

# --- APP SETUP ---
app = Flask(__name__, instance_relative_config=True)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")
os.makedirs(app.instance_path, exist_ok=True)

# --- CLOUDINARY CONFIG ---
cloudinary_url = os.environ.get('CLOUDINARY_URL')
if cloudinary_url:
    cloudinary.config(cloudinary_url=cloudinary_url, secure=True)

# --- DATABASE CONFIG (POSTGRES) ---
if os.environ.get('DATABASE_URL'):
    database_url = os.environ.get('DATABASE_URL')
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local fallback only
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'blog.db')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    profile_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/d_avatar.png/v1/avatar.png')

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    author = db.Column(db.String(80), nullable=False, default="Guest")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved = db.Column(db.Boolean, default=False)
    tags = db.Column(db.String(200), nullable=True)
    media_file = db.Column(db.String(500), nullable=True)
    media_type = db.Column(db.String(10), nullable=True)

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    post = db.relationship('Post', backref=db.backref('reactions', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('reactions', lazy='dynamic'))

# --- DATABASE INITIALIZATION & AUTO-ADMIN ---
with app.app_context():
    db.create_all()
    
    # EMERGENCY AUTO-ADMIN: If the DB is empty or reset, create 'admin'
    admin_check = User.query.filter_by(username="admin").first()
    if not admin_check:
        hashed_pw = generate_password_hash("admin733") # Use this password to login
        new_admin = User(
            username="admin", 
            password=hashed_pw, 
            is_admin=True,
            bio="The Creator of Seven33"
        )
        db.session.add(new_admin)
        db.session.commit()
        print(">>> [SYSTEM] Postgres Admin Created: User: admin | Pass: admin733")

# --- HELPERS ---
def make_slug(title):
    slug = re.sub(r'[^a-zA-Z0-9 ]', '', title)
    return slug.replace(" ", "-").lower()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please log in to continue.")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.context_processor
def utility_processor():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()
    def get_read_time(content):
        words = len(content.split())
        return max(1, words // 200)
    return dict(get_user_by_username=get_user_by_username, get_read_time=get_read_time)

# --- MAIN ROUTES ---
@app.route('/')
@app.route('/public')
def public_home():
    posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).all()
    user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    return render_template('home_public.html', posts=posts, user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        if User.query.filter_by(username=username).first():
            flash("Username already exists.")
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(request.form['password'])
        db.session.add(User(username=username, password=hashed_pw, is_admin=False))
        db.session.commit()
        flash("Registration successful! Please sign in.")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    if user.is_admin:
        posts = Post.query.order_by(Post.created_at.desc()).all()
    else:
        posts = Post.query.filter_by(author=user.username).order_by(Post.created_at.desc()).all()
    return render_template('my_dashboard.html', posts=posts, user=user)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        tags = request.form.get('tags', '')
        slug = make_slug(title)

        if Post.query.filter_by(slug=slug).first():
            flash("Error: This title is already taken.")
            return redirect(url_for('create_post'))

        media_url, m_type = None, None
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename != '':
                upload_result = cloudinary.uploader.upload(file, resource_type="auto")
                media_url = upload_result.get('secure_url')
                m_type = 'video' if upload_result.get('resource_type') == 'video' else 'image'

        post = Post(title=title, content=content, slug=slug, author=user.username,
                    approved=user.is_admin, tags=tags, media_file=media_url, media_type=m_type)
        db.session.add(post)
        db.session.commit()
        
        flash("Post submitted!")
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', post=None)

@app.route('/react/<int:post_id>/<type>', methods=['POST'])
def react(post_id, type):
    if not session.get('user_id'):
        return jsonify({'error': 'Unauthorized'}), 401
    user_id = session['user_id']
    existing = Reaction.query.filter_by(post_id=post_id, user_id=user_id, type=type).first()
    if existing:
        db.session.delete(existing)
    else:
        Reaction.query.filter_by(post_id=post_id, user_id=user_id).delete()
        db.session.add(Reaction(post_id=post_id, user_id=user_id, type=type))
    db.session.commit()
    count = Reaction.query.filter_by(post_id=post_id, type=type).count()
    return jsonify({'count': count, 'type': type})

@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = db.session.get(Post, post_id)
    user = db.session.get(User, session['user_id'])
    if not post or (post.author != user.username and not user.is_admin):
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        post.title = request.form.get('title')
        post.content = request.form.get('content')
        db.session.commit()
        flash("Post updated!")
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', post=post)

@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = db.session.get(Post, post_id)
    user = db.session.get(User, session['user_id'])
    if post and (post.author == user.username or user.is_admin):
        db.session.delete(post)
        db.session.commit()
        flash("Post deleted.")
    return redirect(url_for('dashboard'))

@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug, approved=True).first_or_404()
    user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    return render_template('view_post.html', post=post, user=user)

@app.route('/profile/settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        user.bio = request.form.get('bio', '')
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename != '':
                res = cloudinary.uploader.upload(file)
                user.profile_pic = res.get('secure_url')
        db.session.commit()
        flash("Profile updated!")
        return redirect(url_for('dashboard'))
    return render_template('profile_settings.html', user=user)

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out.")
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=False)
