from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime, timedelta  # Gidugang ang timedelta
from functools import wraps
import cloudinary
import cloudinary.uploader
from cloudinary.uploader import upload

app = Flask(__name__)
app.secret_key = "aloy_super_secret_key_733"

# --- HELPER PARA SA PILIPINAS TIME (UTC+8) ---
def ph_time():
    return datetime.utcnow() + timedelta(hours=8)

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
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    profile_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/v1/avatar.png')
    background_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/v1/sample.jpg')
    created_at = db.Column(db.DateTime, default=ph_time)
    last_seen = db.Column(db.DateTime, default=ph_time) # Gidugang para sa Online Status

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
    approved = db.Column(db.Boolean, default=False)
    media_file = db.Column(db.String(500), nullable=True)
    media_type = db.Column(db.String(10), nullable=True)

    # KINI ANG MU-FIX SA TANANG ERROR:
    # 1. Inig delete sa Post, ma-delete sab ang tanang LIKES niini
    likes = db.relationship('Like', backref='post', cascade="all, delete-orphan", lazy=True)
    
    # 2. Inig delete sa Post, ma-delete sab ang tanang COMMENTS niini
    comments = db.relationship('Comment', backref='post', cascade="all, delete-orphan", lazy=True)
    
    # 3. Kung naa kay Notifications nga nakakonekta sa Post, i-add sab ni:
    # notifications = db.relationship('Notification', backref='post', cascade="all, delete-orphan", lazy=True)

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
    created_at = db.Column(db.DateTime, default=ph_time) # Pabilin ang PH time
    is_read = db.Column(db.Boolean, default=False)
    
    # 1. DUGANG: Parent ID para sa Reply link
    parent_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True)
    
    # Existing relationships
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')
    
    # 2. DUGANG: Relationship para makuha ang content sa gi-replyan
    parent_message = db.relationship('Message', remote_side=[id], backref='replies')
    reaction = db.Column(db.String(20), nullable=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Kinsa ang makadawat
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Kinsa ang nag-trigger
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True) # Unsa nga post
    notif_type = db.Column(db.String(20)) # 'like', 'comment', 'admin'
    message = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=ph_time)

    # Relationships para dali ra i-display ang pangalan sa sender
    sender = db.relationship('User', foreign_keys=[sender_id])

# --- 3. HELPERS & UTILITIES ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# PARA MA-UPDATE ANG LAST SEEN KADA CLICK
@app.before_request
def update_last_seen():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user:
            user.last_seen = ph_time()
            db.session.commit()

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
        now = ph_time() 
        diff = now - date

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

    # --- KANI ANG BAG-O NGA GI-ADD PARA SA STATUS ---
    def get_user_status(user_id):
        user = db.session.get(User, user_id)
        if not user: return "Offline"
        
        # 5 minutes (300 seconds) limit para sa Online status
        if user.last_seen and (ph_time() - user.last_seen).total_seconds() < 300:
            return "Online"
        
        return f"Active {time_ago(user.last_seen)}" if user.last_seen else "Offline"
    # -----------------------------------------------

    def user_has_liked(user_id, post_id):
        if not user_id: return False
        return Like.query.filter_by(user_id=user_id, post_id=post_id).first() is not None

    def get_like_count(post_id):
        return Like.query.filter_by(post_id=post_id).count()

    def get_comment_count(post_id):
        return Comment.query.filter_by(post_id=post_id).count()

    def get_comments_for_post(post_id):
        return Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.desc()).all()

    def get_follower_count(user_id):
        return Follow.query.filter_by(followed_id=user_id).count()

    def is_following(follower_id, followed_id):
        if not follower_id: return False
        return Follow.query.filter_by(follower_id=follower_id, followed_id=followed_id).first() is not None

    return dict(
        get_user_by_username=get_user_by_username,
        get_read_time=get_read_time,
        time_ago=time_ago,
        get_user_status=get_user_status, # GI-APIL NA DIRI
        user_has_liked=user_has_liked,
        get_like_count=get_like_count,
        get_comment_count=get_comment_count,
        get_comments_for_post=get_comments_for_post,
        get_follower_count=get_follower_count,
        is_following=is_following,
        unread_count=Message.query.filter_by(receiver_id=session.get('user_id'), is_read=False).count() if 'user_id' in session else 0,
        now_utc=ph_time()
    )

