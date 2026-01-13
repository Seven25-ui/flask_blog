from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
import uuid

# --- APP SETUP ---
app = Flask(__name__, instance_relative_config=True)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")
os.makedirs(app.instance_path, exist_ok=True)

# --- DATABASE CONFIG ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'blog.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- FILE UPLOAD CONFIG ---
UPLOAD_FOLDER = os.path.join(app.instance_path, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov', 'webm'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    profile_pic = db.Column(db.String(200), default='default-avatar.png')

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    author = db.Column(db.String(80), nullable=False, default="Guest")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved = db.Column(db.Boolean, default=False)
    tags = db.Column(db.String(200), nullable=True)
    media_file = db.Column(db.String(200), nullable=True)
    media_type = db.Column(db.String(10), nullable=True) # 'image' or 'video'

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

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = User.query.get(session.get('user_id'))
        if not user or not user.is_admin:
            flash("Admin access required!")
            return redirect(url_for('public_home'))
        return f(*args, **kwargs)
    return decorated

def get_read_time(content):
    if not content: return 1
    words = len(content.split())
    minutes = round(words / 200)
    return minutes if minutes > 0 else 1

@app.context_processor
def utility_processor():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()
    return dict(get_user_by_username=get_user_by_username, get_read_time=get_read_time)

# --- ROUTES ---

@app.route('/')
@app.route('/public')
@app.route('/public/page/<int:page>')
def public_home(page=1):
    per_page = 5
    posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    user = User.query.get(session['user_id']) if session.get('user_id') else None
    return render_template('home_public.html', posts=posts, user=user)

@app.route('/profile/<username>')
def public_profile(username):
    user_profile = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(author=username, approved=True).order_by(Post.created_at.desc()).all()
    return render_template('public_profile.html', user_profile=user_profile, posts=posts)

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

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        tags = request.form.get('tags', '')
        slug = make_slug(title)
        filename = None
        m_type = None
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                m_type = 'video' if ext in ['mp4', 'mov', 'webm'] else 'image'
        post = Post(title=title, content=content, slug=slug, author=user.username,
                    approved=user.is_admin, tags=tags, media_file=filename, media_type=m_type)
        db.session.add(post)
        db.session.commit()
        flash("Post submitted!")
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', post=None)

@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    user = User.query.get(session['user_id'])
    if post.author != user.username and not user.is_admin:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        post.title = request.form['title']
        post.content = request.form['content']
        post.tags = request.form.get('tags', '')
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                post.media_file = filename
                post.media_type = 'video' if ext in ['mp4', 'mov', 'webm'] else 'image'
        db.session.commit()
        flash("Post updated!")
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', post=post)

@app.route('/approve/<int:post_id>')
@admin_required
def approve_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.approved = True
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/reject/<int:post_id>')
@admin_required
def reject_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/media/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    if user.is_admin:
        posts = Post.query.order_by(Post.created_at.desc()).all()
    else:
        posts = Post.query.filter_by(author=user.username).order_by(Post.created_at.desc()).all()
    return render_template('my_dashboard.html', posts=posts, user=user)

@app.route('/profile/settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        user.bio = request.form.get('bio', '')
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}.{file.filename.rsplit('.', 1)[1].lower()}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                user.profile_pic = filename
        db.session.commit()
        flash("Profile updated!")
        return redirect(url_for('dashboard'))
    return render_template('profile_settings.html', user=user)

@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug, approved=True).first_or_404()
    return render_template('view_post.html', post=post)

@app.route('/react/<int:post_id>', methods=['POST'])
@login_required
def react(post_id):
    reaction_type = request.form.get('type')
    user_id = session['user_id']
    user_reaction = Reaction.query.filter_by(user_id=user_id, post_id=post_id).first()
    if user_reaction:
        if user_reaction.type == reaction_type:
            db.session.delete(user_reaction)
        else:
            user_reaction.type = reaction_type
    else:
        db.session.add(Reaction(user_id=user_id, post_id=post_id, type=reaction_type))
    db.session.commit()
    return jsonify(status='ok')

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
