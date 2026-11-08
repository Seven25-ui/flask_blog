from flask import (Flask, render_template, redirect, url_for, request, session,
                   flash, jsonify, send_from_directory)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_, func, text
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime, timedelta
from functools import wraps
import cloudinary
import cloudinary.uploader
from flask_socketio import SocketIO, join_room

# Para lang sa local nga pagtrabaho (.env file). Sa Render, Environment Variables ang gamit.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# --------------------------------------------------------------------------
# 0. CONFIG (tanang secrets gikan na sa environment variables)
# --------------------------------------------------------------------------
def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


app = Flask(__name__)
app.secret_key = require_env("SECRET_KEY")
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024          # 100 MB max upload
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'                 # panalipod sa CSRF
app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get("RENDER"))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# SocketIO (threading mode: mo-work sa Python 3.13, wala nay eventlet).
# Pwede nimo i-limit ang origin: ALLOWED_ORIGINS=https://flask-blog-v2.onrender.com
socketio = SocketIO(app,
                    cors_allowed_origins=os.environ.get("ALLOWED_ORIGINS", "*"),
                    async_mode='threading')


def ph_time():
    """Oras sa Pilipinas (UTC+8)."""
    return datetime.utcnow() + timedelta(hours=8)


cloudinary.config(
    cloud_name=require_env("CLOUDINARY_CLOUD_NAME"),
    api_key=require_env("CLOUDINARY_API_KEY"),
    api_secret=require_env("CLOUDINARY_API_SECRET"),
    secure=True
)


def fix_uri(uri):
    return (uri.replace("postgres://", "postgresql+pg8000://", 1)
               .replace("postgresql://", "postgresql+pg8000://", 1))


app.config['SQLALCHEMY_DATABASE_URI'] = fix_uri(require_env("DATABASE_URL"))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True, "pool_recycle": 280}
db = SQLAlchemy(app)


# --------------------------------------------------------------------------
# 1. MODELS
# --------------------------------------------------------------------------
class User(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    profile_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/v1/avatar.png')
    background_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/v1/sample.jpg')
    created_at = db.Column(db.DateTime, default=ph_time)
    last_seen = db.Column(db.DateTime, default=ph_time)

    # --- Dating fields ---
    birthdate = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20), nullable=True)                 # male / female / other
    looking_for = db.Column(db.String(20), default='everyone')       # male / female / other / everyone
    location_text = db.Column(db.String(100), nullable=True)         # city lang, dili exact address
    interests = db.Column(db.String(200), nullable=True)


class Post(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    hashtags = db.Column(db.String(200), nullable=True)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    author = db.Column(db.String(80), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=ph_time)
    approved = db.Column(db.Boolean, default=True)
    media_file = db.Column(db.String(500), nullable=True)
    media_type = db.Column(db.String(10), nullable=True)

    # Inig delete sa Post, ma-delete sab ang likes, comments, notifications
    likes = db.relationship('Like', backref='post', cascade="all, delete-orphan", lazy=True)
    comments = db.relationship('Comment', backref='post', cascade="all, delete-orphan", lazy=True)
    notifications = db.relationship('Notification', backref='post', cascade="all, delete-orphan", lazy=True)


class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), default='like')


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)
    user = db.relationship('User', backref='user_comments')


class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)
    is_read = db.Column(db.Boolean, default=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True)

    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')
    parent_message = db.relationship('Message', remote_side=[id], backref='replies')
    reaction = db.Column(db.String(20), nullable=True)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)    # makadawat
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # nag-trigger
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    notif_type = db.Column(db.String(20))
    message = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=ph_time)
    sender = db.relationship('User', foreign_keys=[sender_id])


# --- Dating tables ---
class Swipe(db.Model):
    __table_args__ = (db.UniqueConstraint('swiper_id', 'target_id'),)
    id = db.Column(db.Integer, primary_key=True)
    swiper_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    liked = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)


class Match(db.Model):
    __table_args__ = (db.UniqueConstraint('user_a_id', 'user_b_id'),)
    id = db.Column(db.Integer, primary_key=True)
    user_a_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # mas gamay nga id
    user_b_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)


class Block(db.Model):
    __table_args__ = (db.UniqueConstraint('blocker_id', 'blocked_id'),)
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reported_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)