# --- 4. ROUTES ---

@app.route('/')
def public_home():
    tab = request.args.get('tab', 'discover')
    user = db.session.get(User, session.get('user_id')) if 'user_id' in session else None

    # 1. Main Post Filtering Logic
    if tab == 'video':
        posts = Post.query.filter_by(approved=True, media_type='video').order_by(Post.created_at.desc()).all()
    elif tab == 'following' and user:
        followed_ids = [f.followed_id for f in Follow.query.filter_by(follower_id=user.id).all()]
        posts = Post.query.filter(Post.author_id.in_(followed_ids), Post.approved==True).order_by(Post.created_at.desc()).all()
    else:
        posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).all()

    # 2. Check for New Posts (Last 24 Hours) para sa Pop-up
    time_threshold = datetime.utcnow() - timedelta(hours=24)
    has_new_post = Post.query.filter(Post.approved==True, Post.created_at >= time_threshold).first() is not None

    return render_template('home_public.html', 
                           posts=posts, 
                           user=user, 
                           active_tab=tab, 
                           has_new_post=has_new_post)

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        old_pw = request.form.get('old_password')
        new_pw = request.form.get('new_password')
        confirm_pw = request.form.get('confirm_password')

        if not check_password_hash(user.password, old_pw):
            flash("Sayop imong karaan nga password!", "error")
        elif new_pw != confirm_pw:
            flash("Dili parehas ang new password ug confirm password!", "error")
        else:
            user.password = generate_password_hash(new_pw)
            db.session.commit()
            flash("Success! Na-ilis na imong password.", "success")
            return redirect(url_for('profile_settings'))
    return render_template('change_password.html', user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash("Ayaw kalimti ang username ug password!")
            return redirect(url_for('register'))
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
    
    # Imong existing logic sa posts
    posts = Post.query.all() if user.is_admin else Post.query.filter_by(author=user.username).all()
    
    # KINI ANG GI-DUGANG:
    # 0 lang sa atong sugod aron dili mo-error ang Bell icon sa HTML
    notification_count = 0 
    
    # Gi-pass na nato ang notification_count sa render_template
    return render_template('my_dashboard.html', 
                           posts=posts, 
                           user=user, 
                           notification_count=notification_count)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        hashtags = request.form.get('hashtags')
        slug = re.sub(r'[^a-zA-Z0-9 ]', '', title).replace(" ", "-").lower() + "-" + str(int(ph_time().timestamp()))
        media_url, media_type = None, None
        
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename != '':
                res = cloudinary.uploader.upload(file, resource_type="auto")
                media_url = res.get('secure_url')
                media_type = 'video' if 'video' in str(res.get('resource_type')) else 'image'
        
        new_post = Post(
            title=title,
            content=content,
            hashtags=hashtags,
            slug=slug,
            author=user.username,
            author_id=user.id,
            approved=user.is_admin,
            media_file=media_url,
            media_type=media_type
        )
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
        file = request.files.get('media_file')
        if file and file.filename != '':
            try:
                upload_result = upload(file)
                post.media_file = upload_result['secure_url']
                post.media_type = 'video' if 'video' in file.mimetype else 'image'
            except Exception as e:
                flash(f"Error uploading media: {str(e)}", "danger")
                return render_template('edit_post.html', post=post)

        db.session.commit()
        flash("Post updated successfully!", "success")
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

@app.route('/approve/<int:post_id>', methods=['POST'])
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
            p_file = request.files['profile_pic']
            if p_file and p_file.filename != '':
                p_res = cloudinary.uploader.upload(p_file)
                user.profile_pic = p_res.get('secure_url')
        if 'background_pic' in request.files:
            bg_file = request.files['background_pic']
            if bg_file and bg_file.filename != '':
                bg_res = cloudinary.uploader.upload(bg_file)
                user.background_pic = bg_res.get('secure_url')
        try:
            db.session.commit()
            return redirect(url_for('user_profile', username=user.username))
        except Exception as e:
            db.session.rollback()
            return f"Naay error sa pag-save: {str(e)}"
    return render_template('profile_settings.html', user=user)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('public_home'))

