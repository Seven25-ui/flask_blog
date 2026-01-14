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

# --- CLOUDINARY CONFIG ---
os.environ["CLOUDINARY_URL"] = "cloudinary://179391797818159:DfNDDAsqR2dAy4KH8sZa2_P7x2g@dzwn8b3ax"
cloudinary.config(secure=True)

# --- DATABASE CONFIG ---
if os.environ.get('DATABASE_URL'):
    database_url = os.environ.get('DATABASE_URL').replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"connect_args": {"sslmode": "require"}}
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)

with app.app_context():
    db.create_all()

# --- HELPERS ---
@app.context_processor
def utility_processor():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()

    def get_read_time(content):
        if not content: return 0
        words = len(content.split())
        return max(1, round(words / 200))

    return dict(get_user_by_username=get_user_by_username, get_read_time=get_read_time)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# --- ROUTES ---

@app.route('/')
def public_home():
    posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).all()
    user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    return render_template('home_public.html', posts=posts, user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        hashed_pw = generate_password_hash(request.form['password'])
        is_first = User.query.count() == 0
        db.session.add(User(username=request.form['username'], password=hashed_pw, is_admin=is_first))
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
        flash("Sayop imong username o password!")
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = db.session.get(User, session.get('user_id'))
    if not user:
        session.clear()
        flash("Session expired. Please log in again.")
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
        slug = re.sub(r'[^a-zA-Z0-9 ]', '', title).replace(" ", "-").lower()

        media_url, media_type = None, None
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file.filename != '':
                upload_result = cloudinary.uploader.upload(file, resource_type="auto")
                media_url = upload_result['secure_url']
                media_type = 'video' if 'video' in upload_result.get('resource_type', '') else 'image'

        new_post = Post(
            title=title, content=content, slug=slug,
            author=user.username, approved=user.is_admin,
            media_file=media_url, media_type=media_type
        )
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', post=None)

@app.route('/profile/<string:username>')
def view_profile(username):
    target_user = User.query.filter_by(username=username).first_or_404()
    user_posts = Post.query.filter_by(author=username, approved=True).order_by(Post.created_at.desc()).all()
    logged_in_user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    return render_template('profile.html', target_user=target_user, posts=user_posts, user=logged_in_user)

@app.route('/profile/settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        user.bio = request.form.get('bio')
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file.filename != '':
                upload_result = cloudinary.uploader.upload(file)
                user.profile_pic = upload_result['secure_url']
        db.session.commit()
        flash("Profile updated!")
        return redirect(url_for('dashboard'))
    return render_template('profile_settings.html', user=user)

@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = db.session.get(Post, post_id)
    user = db.session.get(User, session['user_id'])
    if not post or (post.author != user.username and not user.is_admin):
        flash("Unauthorized!")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        post.title = request.form.get('title')
        post.content = request.form.get('content')
        post.slug = re.sub(r'[^a-zA-Z0-9 ]', '', post.title).replace(" ", "-").lower()

        if 'media_file' in request.files:
            file = request.files['media_file']
            if file.filename != '':
                upload_result = cloudinary.uploader.upload(file, resource_type="auto")
                post.media_file = upload_result['secure_url']
                post.media_type = 'video' if 'video' in upload_result.get('resource_type', '') else 'image'

        db.session.commit()
        flash("Post updated!")
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', post=post)

@app.route('/react/<int:post_id>/<string:reac_type>', methods=['POST'])
@login_required
def react(post_id, reac_type):
    user_id = session['user_id']
    existing = Reaction.query.filter_by(post_id=post_id, user_id=user_id).first()
    if existing:
        existing.type = reac_type
    else:
        db.session.add(Reaction(post_id=post_id, user_id=user_id, type=reac_type))
    db.session.commit()
    return jsonify({"count": Reaction.query.filter_by(post_id=post_id).count()})

@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = db.session.get(Post, post_id)
    if post:
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/approve/<int:post_id>')
@login_required
def approve_post(post_id):
    post = db.session.get(Post, post_id)
    if post:
        post.approved = True
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/reject/<int:post_id>')
@login_required
def reject_post(post_id):
    post = db.session.get(Post, post_id)
    if post:
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()
    return render_template('view_post.html', post=post)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