# --------------------------------------------------------------------------
# 1b. DATABASE SETUP (luwas sa existing database)
#     - create_all(): mo-create ra sa bag-ong tables (Swipe, Match, Block, Report)
#     - ensure_dating_schema(): mo-dugang sa bag-ong columns sa existing "user" table
#       gamit ang "ADD COLUMN IF NOT EXISTS" -> walay ma-delete, pwede i-run balik-balik
# --------------------------------------------------------------------------
def ensure_dating_schema():
    new_columns = {
        "birthdate": "DATE",
        "gender": "VARCHAR(20)",
        "looking_for": "VARCHAR(20) DEFAULT 'everyone'",
        "location_text": "VARCHAR(100)",
        "interests": "VARCHAR(200)",
    }
    try:
        with db.engine.begin() as conn:
            for name, ddl in new_columns.items():
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS {name} {ddl}'))
    except Exception as e:
        print(f"Schema update error: {e}")


with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"create_all error: {e}")
    ensure_dating_schema()


# --------------------------------------------------------------------------
# 2. HELPERS
# --------------------------------------------------------------------------
USERNAME_RE = re.compile(r'[A-Za-z0-9_]{3,20}')


def current_user():
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def master_admin_required(f):
    """Para sa 'admin' nga username ra."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user()
        if not user or user.username != 'admin':
            return "Forbidden", 403
        return f(*args, **kwargs)
    return decorated


def get_follower_count(user_id):
    return Follow.query.filter_by(followed_id=user_id).count()


def is_following(follower_id, followed_id):
    if not follower_id:
        return False
    return Follow.query.filter_by(follower_id=follower_id, followed_id=followed_id).first() is not None


# --- Dating helpers ---
def calc_age(birthdate):
    if not birthdate:
        return None
    today = ph_time().date()
    return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))


def are_matched(a, b):
    lo, hi = sorted((a, b))
    return Match.query.filter_by(user_a_id=lo, user_b_id=hi).first() is not None


def is_blocked(a, b):
    """True kung si a nag-block kang b o si b nag-block kang a."""
    return Block.query.filter(
        or_(and_(Block.blocker_id == a, Block.blocked_id == b),
            and_(Block.blocker_id == b, Block.blocked_id == a))
    ).first() is not None


def match_partners(user_id):
    """Tanang matched nga users (wala na-block), pinaka-bag-o una."""
    rows = (Match.query.filter(or_(Match.user_a_id == user_id, Match.user_b_id == user_id))
            .order_by(Match.created_at.desc()).all())
    people = []
    for m in rows:
        other_id = m.user_b_id if m.user_a_id == user_id else m.user_a_id
        other = db.session.get(User, other_id)
        if other and not is_blocked(user_id, other_id):
            people.append(other)
    return people


app.jinja_env.globals.update(is_following=is_following, get_follower_count=get_follower_count,
                             calc_age=calc_age)


def post_owner_id(post):
    """Karaan nga posts mahimong walay author_id; pangitaon gamit ang username."""
    if post.author_id:
        return post.author_id
    owner = User.query.filter_by(username=post.author).first()
    return owner.id if owner else None


def notify(owner_id, sender, post, notif_type, text_msg, toast):
    """I-save ang notification ug i-emit ang real-time signal (kung dili iya kaugalingon)."""
    if not owner_id or owner_id == sender.id:
        return
    db.session.add(Notification(user_id=owner_id, sender_id=sender.id, post_id=post.id,
                                notif_type=notif_type, message=text_msg))
    socketio.emit('notify', {'message': toast, 'type': notif_type}, room=f"user_{owner_id}")


def upload_media(file, allow_video=True):
    """Mo-upload sa Cloudinary. Mobalik ug (url, media_type). Image/video ra ang gitugotan."""
    mime = (file.mimetype or '').lower()
    allowed = ('image/', 'video/') if allow_video else ('image/',)
    if not mime.startswith(allowed):
        raise ValueError("Image o video ra ang gitugotan." if allow_video else "Image ra ang gitugotan.")
    res = cloudinary.uploader.upload(file, resource_type="auto")
    media_type = 'video' if res.get('resource_type') == 'video' else 'image'
    return res.get('secure_url'), media_type


@app.before_request
def update_last_seen():
    # I-skip ang static files ug socket.io; i-update ra kada 2 minutos (dili kada click)
    if request.endpoint in (None, 'static') or request.path.startswith('/socket.io'):
        return
    uid = session.get('user_id')
    if not uid:
        return
    user = db.session.get(User, uid)
    if user is None:
        session.clear()
        return
    now = ph_time()
    if not user.last_seen or (now - user.last_seen).total_seconds() > 120:
        user.last_seen = now
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


@app.context_processor
def utility_processor():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()

    def get_read_time(content):
        return max(1, round(len((content or '').split()) / 200))

    def time_ago(date):
        if not date:
            return ""
        diff = ph_time() - date
        if diff.total_seconds() < 60:
            return "just now"
        periods = (
            (diff.days // 365, "year", "years"),
            (diff.days // 30, "month", "months"),
            (diff.days // 7, "week", "weeks"),
            (diff.days, "day", "days"),
            (diff.seconds // 3600, "hour", "hours"),
            (diff.seconds // 60, "minute", "minutes"),
        )
        for period, singular, plural in periods:
            if period >= 1:
                return f"{period} {singular if period == 1 else plural} ago"
        return "just now"

    def get_user_status(user_id):
        user = db.session.get(User, user_id)
        if not user:
            return "Offline"
        if user.last_seen and (ph_time() - user.last_seen).total_seconds() < 300:
            return "Online"
        return f"Active {time_ago(user.last_seen)}" if user.last_seen else "Offline"

    def user_has_liked(user_id, post_id):
        if not user_id:
            return False
        return Like.query.filter_by(user_id=user_id, post_id=post_id).first() is not None

    def get_like_count(post_id):
        return Like.query.filter_by(post_id=post_id).count()

    def get_comment_count(post_id):
        return Comment.query.filter_by(post_id=post_id).count()

    def get_comments_for_post(post_id):
        return Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.desc()).all()

    uid = session.get('user_id')
    unread = Message.query.filter_by(receiver_id=uid, is_read=False).count() if uid else 0

    return dict(
        get_user_by_username=get_user_by_username,
        get_read_time=get_read_time,
        time_ago=time_ago,
        get_user_status=get_user_status,
        user_has_liked=user_has_liked,
        get_like_count=get_like_count,
        get_comment_count=get_comment_count,
        get_comments_for_post=get_comments_for_post,
        get_follower_count=get_follower_count,
        is_following=is_following,
        unread_count=unread,
        now_utc=ph_time()
    )


@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        join_room(f"user_{session['user_id']}")


# --------------------------------------------------------------------------
# 3. ROUTES: PUBLIC / AUTH
# --------------------------------------------------------------------------
@app.route('/')
def public_home():
    tab = request.args.get('tab', 'discover')
    user = current_user()

    query = Post.query.filter_by(approved=True)
    if tab == 'video':
        query = query.filter_by(media_type='video')
    elif tab == 'following' and user:
        followed_ids = [f.followed_id for f in Follow.query.filter_by(follower_id=user.id).all()]
        query = query.filter(Post.author_id.in_(followed_ids))
    posts = query.order_by(Post.created_at.desc()).limit(50).all()   # limit para dili mabug-at

    time_threshold = ph_time() - timedelta(hours=24)
    has_new_post = Post.query.filter(Post.approved == True, Post.created_at >= time_threshold).first() is not None

    return render_template('home_public.html', posts=posts, user=user,
                           active_tab=tab, has_new_post=has_new_post)


@app.route('/reels')
def reels():
    user = current_user()
    posts = (Post.query.filter_by(approved=True, media_type='video')
             .order_by(Post.created_at.desc()).limit(30).all())
    return render_template('reels.html', posts=posts, user=user)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash("Ayaw kalimti ang username ug password!")
            return redirect(url_for('register'))
        if not USERNAME_RE.fullmatch(username):
            flash("Username: letters, numbers, underscore ra, 3-20 ka characters.")
            return redirect(url_for('register'))
        if len(password) < 6:
            flash("Ang password kinahanglan labing menos 6 ka characters.")
            return redirect(url_for('register'))
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            flash("Naa na nay naggamit sa maong username. Pagpili og lain.")
            return redirect(url_for('register'))

        # --- Dating fields ---
        try:
            birthdate = datetime.strptime(request.form.get('birthdate', ''), '%Y-%m-%d').date()
        except ValueError:
            flash("Ibutang ang saktong birthdate.")
            return redirect(url_for('register'))
        age = calc_age(birthdate)
        if age < 18:
            flash("18 anyos pataas ra ang pwede.")
            return redirect(url_for('register'))
        if age > 100:
            flash("Ibutang ang saktong birthdate.")
            return redirect(url_for('register'))

        gender = request.form.get('gender')
        if gender not in ('male', 'female', 'other'):
            flash("Pilia ang imong gender.")
            return redirect(url_for('register'))
        looking_for = request.form.get('looking_for', 'everyone')
        if looking_for not in ('male', 'female', 'other', 'everyone'):
            looking_for = 'everyone'

        is_first = User.query.count() == 0
        db.session.add(User(username=username, password=generate_password_hash(password),
                            is_admin=is_first, birthdate=birthdate,
                            gender=gender, looking_for=looking_for))
        db.session.commit()
        flash("Rehistrado na ka! Pwede na ka mo-login.")
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username', '')).first()
        if user and check_password_hash(user.password, request.form.get('password', '')):
            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            return redirect(url_for('dashboard'))
        flash("Sayop ang imong username o password.")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('public_home'))


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = current_user()
    if request.method == 'POST':
        old_pw = request.form.get('old_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')
        if not check_password_hash(user.password, old_pw):
            flash("Sayop imong karaan nga password!", "error")
        elif new_pw != confirm_pw:
            flash("Dili parehas ang new password ug confirm password!", "error")
        elif len(new_pw) < 6:
            flash("Ang password kinahanglan labing menos 6 ka characters.", "error")
        else:
            user.password = generate_password_hash(new_pw)
            db.session.commit()
            flash("Success! Na-ilis na imong password.", "success")
            return redirect(url_for('profile_settings'))
    return render_template('change_password.html', user=user)


# --------------------------------------------------------------------------
# 4. ROUTES: DASHBOARD / POSTS
# --------------------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    if user is None:
        session.clear()
        return redirect(url_for('login'))

    if user.username == 'admin':
        return render_template('admin.html',
                               users=User.query.all(),
                               messages=Message.query.order_by(Message.created_at.desc()).all(),
                               user=user)

    posts = Post.query.filter_by(author_id=user.id).order_by(Post.created_at.desc()).all()
    notif_count = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    msg_count = Message.query.filter_by(receiver_id=user.id, is_read=False).count()
    return render_template('my_dashboard.html', posts=posts, user=user,
                           unread_notifs=notif_count, unread_msgs=msg_count)


@app.route('/notifications')
@login_required
def notifications():
    user_id = session['user_id']
    all_notifs = (Notification.query.filter_by(user_id=user_id)
                  .order_by(Notification.created_at.desc()).limit(100).all())
    # I-render una (gamit ang is_read karon), unya i-mark as read
    html = render_template('notifications.html', notifications=all_notifs)
    for n in all_notifs:
        n.is_read = True
    db.session.commit()
    return html


@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    user = current_user()
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        content = (request.form.get('content') or '').strip()
        hashtags = request.form.get('hashtags')
        if not title or not content:
            flash("Kinahanglan naay title ug content.")
            return render_template('create_post.html')

        slug_base = re.sub(r'[^a-zA-Z0-9 ]', '', title).strip().replace(" ", "-").lower() or "post"
        slug = f"{slug_base[:150]}-{int(ph_time().timestamp())}"

        media_url, media_type = None, None
        file = request.files.get('media_file')
        if file and file.filename:
            try:
                media_url, media_type = upload_media(file)
            except Exception as e:
                flash(f"Upload error: {e}")
                return render_template('create_post.html')

        db.session.add(Post(title=title, content=content, hashtags=hashtags, slug=slug,
                            author=user.username, author_id=user.id, approved=True,
                            media_file=media_url, media_type=media_type))
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('create_post.html')


@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    user = current_user()
    if post.author != user.username and not user.is_admin:
        return "Unauthorized", 403

    if request.method == 'POST':
        post.title = (request.form.get('title') or post.title).strip()
        post.content = request.form.get('content') or post.content
        file = request.files.get('media_file')
        if file and file.filename:
            try:
                post.media_file, post.media_type = upload_media(file)
            except Exception as e:
                flash(f"Error uploading media: {e}", "danger")
                return render_template('edit_post.html', post=post)
        db.session.commit()
        flash("Post updated successfully!", "success")
        return redirect(url_for('dashboard'))
    return render_template('edit_post.html', post=post)


@app.route('/approve/<int:post_id>', methods=['POST'])
@login_required
def approve_post(post_id):
    user = current_user()
    if user.is_admin:
        post = Post.query.get_or_404(post_id)
        post.approved = True
        db.session.commit()
    return redirect(url_for('dashboard'))


@app.route('/reject/<int:post_id>', methods=['POST'])
@login_required
def reject_post(post_id):
    user = current_user()
    if user.is_admin:
        post = Post.query.get_or_404(post_id)
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('dashboard'))


@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()
    user = current_user()
    if not post.approved and not (user and (user.is_admin or user.id == post.author_id)):
        return "Not found", 404
    return render_template('view_post.html', post=post)


@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    user = current_user()
    post = db.session.get(Post, post_id)
    if not post:
        return redirect(url_for('dashboard'))
    if post.author_id == user.id or post.author == user.username or user.is_admin:
        try:
            db.session.delete(post)   # cascade: likes, comments, notifications
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Delete Error: {e}")
            return "Error deleting post.", 500
        return redirect(url_for('dashboard'))
    return "Bawal! Dili ni nimo post ug dili ka Admin.", 403


# --------------------------------------------------------------------------
# 5. ROUTES: PROFILE / SOCIAL
# --------------------------------------------------------------------------
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = current_user()
    if request.method == 'POST':
        # Birthdate: ma-set ra KUNG WALA PA (para sa karaan nga accounts). Dili na ma-usab human ma-set.
        if not user.birthdate:
            bd_raw = (request.form.get('birthdate') or '').strip()
            if bd_raw:
                try:
                    bd = datetime.strptime(bd_raw, '%Y-%m-%d').date()
                except ValueError:
                    flash("Ibutang ang saktong birthdate.")
                    return redirect(url_for('profile_settings'))
                age = calc_age(bd)
                if age < 18:
                    flash("18 anyos pataas ra ang pwede.")
                    return redirect(url_for('profile_settings'))
                if age > 100:
                    flash("Ibutang ang saktong birthdate.")
                    return redirect(url_for('profile_settings'))
                user.birthdate = bd

        try:
            user.bio = (request.form.get('bio') or '')[:500]
            user.location_text = (request.form.get('location_text') or '').strip()[:100] or None
            user.interests = (request.form.get('interests') or '').strip()[:200] or None

            gender = request.form.get('gender')
            if gender in ('male', 'female', 'other'):
                user.gender = gender
            looking_for = request.form.get('looking_for')
            if looking_for in ('male', 'female', 'other', 'everyone'):
                user.looking_for = looking_for

            for field, attr in (('profile_pic', 'profile_pic'), ('background_pic', 'background_pic')):
                f = request.files.get(field)
                if f and f.filename:
                    url, _ = upload_media(f, allow_video=False)
                    setattr(user, attr, url)
            db.session.commit()
            return redirect(url_for('user_profile', username=user.username))
        except Exception as e:
            db.session.rollback()
            flash(f"Naay error sa pag-save: {e}")
    return render_template('profile_settings.html', user=user)


@app.route('/user/<username>')
def user_profile(username):
    target_user = User.query.filter_by(username=username).first_or_404()
    me_id = session.get('user_id')
    if me_id and me_id != target_user.id and is_blocked(me_id, target_user.id):
        return "Not found", 404
    user_posts = (Post.query.filter_by(author=username, approved=True)
                  .order_by(Post.created_at.desc()).all())
    return render_template('profile.html', target_user=target_user, posts=user_posts, user=current_user())


@app.route('/like/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401
    user = current_user()
    if user is None:
        return {"error": "Unauthorized"}, 401
    post = Post.query.get_or_404(post_id)

    existing = Like.query.filter_by(user_id=user.id, post_id=post_id).first()
    try:
        if existing:
            db.session.delete(existing)
            liked = False
        else:
            db.session.add(Like(user_id=user.id, post_id=post_id))
            notify(post_owner_id(post), user, post, 'like',
                   f"liked your post: {post.title[:30]}...",
                   f'❤️ {user.username} liked your post!')
            liked = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Like error: {e}")
        return {"error": "Failed"}, 500
    return {"liked": liked, "count": Like.query.filter_by(post_id=post_id).count()}


@app.route('/comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401
    user = current_user()
    if user is None:
        return {"error": "Unauthorized"}, 401
    post = Post.query.get_or_404(post_id)

    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()[:500]
    if not content:
        return {"error": "Empty comment"}, 400

    new_comment = Comment(post_id=post_id, user_id=user.id, content=content)
    db.session.add(new_comment)
    preview = (content[:30] + '...') if len(content) > 30 else content
    notify(post_owner_id(post), user, post, 'comment',
           f'commented on your post: "{preview}"',
           f'💬 {user.username} commented on your post!')
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Database Error: {e}")
        return {"error": "Failed to save comment"}, 500

    return {
        "success": True,
        "id": new_comment.id,
        "username": user.username,
        "profile_pic": user.profile_pic or f"https://ui-avatars.com/api/?name={user.username}",
        "content": content,
        "created_at": new_comment.created_at.strftime('%b %d, %I:%M %p')
    }


@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Please login first"}), 401
    user = current_user()
    comment = db.session.get(Comment, comment_id)
    if not comment:
        return jsonify({"success": False, "error": "Comment not found"}), 404
    if comment.user_id == user.id or user.is_admin:
        try:
            db.session.delete(comment)
            db.session.commit()
            return jsonify({"success": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": False, "error": "Bawal! Dili ni nimo comment."}), 403


@app.route('/follow/<int:user_id>', methods=['POST'])
def follow_user(user_id):
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    me = session['user_id']
    if me == user_id:
        return jsonify({'error': 'cannot follow yourself'}), 400
    if not db.session.get(User, user_id):
        return jsonify({'error': 'user not found'}), 404
    existing = Follow.query.filter_by(follower_id=me, followed_id=user_id).first()
    if existing:
        db.session.delete(existing)
        status = 'unfollowed'
    else:
        db.session.add(Follow(follower_id=me, followed_id=user_id))
        status = 'followed'
    db.session.commit()
    return jsonify({'status': status, 'count': get_follower_count(user_id)})


# --------------------------------------------------------------------------
# 5b. ROUTES: DATING (discover / swipe / matches / block / report)
# --------------------------------------------------------------------------
@app.route('/discover')
@login_required
def discover():
    me = current_user()

    # Karaan nga accounts: kumpletoha una ang dating profile
    if not me.birthdate or not me.gender:
        flash("Kumpletoha una imong dating profile (birthdate ug gender).")
        return redirect(url_for('profile_settings'))

    swiped = db.session.query(Swipe.target_id).filter(Swipe.swiper_id == me.id)
    blocked_by_me = db.session.query(Block.blocked_id).filter(Block.blocker_id == me.id)
    blocked_me = db.session.query(Block.blocker_id).filter(Block.blocked_id == me.id)

    q = User.query.filter(
        User.id != me.id,
        User.birthdate.isnot(None),
        User.username != 'admin',
        ~User.id.in_(swiped),
        ~User.id.in_(blocked_by_me),
        ~User.id.in_(blocked_me),
    )
    # Ang gusto nako
    if me.looking_for in ('male', 'female', 'other'):
        q = q.filter(User.gender == me.looking_for)
    # Ug ang gusto nila (mutual)
    q = q.filter(or_(User.looking_for == 'everyone',
                     User.looking_for == me.gender,
                     User.looking_for.is_(None)))

    candidate = q.order_by(func.random()).first()
    return render_template('discover.html', candidate=candidate, user=me)


@app.route('/swipe/<int:target_id>', methods=['POST'])
@login_required
def swipe(target_id):
    me = current_user()
    if target_id == me.id or not db.session.get(User, target_id):
        return {"error": "invalid"}, 400
    if is_blocked(me.id, target_id):
        return {"error": "blocked"}, 403

    data = request.get_json(silent=True) or {}
    liked = bool(data.get('liked'))

    if Swipe.query.filter_by(swiper_id=me.id, target_id=target_id).first():
        return {"matched": False}          # na-swipe na, ayaw i-doble

    matched = False
    try:
        db.session.add(Swipe(swiper_id=me.id, target_id=target_id, liked=liked))
        if liked:
            they_liked = Swipe.query.filter_by(swiper_id=target_id, target_id=me.id, liked=True).first()
            if they_liked and not are_matched(me.id, target_id):
                lo, hi = sorted((me.id, target_id))
                db.session.add(Match(user_a_id=lo, user_b_id=hi))
                matched = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Swipe error: {e}")
        return {"error": "failed"}, 500

    if matched:
        other = db.session.get(User, target_id)
        # I-notify ang duha ka side
        socketio.emit('notify', {'message': f"💘 It's a match with {me.username}!", 'type': 'match'},
                      room=f"user_{target_id}")
        socketio.emit('notify', {'message': f"💘 It's a match with {other.username}!", 'type': 'match'},
                      room=f"user_{me.id}")
        return {"matched": True, "username": other.username}
    return {"matched": False}


@app.route('/matches')
@login_required
def matches():
    me = current_user()
    return render_template('matches.html', people=match_partners(me.id), user=me)


@app.route('/block/<int:target_id>', methods=['POST'])
@login_required
def block_user(target_id):
    me_id = session['user_id']
    if target_id == me_id or not db.session.get(User, target_id):
        return {"error": "invalid"}, 400
    if not Block.query.filter_by(blocker_id=me_id, blocked_id=target_id).first():
        db.session.add(Block(blocker_id=me_id, blocked_id=target_id))
        db.session.commit()
    return {"status": "blocked"}


@app.route('/report/<int:target_id>', methods=['POST'])
@login_required
def report_user(target_id):
    reason = ((request.get_json(silent=True) or {}).get('reason') or '').strip()[:300]
    if not reason or not db.session.get(User, target_id):
        return {"error": "invalid"}, 400
    db.session.add(Report(reporter_id=session['user_id'], reported_id=target_id, reason=reason))
    db.session.commit()
    return {"status": "reported"}


# --------------------------------------------------------------------------
# 6. ROUTES: MESSAGES (matches ra ang pwede ma-chat)
# --------------------------------------------------------------------------
@app.route('/messages')
@app.route('/messages/<int:user_id>')
@login_required
def inbox(user_id=None):
    me_id = session['user_id']
    me = current_user()

    # Ang partners kay ang mga matches (bisan wala pa magsinultihanay)
    partners = match_partners(me_id)

    active_chat, selected_user = [], None
    if user_id:
        if not are_matched(me_id, user_id) or is_blocked(me_id, user_id):
            flash("Matches ra ang pwede ma-chat.")
            return redirect(url_for('matches'))

        selected_user = db.session.get(User, user_id)
        if selected_user:
            active_chat = Message.query.filter(
                ((Message.sender_id == me_id) & (Message.receiver_id == user_id)) |
                ((Message.sender_id == user_id) & (Message.receiver_id == me_id))
            ).order_by(Message.created_at.asc()).all()
            for m in Message.query.filter_by(sender_id=user_id, receiver_id=me_id, is_read=False).all():
                m.is_read = True
            db.session.commit()

    return render_template('messages.html', partners=partners, active_chat=active_chat,
                           selected_user=selected_user, user=me, active_tab='messages')


@app.route('/send_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_message(receiver_id):
    me = current_user()
    content = (request.form.get('content') or '').strip()[:2000]
    parent_id = request.form.get('parent_id')

    if not db.session.get(User, receiver_id):
        return redirect(url_for('matches'))
    # Matches ra, ug dili kung naay block
    if not are_matched(me.id, receiver_id) or is_blocked(me.id, receiver_id):
        return "Matches ra ang pwede ma-chat.", 403
    if not content:
        return redirect(request.referrer or url_for('inbox', user_id=receiver_id))

    p_id = int(parent_id) if parent_id and parent_id.isdigit() else None
    try:
        db.session.add(Message(sender_id=me.id, receiver_id=receiver_id,
                               content=content, parent_id=p_id))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
        return "Error sending message.", 500

    # Real-time toast sa nakadawat
    socketio.emit('notify', {'message': f'💬 {me.username}: {content[:40]}', 'type': 'message',
                             'sender_id': me.id},
                  room=f"user_{receiver_id}")
    return redirect(url_for('inbox', user_id=receiver_id))


@app.route('/react_message/<int:message_id>', methods=['POST'])
@login_required
def react_message(message_id):
    data = request.get_json(silent=True) or {}
    reaction = (data.get('reaction') or '')[:20] or None
    msg = Message.query.get_or_404(message_id)
    # Sender o receiver ra ang pwede mo-react
    if session['user_id'] not in (msg.sender_id, msg.receiver_id):
        return {"status": "forbidden"}, 403
    msg.reaction = reaction
    try:
        db.session.commit()
        return {"status": "success", "reaction": reaction}, 200
    except Exception:
        db.session.rollback()
        return {"status": "error"}, 500


@app.route('/delete_message/<int:message_id>', methods=['GET', 'POST'])
@login_required
def delete_message(message_id):
    message = Message.query.get_or_404(message_id)
    if message.sender_id == session['user_id']:
        db.session.delete(message)
        db.session.commit()
        return redirect(request.referrer or url_for('inbox'))
    return "Dili nimo mahimong papason kini.", 403


@app.route('/api/unread-count')
def unread_count():
    if 'user_id' not in session:
        return {"count": 0, "messages": 0, "total": 0}
    uid = session['user_id']
    notif_count = Notification.query.filter_by(user_id=uid, is_read=False).count()
    msg_count = Message.query.filter_by(receiver_id=uid, is_read=False).count()
    return {"count": notif_count, "messages": msg_count, "total": notif_count + msg_count}


# --------------------------------------------------------------------------
# 7. ROUTES: ADMIN (POST ra, 'admin' account ra)
# --------------------------------------------------------------------------
@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
@master_admin_required
def admin_delete_user(user_id):
    target = db.session.get(User, user_id)
    if not target:
        return "User not found", 404
    if target.username == 'admin':
        return "Dili ma-delete ang admin.", 400
    try:
        # Posts una (ORM delete para mo-cascade ang likes/comments/notifications)
        for post in Post.query.filter((Post.author_id == user_id) | (Post.author == target.username)).all():
            db.session.delete(post)
        db.session.flush()
        Like.query.filter_by(user_id=user_id).delete()
        Comment.query.filter_by(user_id=user_id).delete()
        Reaction.query.filter_by(user_id=user_id).delete()
        Follow.query.filter((Follow.follower_id == user_id) | (Follow.followed_id == user_id)).delete()
        # Dating tables
        Swipe.query.filter((Swipe.swiper_id == user_id) | (Swipe.target_id == user_id)).delete()
        Match.query.filter((Match.user_a_id == user_id) | (Match.user_b_id == user_id)).delete()
        Block.query.filter((Block.blocker_id == user_id) | (Block.blocked_id == user_id)).delete()
        Report.query.filter((Report.reporter_id == user_id) | (Report.reported_id == user_id)).delete()
        Notification.query.filter((Notification.user_id == user_id) | (Notification.sender_id == user_id)).delete()
        # Message replies: i-null ang parent_id sa mga naka-reply sa iyang messages
        own_ids = [m.id for m in Message.query.filter(
            (Message.sender_id == user_id) | (Message.receiver_id == user_id)).all()]
        if own_ids:
            Message.query.filter(Message.parent_id.in_(own_ids)).update({Message.parent_id: None}, synchronize_session=False)
        Message.query.filter((Message.sender_id == user_id) | (Message.receiver_id == user_id)).delete()
        db.session.delete(target)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DATABASE ERROR: {e}")
        return f"Error: {e}", 500
    return redirect(url_for('dashboard'))


@app.route('/admin/delete_message/<int:msg_id>', methods=['POST'])
@login_required
@master_admin_required
def admin_delete_message(msg_id):
    msg = db.session.get(Message, msg_id)
    if not msg:
        return "Message not found", 404
    try:
        Message.query.filter_by(parent_id=msg_id).update({Message.parent_id: None})
        db.session.delete(msg)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DATABASE ERROR: {e}")
        return f"Error: {e}", 500
    return redirect(url_for('dashboard'))


# --------------------------------------------------------------------------
# 8. PWA FILES
# --------------------------------------------------------------------------
@app.route('/sw.js')
def serve_sw():
    resp = send_from_directory('static', 'sw.js', mimetype='application/javascript')
    resp.headers['Cache-Control'] = 'no-cache'          # kanunay i-check kung naay bag-ong service worker
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp


@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')


# I-inject ang PWA tags sa TANANG HTML pages (wala na kinahanglan usbon ang matag template)
PWA_SNIPPET = (
    '<link rel="manifest" href="/manifest.json">'
    '<meta name="theme-color" content="#000000">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black">'
    '<link rel="apple-touch-icon" href="/static/icon-192.png">'
    '<script>if("serviceWorker" in navigator){window.addEventListener("load",function(){'
    'navigator.serviceWorker.register("/sw.js").catch(function(){});});}</script>'
)


@app.after_request
def inject_pwa_tags(resp):
    try:
        if (resp.status_code == 200 and resp.mimetype == 'text/html'
                and not resp.direct_passthrough):
            html = resp.get_data(as_text=True)
            if '</head>' in html and 'rel="manifest"' not in html:
                resp.set_data(html.replace('</head>', PWA_SNIPPET + '</head>', 1))
    except Exception as e:
        print(f"PWA inject error: {e}")
    return resp


if __name__ == '__main__':
    # Local lang ni. Sa Render, gunicorn ang mo-run:
    #   gunicorn --worker-class gthread --threads 100 -w 1 --bind 0.0.0.0:$PORT app:app
    socketio.run(app, debug=os.environ.get("DEBUG") == "1", host='0.0.0.0',
                 port=int(os.environ.get("PORT", 5000)), allow_unsafe_werkzeug=True)