@app.route('/user/<username>')
def user_profile(username):
    target_user = User.query.filter_by(username=username).first_or_404()
    user_posts = Post.query.filter_by(author=username, approved=True).order_by(Post.created_at.desc()).all()
    logged_in_user = db.session.get(User, session.get('user_id')) if 'user_id' in session else None
    return render_template('profile.html', target_user=target_user, posts=user_posts, user=logged_in_user)

@app.route('/like/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session: return {"error": "Unauthorized"}, 401
    user_id = session['user_id']
    post = Post.query.get_or_404(post_id)

    existing_like = Like.query.filter_by(user_id=user_id, post_id=post_id).first()

    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        return {"liked": False, "count": Like.query.filter_by(post_id=post_id).count()}
    else:
        new_like = Like(user_id=user_id, post_id=post_id)
        db.session.add(new_like)

        # Notification Logic
        if post.author_id != user_id:
            new_notif = Notification(
                user_id=post.author_id,
                sender_id=user_id,
                post_id=post.id,
                notif_type='like',
                message=f"liked your post: {post.title[:30]}..."
            )
            db.session.add(new_notif)

        db.session.commit()
        return {"liked": True, "count": Like.query.filter_by(post_id=post_id).count()}

@app.route('/comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session: return {"error": "Unauthorized"}, 401
    
    user = db.session.get(User, session['user_id'])
    post = Post.query.get_or_404(post_id)
    
    data = request.get_json()
    content = data.get('content', '').strip()
    if not content: return {"error": "Empty comment"}, 400

    # 1. Save ang comment
    new_comment = Comment(post_id=post_id, user_id=user.id, content=content)
    db.session.add(new_comment)

    # 2. Notification Logic (Gi-fix nako ang spacing ani)
    if post.author_id != user.id:
        new_notif = Notification(
            user_id=post.author_id,
            sender_id=user.id,
            post_id=post.id,
            notif_type='comment',
            message=f"commented on your post: \"{content[:30]}...\""
        )
        db.session.add(new_notif)
    
    # 3. Commit tanan
    db.session.commit()

    formatted_time = new_comment.created_at.strftime('%b %d, %I:%M %p')
    return {
        "success": True,
        "username": user.username,
        "profile_pic": user.profile_pic if user.profile_pic else f"https://ui-avatars.com/api/?name={user.username}",
        "content": content,
        "created_at": formatted_time
    }

@app.route('/follow/<int:user_id>', methods=['POST'])
def follow_user(user_id):
    if 'user_id' not in session: return jsonify({'error': 'unauthorized'}), 401
    current_user_id = session['user_id']
    if current_user_id == user_id: return jsonify({'error': 'cannot follow yourself'}), 400
    existing_follow = Follow.query.filter_by(follower_id=current_user_id, followed_id=user_id).first()
    if existing_follow:
        db.session.delete(existing_follow)
        db.session.commit()
        return jsonify({'status': 'unfollowed', 'count': get_follower_count(user_id)})
    else:
        new_follow = Follow(follower_id=current_user_id, followed_id=user_id)
        db.session.add(new_follow)
        db.session.commit()
        return jsonify({'status': 'followed', 'count': get_follower_count(user_id)})

def get_follower_count(user_id):
    return Follow.query.filter_by(followed_id=user_id).count()

def is_following(follower_id, followed_id):
    return Follow.query.filter_by(follower_id=follower_id, followed_id=followed_id).first() is not None

app.jinja_env.globals.update(is_following=is_following, get_follower_count=get_follower_count)

@app.route('/post/<slug>')
def view_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()
    return render_template('view_post.html', post=post)

@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    if 'user_id' not in session: return {"error": "Unauthorized"}, 401
    comment = db.session.get(Comment, comment_id)
    if not comment: return {"error": "Comment not found"}, 404
    if comment.user_id != session['user_id']: return {"error": "Permission denied"}, 403
    db.session.delete(comment)
    db.session.commit()
    return {"success": True}

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/messages')
@app.route('/messages/<int:user_id>')
@login_required
def inbox(user_id=None):
    current_user_id = session['user_id']
    current_user = db.session.get(User, current_user_id)

    # Chat history logic
    messages_query = Message.query.filter(
        (Message.sender_id == current_user_id) | (Message.receiver_id == current_user_id)
    ).order_by(Message.created_at.desc()).all()

    chat_partners_ids = []
    partners = []
    for msg in messages_query:
        partner_id = msg.receiver_id if msg.sender_id == current_user_id else msg.sender_id
        if partner_id not in chat_partners_ids:
            partner = db.session.get(User, partner_id)
            if partner:
                partners.append(partner)
                chat_partners_ids.append(partner_id)

    active_chat = []
    selected_user = None
    if user_id:
        selected_user = db.session.get(User, user_id)
        if selected_user:
            active_chat = Message.query.filter(
                ((Message.sender_id == current_user_id) & (Message.receiver_id == user_id)) | 
                ((Message.sender_id == user_id) & (Message.receiver_id == current_user_id))
            ).order_by(Message.created_at.asc()).all()
            
            unread = Message.query.filter_by(sender_id=user_id, receiver_id=current_user_id, is_read=False).all()
            for m in unread: m.is_read = True
            db.session.commit()

    return render_template('messages.html', partners=partners, active_chat=active_chat, selected_user=selected_user, user=current_user, active_tab='messages')

@app.route('/send_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_message(receiver_id):
    content = request.form.get('content')
    parent_id = request.form.get('parent_id') # Gikan sa hidden input sa message.html
    
    # Check kung empty ba ang content
    if not content or not content.strip():
        return redirect(request.referrer or url_for('inbox', user_id=receiver_id))
    
    # I-process ang parent_id (kung naay gi-replyan o wala)
    p_id = None
    if parent_id and parent_id.isdigit():
        p_id = int(parent_id)

    # I-create ang bag-ong message nga naay parent_id
    new_msg = Message(
        sender_id=session['user_id'], 
        receiver_id=receiver_id, 
        content=content.strip(),
        parent_id=p_id
    )
    
    try:
        db.session.add(new_msg)
        db.session.commit()
        return redirect(url_for('inbox', user_id=receiver_id))
    except Exception as e:
        db.session.rollback()
        # Print sa terminal para makita nimo ang error kung naa man gani
        print(f"Error: {e}")
        return "Error sending message.", 500

@app.route('/delete_message/<int:message_id>')
@login_required
def delete_message(message_id):
    # Pangitaon ang message sa database gamit ang ID
    msg = Message.query.get_or_404(message_id)
    
    # SECURITY CHECK: Siguroha nga ang nag-delete kay ang sender gyud
    # Para dili mapapas sa uban ang dili ilaha nga message
    if msg.sender_id == session.get('user_id'):
        try:
            # Kung naay mga reply kani nga message, 
            # kinahanglan nato i-handle (i-set to null ang parent_id sa replies)
            Message.query.filter_by(parent_id=message_id).update({"parent_id": None})
            
            db.session.delete(msg)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Delete Error: {e}")
            return "Error deleting message", 500
    
    # Inig human delete, i-balik siya sa iyang gi-gikanan nga page
    return redirect(request.referrer or url_for('inbox'))

@app.route('/react_message/<int:message_id>', methods=['POST'])
@login_required
def react_message(message_id):
    data = request.get_json()
    reaction = data.get('reaction')
    
    msg = Message.query.get_or_404(message_id)
    # Pwede ra bisan kinsa mo-react (sender o receiver)
    msg.reaction = reaction 
    
    try:
        db.session.commit()
        return {"status": "success", "reaction": reaction}, 200
    except Exception as e:
        db.session.rollback()
        return {"status": "error"}, 500

@app.route('/notifications')
@login_required
def notifications():
    user = db.session.get(User, session['user_id'])
    notification_count = 0
    return render_template('notifications.html', user=user, notification_count=notification_count)

@app.route('/api/unread-count')
def unread_count():
    # I-check kung naay naka-login sa session
    if 'user_id' not in session:
        return {"count": 0}
    
    user_id = session['user_id']
    
    # Gamita ang user_id gikan sa session para sa query
    count = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    return {"count": count}

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
