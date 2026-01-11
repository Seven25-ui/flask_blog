from flask import Flask, render_template, redirect, url_for, request, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime
from functools import wraps

# --- APP SETUP ---
app = Flask(__name__, instance_relative_config=True)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")

# --- Ensure instance folder exists ---
os.makedirs(app.instance_path, exist_ok=True)

# --- DATABASE CONFIG ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'blog.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- DATABASE MODELS ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    author = db.Column(db.String(80), nullable=False, default="Guest")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved = db.Column(db.Boolean, default=False)
    tags = db.Column(db.String(200), nullable=True)

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # ex: 'like', 'love', 'haha', etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    post = db.relationship('Post', backref=db.backref('reactions', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('reactions', lazy='dynamic'))

# --- CREATE DB IF NOT EXISTS ---
with app.app_context():
    db.create_all()

# --- HELPERS ---

def make_slug(title):
    slug = re.sub(r'[^a-zA-Z0-9 ]', '', title)
    return slug.replace(" ", "-").lower()

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login'))
        user = User.query.get(user_id)
        if not user or not user.is_admin:
            flash("You are not authorized!")
            return redirect(url_for('public_home'))
        return f(*args, **kwargs)
    return decorated

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please login first!")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ================= ROUTES =================

# --- Public home ---

@app.route('/')
@app.route('/public')
@app.route('/public/page/<int:page>')
def public_home(page=1):
    per_page = 5
    posts = Post.query.filter_by(approved=True)\
        .order_by(Post.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    # Kuha ang user gikan sa session
    user = None
    if session.get('user_id'):
        user = User.query.get(session['user_id'])
    return render_template('home_public.html', posts=posts, user=user)

# --- Register ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash("Username already exists!")
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password)
        # First registered user becomes admin
        is_admin = not User.query.first()
        db.session.add(User(username=username, password=hashed_pw, is_admin=is_admin))
        db.session.commit()
        flash("User registered! You can now login.")
        return redirect(url_for('login'))

    return render_template('register.html')

# --- Login ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id

            # Flash newly approved posts
            approved_posts = Post.query.filter_by(author=user.username, approved=True).all()
            for post in approved_posts:
                flash(f"Your post '{post.title}' is approved!")                                             
            # Redirect admin to dashboard, others to my_posts
            return redirect(url_for('dashboard') if user.is_admin else url_for('my_posts'))

        flash("Invalid credentials")
    return render_template('login.html')

# --- Logout ---
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# --- Create post ---
@app.route('/create', methods=['GET', 'POST'])
def create_post():
    user = User.query.get(session['user_id']) if session.get('user_id') else None
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        tags = request.form.get('tags', '')
        slug = make_slug(title)
        if Post.query.filter_by(slug=slug).first():
            flash("Post already exists!")
            return redirect(url_for('create_post'))                                                                 
        post = Post(
            title=title,
            content=content,
            tags=tags,
            slug=slug,
            author=user.username if user else "Guest",
            approved=True if user and user.is_admin else False
        )
        db.session.add(post)
        db.session.commit()
        flash("Post created!" + (" (Auto-approved)" if user and user.is_admin else " (Pending approval)"))
        return redirect(url_for('public_home'))

    return render_template('create_post.html')

# --- View post ---
@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug, approved=True).first_or_404()                                      
    return render_template('view_post.html', post=post)

# --- Search ---
@app.route('/search')
def search():
    q = request.args.get('q', '')
    posts = Post.query.filter(
        Post.approved == True,
        (Post.title.contains(q)) | (Post.content.contains(q))
    ).all() if q else []
    return render_template('search_results.html', posts=posts, query=q)

# --- My Posts (all users) ---
@app.route('/my_posts')
def my_posts():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    posts = Post.query.filter_by(author=user.username).order_by(Post.created_at.desc()).all()
    return render_template('my_posts.html', posts=posts)

# ================== MODERATION ==================
# --- Pending posts (admin only) ---
@app.route('/pending')
@admin_required
def pending_posts():
    posts = Post.query.filter_by(approved=False).order_by(Post.created_at.desc()).all()
    return render_template('pending_posts.html', posts=posts)

# --- Approve post (admin only) ---
@app.route('/approve/<int:post_id>')
@admin_required
def approve_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.approved = True
    db.session.commit()
    flash(f"Post '{post.title}' approved!")
    return redirect(url_for('pending_posts'))

# --- Reject / delete post (admin only) ---
@app.route('/reject/<int:post_id>')
@admin_required
def reject_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash(f"Post '{post.title}' rejected/deleted!")
    return redirect(url_for('pending_posts'))

# --- Edit post ---
@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    user = User.query.get(session['user_id'])

    if post.author != user.username and not user.is_admin:
        flash("You cannot edit this post!")
        return redirect(url_for('my_dashboard'))

    if request.method == 'POST':
        post.title = request.form['title']
        post.content = request.form['content']
        post.tags = request.form.get('tags', post.tags)
        post.slug = make_slug(post.title)
        db.session.commit()
        flash("Post updated!")
        return redirect(url_for('my_dashboard' if not user.is_admin else 'dashboard'))

    return render_template('edit_post.html', post=post)

# --- Dashboard (admin + normal user) ---
@app.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if user.is_admin:
        # Admin sees all posts
        posts = Post.query.order_by(Post.created_at.desc()).all()
    else:
        # Normal user sees only their own posts
        posts = Post.query.filter_by(author=user.username).order_by(Post.created_at.desc()).all()

    return render_template('my_dashboard.html', posts=posts, user=user)

# --- UNLIMITED Reactions ---
@app.route('/react/<int:post_id>', methods=['POST'])
def react(post_id):
    if not session.get('user_id'):
        return {"status": "error", "message": "Login first!"}, 401

    reaction_type = request.form.get('type')
    user_id = session['user_id']

    # Unlimited reaction: always add new record per click
    new_reaction = Reaction(post_id=post_id, user_id=user_id, type=reaction_type)
    db.session.add(new_reaction)
    db.session.commit()

    return {"status": "ok"}

# --- RUN ---
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
