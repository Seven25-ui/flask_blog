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
app.secret_key = "aloy_super_secret_key_733"

# --- 1. CONFIG ---
cloudinary.config(
    cloud_name = "dzwn8b3ax",
    api_key = "179391797818159",
    api_secret = "DfNDDAsqR2dAy4KH8sZa2_P7x2g",
    secure = True
)

raw_url = "postgresql://neondb_owner:npg_kqEm6hxCyWj2@ep-fragrant-moon-a18v84gz-pooler.ap-southeast-1.aws.neon.tech/neondb"

def fix_uri(uri):
    return uri.replace("postgres://", "postgresql+pg8000://", 1).replace("postgresql://", "postgresql+pg8000://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = fix_uri(raw_url)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- 2. MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    profile_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/v1/avatar.png')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Post(db.Model):
    __table_args__ = {'extend_existing': True}
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
    type = db.Column(db.String(20), default='like')

# --- 3. HELPERS & UTILITIES ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.context_processor
def utility_processor():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()

    def get_read_time(content):
        words_per_minute = 200
        words = len(content.split())
        return max(1, round(words / words_per_minute))

    def time_ago(date):
        if not date: return ""
        now = datetime.utcnow()
        diff = now - date
        periods = (
            (diff.days // 365, "year", "years"),
            (diff.days // 30, "month", "months"),
            (diff.days // 7, "week", "weeks"),
            (diff.days, "day", "days"),
            (diff.seconds // 3600, "hour", "hours"),
            (diff.seconds // 60, "minute", "minutes"),
            (diff.seconds, "second", "seconds"),
        )
        for period, singular, plural in periods:
            if period >= 1:
                return f"{period} {singular if period == 1 else plural} ago"
        return "just now"
    return dict(get_user_by_username=get_user_by_username, get_read_time=get_read_time, time_ago=time_ago)

# --- 4. ROUTES ---
@app.route('/')
def public_home():
    posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).all()
    user = db.session.get(User, session.get('user_id')) if 'user_id' in session else None
    return render_template('home_public.html', posts=posts, user=user)

@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()
    return render_template('view_post.html', post=post)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # VALIDATION: Check if empty
        if not username or not password:
            flash("Ayaw kalimti ang username ug password!")
            return redirect(url_for('register'))

        # VALIDATION: Check if username already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Naa na nay naggamit sa maong username. Pagpili og lain.")
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        is_first = User.query.count() == 0
        new_user = User(username=username, password=hashed_pw, is_admin=is_first)
        
        db.session.add(new_user)
        db.session.commit()
        flash("Rehistrado na ka! Pwede na ka mo-login.")
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session.clear()
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        flash("Sayop ang imong username o password.")
    return render_template('login.html')

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
    if post.author != user.username and not user.is_admin: return "Unauthorized", 403
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

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('public_home'))

@app.route('/user/<username>')
def user_profile(username):
    # Kuhaon ang user data
    view_user = User.query.filter_by(username=username).first_or_404()
    
    # Kuhaon ang iyang mga approved posts lang para sa public view
    user_posts = Post.query.filter_by(author=username, approved=True).order_by(Post.created_at.desc()).all()
    
    # Check kung kinsa ang naka-login para sa navbar
    logged_in_user = db.session.get(User, session.get('user_id')) if 'user_id' in session else None
    
    return render_template('profile.html', view_user=view_user, posts=user_posts, user=logged_in_user)

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
