from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader

# --- APP SETUP ---
app = Flask(__name__, instance_relative_config=True)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")
os.makedirs(app.instance_path, exist_ok=True)

# --- CLOUDINARY CONFIG ---
# Kini automatic na mobasa sa 'CLOUDINARY_URL' variable gikan sa Render
cloudinary.config(secure=True)

# --- DATABASE CONFIG ---
if os.environ.get('DATABASE_URL'):
    database_url = os.environ.get('DATABASE_URL')
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
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
    # Default avatar gikan sa Cloudinary
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
    media_file = db.Column(db.String(500), nullable=True) # Cloudinary URL
    media_type = db.Column(db.String(10), nullable=True)

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    post = db.relationship('Post', backref=db.backref('reactions', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('reactions', lazy='dynamic'))

with app.app_context():
    db.create_all()

# --- HELPERS ---
def make_slug(title):
    slug = re.sub(r'[^a-zA-Z0-9 ]', '', title)
    return slug.replace(" ", "-").lower()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please login first!")
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

# --- ROUTES ---
@app.route('/')
@app.route('/public')
def public_home():
    posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).all()
    user = User.query.get(session['user_id']) if session.get('user_id') else None
    return render_template('home_public.html', posts=posts, user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        if User.query.filter_by(username=username).first():
            flash("Username exists!")
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(request.form['password'])
        is_admin = not User.query.first()
        db.session.add(User(username=username, password=hashed_pw, is_admin=is_admin))
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
        flash("Invalid credentials")
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    if user.is_admin:
        posts = Post.query.order_by(Post.created_at.desc()).all()
    else:
        posts = Post.query.filter_by(author=user.username).order_by(Post.created_at.desc()).all()
    return render_template('my_dashboard.html', posts=posts, user=user)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        tags = request.form.get('tags', '')
        slug = make_slug(title)
        media_url = None
        m_type = None

        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename != '':
                # I-upload sa Cloudinary (automatic image/video detection)
                upload_result = cloudinary.uploader.upload(file, resource_type="auto")
                media_url = upload_result['secure_url']
                
                # Mas maayo nga checking sa media type gikan sa Cloudinary result
                m_type = 'video' if upload_result['resource_type'] == 'video' else 'image'

        post = Post(title=title, content=content, slug=slug, author=user.username,
                    approved=user.is_admin, tags=tags, media_file=media_url, media_type=m_type)
        db.session.add(post)
        db.session.commit()
        flash("Post submitted!")
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', post=None)

@app.route('/profile/settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        user.bio = request.form.get('bio', '')
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename != '':
                upload_result = cloudinary.uploader.upload(file)
                user.profile_pic = upload_result['secure_url']
        db.session.commit()
        flash("Profile updated!")
        return redirect(url_for('dashboard'))
    return render_template('profile_settings.html', user=user)

@app.route('/react/<int:post_id>', methods=['POST'])
@login_required
def react(post_id):
    user_id = session['user_id']
    reaction_type = request.form.get('type')
    existing = Reaction.query.filter_by(post_id=post_id, user_id=user_id).first()
    if existing:
        if existing.type == reaction_type:
            db.session.delete(existing)
        else:
            existing.type = reaction_type
    else:
        db.session.add(Reaction(post_id=post_id, user_id=user_id, type=reaction_type))
    db.session.commit()
    return jsonify(success=True)

@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug, approved=True).first_or_404()
    return render_template('view_post.html', post=post)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
