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

# --- DATABASE CONFIG (MAO NI ANG IMPORTANTE) ---
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # SQLALCHEMY 2.0 FIX: Kinahanglan 'postgresql://' dili 'postgres://'
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "connect_args": {"sslmode": "require"},
        "pool_pre_ping": True,
    }
    # Makita ni nimo sa Render Dashboard > Logs
    print("🚀 INFO: NAGGAMIT KITA OG POSTGRESQL (SAFE ANG DATA!)")
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
    print("⚠️ WARNING: NAGGAMIT KITA OG SQLITE (MAPAPAS ANG DATA!)")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# --- MODELS ---
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

def create_notification(recipient_id, sender_id, post_id, type):
    if recipient_id != sender_id:
        notif = Notification(recipient_id=recipient_id, sender_id=sender_id, post_id=post_id, type=type)
        db.session.add(notif)
        db.session.commit()

# --- ROUTES ---
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
            
            # Simple slug generator
            slug = re.sub(r'[^a-zA-Z0-9 ]', '', title).replace(" ", "-").lower() + "-" + str(int(datetime.utcnow().timestamp()))
            
            media_url, media_type = None, None

            # I-check kung naay gi-upload nga file
            if 'media_file' in request.files:
                file = request.files['media_file']
                if file and file.filename != '':
                    # I-upload sa Cloudinary
                    # Siguradoha nga husto ang CLOUDINARY_URL sa Render
                    upload_result = cloudinary.uploader.upload(file, resource_type="auto")
                    media_url = upload_result.get('secure_url')
                    media_type = 'video' if 'video' in upload_result.get('resource_type', '') else 'image'
                    print(f"DEBUG: Cloudinary Upload Success: {media_url}")

            new_post = Post(
                title=title, 
                content=content, 
                slug=slug, 
                author=user.username,
                approved=user.is_admin, 
                media_file=media_url, 
                media_type=media_type
            )
            
            db.session.add(new_post)
            db.session.commit()
            flash("Post created successfully!")
            return redirect(url_for('dashboard'))

        except Exception as e:
            db.session.rollback() # I-undo ang database changes kung naay error
            print(f"❌ ERROR ON /CREATE: {str(e)}")
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

@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    data = request.get_json()
    if not data or not data.get('content'):
        return jsonify({"error": "Empty comment"}), 400
    post = Post.query.get_or_404(post_id)
    new_comment = Comment(post_id=post_id, user_id=session['user_id'], content=data.get('content'))
    db.session.add(new_comment)
    db.session.commit()
    
    post_owner = User.query.filter_by(username=post.author).first()
    if post_owner:
        create_notification(post_owner.id, session['user_id'], post.id, 'comment')

    return jsonify({"username": new_comment.user.username, "profile_pic": new_comment.user.profile_pic, "content": new_comment.content})

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

@app.route('/react/<int:post_id>/<string:reac_type>', methods=['POST'])
@login_required
def react(post_id, reac_type):
    user_id = session['user_id']
    post = Post.query.get_or_404(post_id)
    existing = Reaction.query.filter_by(post_id=post_id, user_id=user_id).first()
    if existing:
        existing.type = reac_type
    else:
        db.session.add(Reaction(post_id=post_id, user_id=user_id, type=reac_type))
        post_owner = User.query.filter_by(username=post.author).first()
        if post_owner:
            create_notification(post_owner.id, user_id, post_id, 'fire')
    db.session.commit()
    return jsonify({"count": Reaction.query.filter_by(post_id=post_id).count()})

@app.route('/profile/<username>')
def view_profile(username):
    user_profile = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(author=username, approved=True).order_by(Post.created_at.desc()).all()
    return render_template('profile.html', target_user=user_profile, posts=posts)

@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()
    return render_template('view_post.html', post=post)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('public_home'))

@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    user = db.session.get(User, session['user_id'])
    if post.author != user.username and not user.is_admin:
        flash("Dili nimo pwede usbon kini nga post!")
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        post.title = request.form.get('title')
        post.content = request.form.get('content')
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename != '':
                res = cloudinary.uploader.upload(file, resource_type="auto")
                post.media_file = res.get('secure_url')
                post.media_type = 'video' if 'video' in res.get('resource_type', '') else 'image'
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('create_post.html', post=post)

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

@app.route('/search')
def search():
    query = request.args.get('q', '')
    users = User.query.filter(User.username.ilike(f'%{query}%')).all() if query else []
    return render_template('search_results.html', users=users, query=query)

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(recipient_id=session['user_id']).order_by(Notification.created_at.desc()).all()
    for n in notifs: n.is_read = True
    db.session.commit()
    return render_template('notifications.html', notifications=notifs)

@app.route('/chat')
@login_required
def chat():
    messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).all()
    return render_template('chat.html', messages=messages)

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    data = request.get_json()
    new_msg = ChatMessage(user_id=session['user_id'], message=data['message'])
    db.session.add(new_msg)
    db.session.commit()
    return jsonify({'username': User.query.get(session['user_id']).username, 'profile_pic': User.query.get(session['user_id']).profile_pic, 'message': new_msg.message})

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
