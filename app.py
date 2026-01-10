from flask import Flask, render_template, redirect, url_for, request, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime

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

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    author = db.Column(db.String(80), nullable=False, default="Guest")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved = db.Column(db.Boolean, default=False)  # new field for moderation
    tags = db.Column(db.String(200), nullable=True)  # new field for tags

# --- CREATE DB IF NOT EXISTS ---
with app.app_context():
    db.create_all()

# --- HELPER ---
def make_slug(title):
    slug = re.sub(r'[^a-zA-Z0-9 ]', '', title)
    return slug.replace(" ", "-").lower()

# --- ROUTES ---

# Public home with pagination
@app.route('/')
@app.route('/public')
@app.route('/public/page/<int:page>')
def public_home(page=1):
    per_page = 5
    posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('home_public.html', posts=posts)

# --- User registration/login/logout ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash("Username already exists!")
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        flash("Admin created! You can now login.")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash("Logged in successfully!")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username or password.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("Logged out successfully!")
    return redirect(url_for('login'))

# --- Admin dashboard ---
@app.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        flash("Please login first!")
        return redirect(url_for('login'))
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('dashboard.html', posts=posts)

# --- Create post (admin + public) ---
@app.route('/create', methods=['GET', 'POST'])
def create_post():
    user = None
    if session.get('user_id'):
        user = User.query.get(session['user_id'])

    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        tags = request.form.get('tags', '')
        slug = make_slug(title)
        author = user.username if user else request.form.get('author', 'Guest')

        if Post.query.filter_by(slug=slug).first():
            flash("Post with this title already exists!")
            return redirect(url_for('create_post'))

        new_post = Post(
            title=title,
            content=content,
            slug=slug,
            author=author,
            tags=tags,
            approved=bool(user),  # auto-approved if admin, else False
            created_at=datetime.utcnow()
        )
        db.session.add(new_post)
        db.session.commit()
        flash("Post submitted! Awaiting approval." if not user else "Post created successfully!")
        return redirect(url_for('public_home'))

    return render_template('create_post.html')

# --- Edit post (admin only) ---
@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    if not session.get('user_id'):
        flash("Please login first!")
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        flash("User not found. Please login again.")
        session.pop('user_id', None)
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)

    if request.method == 'POST':
        post.title = request.form['title']
        post.content = request.form['content']
        post.slug = make_slug(post.title)
        post.author = user.username
        post.tags = request.form.get('tags', post.tags)
        db.session.commit()
        flash("Post updated successfully!")
        return redirect(url_for('dashboard'))

    return render_template('edit_post.html', post=post)

# --- Delete post (admin only) ---
@app.route('/delete/<int:post_id>')
def delete_post(post_id):
    if not session.get('user_id'):
        flash("Please login first!")
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted successfully!")
    return redirect(url_for('dashboard'))

# --- View single post (approved only) ---
@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug, approved=True).first_or_404()
    return render_template('view_post.html', post=post)

# --- Search (approved only) ---
@app.route('/search')
def search():
    query = request.args.get('q', '')
    if query:
        posts = Post.query.filter(
            ((Post.title.contains(query)) | (Post.content.contains(query))) & (Post.approved==True)
        ).order_by(Post.created_at.desc()).all()
    else:
        posts = []

    return render_template('search_results.html', posts=posts, query=query)

# --- Pending posts for approval (admin only) ---
@app.route('/pending')
def pending_posts():
    if not session.get('user_id'):
        flash("Please login first!")
        return redirect(url_for('login'))

    # Admin sees all posts where approved=False
    posts = Post.query.filter_by(approved=False).order_by(Post.created_at.desc()).all()
    return render_template('pending_posts.html', posts=posts)

# --- Approve a post (admin only) ---
@app.route('/approve/<int:post_id>')
def approve_post(post_id):
    if not session.get('user_id'):
        flash("Please login first!")
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)
    post.approved = True
    db.session.commit()
    flash(f"Post '{post.title}' approved!")
    return redirect(url_for('pending_posts'))

# --- RUN APP ---
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
