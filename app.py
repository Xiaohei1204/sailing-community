"""
帆船交流平台 - 后端主程序（PostgreSQL 持久化版本）
Sailing Community Platform - Flask Backend with SQLAlchemy
"""

import os
import re
import sys
import time
import uuid
import json
import hashlib
import threading
import requests as http_requests
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, request, jsonify, send_from_directory,
    render_template, session, send_file
)
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from PIL import Image
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())
CORS(app, supports_credentials=True)

# Session Cookie 配置（HTTPS 环境必须）
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_HTTPONLY'] = True

# ============ 数据库配置 ============
database_url = os.environ.get('DATABASE_URL', '')
# Render 的 PostgreSQL URL 是 postgres://，SQLAlchemy 1.4+ 需要 postgresql://
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

if database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # 本地开发用 SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sailing.db'

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ============ 上传配置 ============
UPLOAD_FOLDER_IMAGES = os.path.join('static', 'uploads', 'images')
UPLOAD_FOLDER_VIDEOS = os.path.join('static', 'uploads', 'videos')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'avi'}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB

os.makedirs(UPLOAD_FOLDER_IMAGES, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_VIDEOS, exist_ok=True)


# ============ 数据库模型 ============

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.String(8), primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    nickname = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), default='')
    avatar = db.Column(db.String(500), default='')
    bio = db.Column(db.String(500), default='热爱帆船运动')
    created_at = db.Column(db.Float, default=time.time)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'nickname': self.nickname,
            'email': self.email or '',
            'has_email': bool(self.email),
            'avatar': self.avatar or '',
            'bio': self.bio or ''
        }


# 帖子-标签关联表
post_tags = db.Table('post_tags',
    db.Column('post_id', db.String(8), db.ForeignKey('posts.id'), primary_key=True),
    db.Column('tag_name', db.String(50), db.ForeignKey('tags.name'), primary_key=True)
)

# 帖子-点赞用户关联表
post_likes = db.Table('post_likes',
    db.Column('post_id', db.String(8), db.ForeignKey('posts.id'), primary_key=True),
    db.Column('user_id', db.String(8), db.ForeignKey('users.id'), primary_key=True)
)


class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.String(8), primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    images = db.Column(db.Text, default='[]')  # JSON 数组字符串
    videos = db.Column(db.Text, default='[]')  # JSON 数组字符串
    likes = db.Column(db.Integer, default=0)
    views = db.Column(db.Integer, default=0)
    user_id = db.Column(db.String(8), db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.Float, default=time.time)

    tags = db.relationship('Tag', secondary=post_tags, lazy='subquery')
    liked_by_users = db.relationship('User', secondary=post_likes, lazy='subquery')

    def get_images(self):
        import json
        try:
            return json.loads(self.images)
        except:
            return []

    def set_images(self, val):
        import json
        self.images = json.dumps(val, ensure_ascii=False)

    def get_videos(self):
        import json
        try:
            return json.loads(self.videos)
        except:
            return []

    def set_videos(self, val):
        import json
        self.videos = json.dumps(val, ensure_ascii=False)

    def get_tags_list(self):
        return [t.name for t in self.tags]


class Tag(db.Model):
    __tablename__ = 'tags'
    name = db.Column(db.String(50), primary_key=True)


class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.String(8), primary_key=True)
    post_id = db.Column(db.String(8), db.ForeignKey('posts.id'), nullable=False)
    user_id = db.Column(db.String(8), db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    parent_id = db.Column(db.String(8), db.ForeignKey('comments.id'), default=None, nullable=True)
    created_at = db.Column(db.Float, default=time.time)


class PasswordReset(db.Model):
    __tablename__ = 'password_resets'
    id = db.Column(db.String(8), primary_key=True)
    user_id = db.Column(db.String(8), db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.Float, default=time.time)

    user = db.relationship('User')


# ============ 工具函数 ============

def generate_id():
    return str(uuid.uuid4())[:8]


def allowed_file(filename, allowed_ext):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_ext


def time_ago(timestamp):
    now = time.time()
    diff = now - timestamp
    if diff < 60:
        return '刚刚'
    elif diff < 3600:
        return f'{int(diff // 60)}分钟前'
    elif diff < 86400:
        return f'{int(diff // 3600)}小时前'
    elif diff < 2592000:
        return f'{int(diff // 86400)}天前'
    else:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d')


def get_or_create_tag(name):
    tag = Tag.query.get(name)
    if not tag:
        tag = Tag(name=name)
        db.session.add(tag)
    return tag


def send_email(to_email, subject, html_content):
    """通过 Resend API 发送邮件"""
    api_key = os.environ.get('RESEND_API_KEY', '')
    if not api_key:
        print(f'⚠️ RESEND_API_KEY 未配置，无法发送邮件到 {to_email}')
        return False

    from_email = os.environ.get('MAIL_FROM', 'sailing@onrender.com')

    try:
        resp = http_requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'from': f'帆船交流平台 <{from_email}>',
                'to': [to_email],
                'subject': subject,
                'html': html_content
            },
            timeout=10
        )
        if resp.status_code == 200:
            print(f'✅ 邮件已发送到 {to_email}')
            return True
        else:
            print(f'❌ 邮件发送失败: {resp.text}')
            return False
    except Exception as e:
        print(f'❌ 邮件发送异常: {e}')
        return False


# ============ 登录检查 ============

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '请先登录'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ============ 健康检查 ============

@app.route('/api/health')
def health_check():
    try:
        db.session.execute(db.text('SELECT 1'))
        db_ok = True
        db_msg = 'connected'
    except Exception as e:
        db_ok = False
        db_msg = str(e)

    return jsonify({
        'success': True,
        'database': {
            'ok': db_ok,
            'message': db_msg
        },
        'has_database_url': bool(os.environ.get('DATABASE_URL', ''))
    })


# ============ 页面路由 ============

@app.route('/')
def index():
    return render_template('index.html')


# ============ 用户 API ============

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '请求数据无效'})
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        confirm_password = data.get('confirm_password', '').strip()
        nickname = data.get('nickname', '').strip() or username
        email = data.get('email', '').strip()

        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'})
        if len(username) < 2 or len(username) > 20:
            return jsonify({'success': False, 'message': '用户名长度2-20个字符'})
        if len(password) < 4:
            return jsonify({'success': False, 'message': '密码至少4个字符'})
        if password != confirm_password:
            return jsonify({'success': False, 'message': '两次输入的密码不一致'})
        if not email:
            return jsonify({'success': False, 'message': '请输入邮箱地址'})

        # 邮箱格式校验
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            return jsonify({'success': False, 'message': '邮箱格式不正确'})

        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'message': '用户名已存在'})
        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'message': '该邮箱已被注册'})

        user = User(
            id=generate_id(),
            username=username,
            password=password,
            nickname=nickname,
            email=email,
            bio='热爱帆船运动'
        )
        db.session.add(user)
        db.session.commit()

        session['user_id'] = user.id
        session['username'] = user.username
        session['nickname'] = user.nickname

        return jsonify({'success': True, 'user': user.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'注册失败: {str(e)}'})


@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '请求数据无效'})
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        user = User.query.filter_by(username=username, password=password).first()
        if not user:
            return jsonify({'success': False, 'message': '用户名或密码错误'})

        session['user_id'] = user.id
        session['username'] = user.username
        session['nickname'] = user.nickname

        return jsonify({'success': True, 'user': user.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'message': f'登录失败: {str(e)}'})


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/current_user', methods=['GET'])
def current_user():
    if 'user_id' not in session:
        return jsonify({'success': False, 'user': None})

    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return jsonify({'success': False, 'user': None})

    return jsonify({'success': True, 'user': user.to_dict()})


@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    """发送密码重置邮件"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '请求数据无效'})

    email = data.get('email', '').strip()
    if not email:
        return jsonify({'success': False, 'message': '请输入邮箱地址'})

    # 查找该邮箱对应的用户
    user = User.query.filter_by(email=email).first()
    if not user:
        # 安全考虑：不透露邮箱是否存在
        return jsonify({'success': True, 'message': '如果该邮箱已绑定，重置链接已发送'})

    # 使旧 token 失效
    old_resets = PasswordReset.query.filter_by(user_id=user.id, used=False).all()
    for r in old_resets:
        r.used = True

    # 生成新 token
    token = hashlib.sha256(f"{user.id}{time.time()}{uuid.uuid4().hex}".encode()).hexdigest()[:32]

    reset_record = PasswordReset(
        id=generate_id(),
        user_id=user.id,
        token=token
    )
    db.session.add(reset_record)
    db.session.commit()

    # 构建重置链接
    base_url = os.environ.get('BASE_URL', request.host_url.rstrip('/'))
    reset_url = f"{base_url}/#/reset-password?token={token}"

    # 发送邮件
    html = f"""
    <div style="max-width:600px;margin:0 auto;font-family:sans-serif;padding:20px">
        <div style="text-align:center;margin-bottom:30px">
            <span style="font-size:3rem">⛵</span>
            <h1 style="color:#0c7bb3;margin:10px 0">帆船交流平台</h1>
        </div>
        <div style="background:#f8fafc;border-radius:12px;padding:30px;border:1px solid #e2e8f0">
            <h2 style="margin-top:0;color:#1e293b">重置你的密码</h2>
            <p style="color:#64748b;font-size:15px;line-height:1.6">
                你好 <strong>{user.nickname}</strong>，我们收到了重置密码的请求。<br>
                点击下方按钮设置新密码，链接 30 分钟内有效：
            </p>
            <div style="text-align:center;margin:30px 0">
                <a href="{reset_url}" style="background:#0c7bb3;color:white;padding:12px 32px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:500">
                    重置密码
                </a>
            </div>
            <p style="color:#94a3b8;font-size:13px">
                如果按钮无法点击，请复制以下链接到浏览器打开：<br>
                <a href="{reset_url}" style="color:#0c7bb3;word-break:break-all">{reset_url}</a>
            </p>
            <p style="color:#94a3b8;font-size:13px;margin-top:20px">
                如果你没有请求重置密码，请忽略此邮件。
            </p>
        </div>
        <p style="text-align:center;color:#94a3b8;font-size:12px;margin-top:20px">
            帆船交流平台 · 与全球帆船爱好者分享航海故事
        </p>
    </div>
    """

    send_email(email, '⛵ 重置你的帆船交流平台密码', html)

    return jsonify({'success': True, 'message': '如果该邮箱已绑定，重置链接已发送'})


@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    """通过 token 重置密码"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '请求数据无效'})

    token = data.get('token', '').strip()
    new_password = data.get('password', '').strip()

    if not token or not new_password:
        return jsonify({'success': False, 'message': '参数不完整'})
    if len(new_password) < 4:
        return jsonify({'success': False, 'message': '密码至少4个字符'})

    # 查找有效的 token
    reset_record = PasswordReset.query.filter_by(token=token, used=False).first()
    if not reset_record:
        return jsonify({'success': False, 'message': '重置链接无效或已过期'})

    # 检查是否过期（30分钟）
    if time.time() - reset_record.created_at > 1800:
        reset_record.used = True
        db.session.commit()
        return jsonify({'success': False, 'message': '重置链接已过期，请重新申请'})

    # 重置密码
    user = User.query.get(reset_record.user_id)
    if not user:
        return jsonify({'success': False, 'message': '用户不存在'})

    user.password = new_password
    reset_record.used = True
    db.session.commit()

    return jsonify({'success': True, 'message': '密码重置成功'})


@app.route('/api/verify-reset-token', methods=['POST'])
def verify_reset_token():
    """验证重置 token 是否有效"""
    data = request.get_json()
    token = data.get('token', '').strip() if data else ''

    reset_record = PasswordReset.query.filter_by(token=token, used=False).first()
    if not reset_record:
        return jsonify({'success': False, 'message': '重置链接无效'})

    if time.time() - reset_record.created_at > 1800:
        return jsonify({'success': False, 'message': '重置链接已过期'})

    return jsonify({'success': True, 'message': '链接有效'})


@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': '用户不存在'})

    post_count = Post.query.filter_by(user_id=user_id).count()

    return jsonify({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'nickname': user.nickname,
            'avatar': user.avatar or '',
            'bio': user.bio or '',
            'post_count': post_count,
            'joined': time_ago(user.created_at)
        }
    })


@app.route('/api/user/profile', methods=['PUT'])
@login_required
def update_profile():
    data = request.get_json()
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'success': False, 'message': '用户不存在'})

    if 'nickname' in data:
        user.nickname = data['nickname'].strip() or user.username
        session['nickname'] = user.nickname
    if 'bio' in data:
        user.bio = data['bio'].strip()

    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()})


@app.route('/api/user/bind-email', methods=['POST'])
@login_required
def bind_email():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '请求数据无效'})

    email = data.get('email', '').strip()

    if not email:
        return jsonify({'success': False, 'message': '邮箱不能为空'})

    # 简单邮箱格式校验
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return jsonify({'success': False, 'message': '邮箱格式不正确'})

    # 检查邮箱是否已被其他用户绑定
    existing = User.query.filter_by(email=email).first()
    if existing and existing.id != session['user_id']:
        return jsonify({'success': False, 'message': '该邮箱已被其他用户绑定'})

    user = User.query.get(session['user_id'])
    user.email = email
    db.session.commit()

    return jsonify({'success': True, 'user': user.to_dict()})


# ============ 帖子 API ============

@app.route('/api/posts', methods=['GET'])
def get_posts():
    query = Post.query

    tag = request.args.get('tag', '').strip()
    keyword = request.args.get('keyword', '').strip()
    user_id = request.args.get('user_id', '').strip()
    sort = request.args.get('sort', 'latest')

    if tag:
        tag_obj = Tag.query.get(tag)
        if tag_obj:
            query = query.filter(Post.tags.contains(tag_obj))
        else:
            return jsonify({'success': True, 'posts': []})

    if user_id:
        query = query.filter_by(user_id=user_id)

    if keyword:
        query = query.filter(
            db.or_(
                Post.title.ilike(f'%{keyword}%'),
                Post.content.ilike(f'%{keyword}%')
            )
        )

    if sort == 'hot':
        query = query.order_by(Post.likes.desc())
    else:
        query = query.order_by(Post.created_at.desc())

    posts = query.all()

    result = []
    for p in posts:
        author = User.query.get(p.user_id)
        comment_count = Comment.query.filter_by(post_id=p.id).count()
        result.append({
            'id': p.id,
            'title': p.title,
            'content': p.content,
            'images': p.get_images(),
            'videos': p.get_videos(),
            'tags': p.get_tags_list(),
            'likes': p.likes,
            'views': p.views,
            'comment_count': comment_count,
            'created_at': p.created_at,
            'time_ago': time_ago(p.created_at),
            'author': {
                'id': author.id if author else '',
                'nickname': author.nickname if author else '匿名',
                'avatar': author.avatar if author else ''
            }
        })

    return jsonify({'success': True, 'posts': result})


@app.route('/api/posts', methods=['POST'])
@login_required
def create_post():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    tags_str = request.form.get('tags', '').strip()

    if not title:
        return jsonify({'success': False, 'message': '标题不能为空'})
    if not content:
        return jsonify({'success': False, 'message': '内容不能为空'})

    # 处理图片上传
    images = []
    oversized_names = []
    image_files = request.files.getlist('images')
    for img_file in image_files[:9]:
        if img_file and allowed_file(img_file.filename, ALLOWED_IMAGE_EXTENSIONS):
            img_file.seek(0, 2)
            size = img_file.tell()
            img_file.seek(0)
            if size > MAX_IMAGE_SIZE:
                oversized_names.append(img_file.filename)
                continue

            ext = img_file.filename.rsplit('.', 1)[1].lower()
            filename = f"{generate_id()}_{int(time.time())}.{ext}"
            filepath = os.path.join(UPLOAD_FOLDER_IMAGES, filename)

            img = Image.open(img_file)
            max_width = 1200
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            img.save(filepath, quality=85, optimize=True)

            images.append(f'/static/uploads/images/{filename}')

    # 处理视频上传
    videos = []
    video_files = request.files.getlist('videos')
    for vid_file in video_files[:3]:
        if vid_file and allowed_file(vid_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            vid_file.seek(0, 2)
            size = vid_file.tell()
            vid_file.seek(0)
            if size > MAX_VIDEO_SIZE:
                continue

            ext = vid_file.filename.rsplit('.', 1)[1].lower()
            filename = f"{generate_id()}_{int(time.time())}.{ext}"
            filepath = os.path.join(UPLOAD_FOLDER_VIDEOS, filename)
            vid_file.save(filepath)
            videos.append(f'/static/uploads/videos/{filename}')

    post = Post(
        id=generate_id(),
        title=title,
        content=content,
        user_id=session['user_id']
    )
    post.set_images(images)
    post.set_videos(videos)

    # 处理标签
    if tags_str:
        tag_names = [t.strip() for t in tags_str.split(',') if t.strip()]
        for tag_name in tag_names:
            tag_obj = get_or_create_tag(tag_name)
            post.tags.append(tag_obj)

    db.session.add(post)
    db.session.commit()

    result = {'success': True, 'post_id': post.id}
    if oversized_names:
        result['warning'] = f"以下图片超过5MB已被跳过：{', '.join(oversized_names)}"
    return jsonify(result)


@app.route('/api/posts/<post_id>', methods=['GET'])
def get_post(post_id):
    post = Post.query.get(post_id)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})

    # 增加浏览量
    post.views += 1
    db.session.commit()

    author = User.query.get(post.user_id)

    # 获取评论
    post_comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at).all()

    comment_list = []
    for c in post_comments:
        c_author = User.query.get(c.user_id)
        reply_to = None
        if c.parent_id:
            parent_comment = Comment.query.get(c.parent_id)
            if parent_comment:
                parent_author = User.query.get(parent_comment.user_id)
                reply_to = {
                    'id': parent_comment.id,
                    'nickname': parent_author.nickname if parent_author else '匿名',
                    'content': parent_comment.content[:50] + ('...' if len(parent_comment.content) > 50 else ''),
                }
        comment_list.append({
            'id': c.id,
            'content': c.content,
            'parent_id': c.parent_id,
            'reply_to': reply_to,
            'created_at': c.created_at,
            'time_ago': time_ago(c.created_at),
            'author': {
                'id': c_author.id if c_author else '',
                'nickname': c_author.nickname if c_author else '匿名',
                'avatar': c_author.avatar if c_author else ''
            }
        })

    is_liked = False
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and user in post.liked_by_users:
            is_liked = True

    return jsonify({
        'success': True,
        'post': {
            'id': post.id,
            'title': post.title,
            'content': post.content,
            'images': post.get_images(),
            'videos': post.get_videos(),
            'tags': post.get_tags_list(),
            'likes': post.likes,
            'views': post.views,
            'is_liked': is_liked,
            'comment_count': len(post_comments),
            'created_at': post.created_at,
            'time_ago': time_ago(post.created_at),
            'author': {
                'id': author.id if author else '',
                'nickname': author.nickname if author else '匿名',
                'avatar': author.avatar if author else ''
            },
            'comments': comment_list
        }
    })


@app.route('/api/posts/<post_id>', methods=['DELETE'])
@login_required
def delete_post(post_id):
    post = Post.query.get(post_id)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})
    if post.user_id != session['user_id']:
        return jsonify({'success': False, 'message': '无权删除'})

    # 删除关联文件
    for img in post.get_images():
        img_path = os.path.join(os.path.dirname(__file__), img.lstrip('/'))
        if os.path.exists(img_path):
            os.remove(img_path)
    for vid in post.get_videos():
        vid_path = os.path.join(os.path.dirname(__file__), vid.lstrip('/'))
        if os.path.exists(vid_path):
            os.remove(vid_path)

    # 删除评论
    Comment.query.filter_by(post_id=post_id).delete()
    db.session.delete(post)
    db.session.commit()

    return jsonify({'success': True})


# ============ 点赞 API ============

@app.route('/api/posts/<post_id>/like', methods=['POST'])
@login_required
def toggle_like(post_id):
    post = Post.query.get(post_id)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})

    user = User.query.get(session['user_id'])

    if user in post.liked_by_users:
        post.liked_by_users.remove(user)
        post.likes = max(0, post.likes - 1)
        liked = False
    else:
        post.liked_by_users.append(user)
        post.likes += 1
        liked = True

    db.session.commit()
    return jsonify({'success': True, 'liked': liked, 'likes': post.likes})


# ============ 评论 API ============

@app.route('/api/posts/<post_id>/comments', methods=['POST'])
@login_required
def add_comment(post_id):
    data = request.get_json()
    content = data.get('content', '').strip()
    parent_id = data.get('parent_id', None)

    if not content:
        return jsonify({'success': False, 'message': '评论内容不能为空'})

    post = Post.query.get(post_id)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})

    # 验证 parent_id：如果指定了回复目标，必须存在且属于同一帖子
    if parent_id:
        parent_comment = Comment.query.get(parent_id)
        if not parent_comment:
            return jsonify({'success': False, 'message': '回复的评论不存在'})
        if parent_comment.post_id != post_id:
            return jsonify({'success': False, 'message': '不能回复其他帖子的评论'})

    comment = Comment(
        id=generate_id(),
        post_id=post_id,
        user_id=session['user_id'],
        content=content,
        parent_id=parent_id,
    )
    db.session.add(comment)
    db.session.commit()

    user = User.query.get(session['user_id'])

    # 构建返回数据
    result_comment = {
        'id': comment.id,
        'content': comment.content,
        'parent_id': comment.parent_id,
        'time_ago': time_ago(comment.created_at),
        'author': {
            'id': user.id,
            'nickname': user.nickname,
            'avatar': user.avatar or ''
        }
    }

    # 如果是回复，附带被回复信息
    if parent_id:
        parent_comment = Comment.query.get(parent_id)
        if parent_comment:
            parent_author = User.query.get(parent_comment.user_id)
            result_comment['reply_to'] = {
                'id': parent_comment.id,
                'nickname': parent_author.nickname if parent_author else '匿名',
                'content': parent_comment.content[:50] + ('...' if len(parent_comment.content) > 50 else ''),
            }

    return jsonify({
        'success': True,
        'comment': result_comment
    })


# ============ 标签 API ============

@app.route('/api/tags', methods=['GET'])
def get_tags():
    tags = Tag.query.all()
    result = []
    for t in tags:
        count = db.session.query(post_tags).filter_by(tag_name=t.name).count()
        if count > 0:
            result.append({'name': t.name, 'count': count})
    result.sort(key=lambda x: x['count'], reverse=True)
    return jsonify({'success': True, 'tags': result})


# ============ 统计 API ============

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify({
        'success': True,
        'stats': {
            'posts': Post.query.count(),
            'users': User.query.count(),
            'comments': Comment.query.count()
        }
    })


# ============ 数据库备份 & 恢复 ============

BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'backups')
os.makedirs(BACKUP_DIR, exist_ok=True)


def export_backup_json():
    """导出所有数据为 JSON 字典"""
    with app.app_context():
        data = {
            'version': 1,
            'timestamp': time.time(),
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'users': [],
            'posts': [],
            'comments': [],
            'tags': [],
            'post_tags': [],
            'post_likes': [],
            'password_resets': [],
        }

        for u in User.query.all():
            data['users'].append({
                'id': u.id, 'username': u.username, 'password': u.password,
                'nickname': u.nickname, 'email': u.email or '',
                'avatar': u.avatar or '', 'bio': u.bio or '',
                'created_at': u.created_at,
            })

        for p in Post.query.all():
            data['posts'].append({
                'id': p.id, 'title': p.title, 'content': p.content,
                'images': p.get_images(), 'videos': p.get_videos(),
                'likes': p.likes, 'views': p.views, 'user_id': p.user_id,
                'created_at': p.created_at,
                'tags': p.get_tags_list(),
            })

        for c in Comment.query.all():
            data['comments'].append({
                'id': c.id, 'post_id': c.post_id, 'user_id': c.user_id,
                'content': c.content, 'parent_id': c.parent_id,
                'created_at': c.created_at,
            })

        for t in Tag.query.all():
            data['tags'].append({'name': t.name})

        # 关联表
        rows = db.session.execute(db.text('SELECT post_id, tag_name FROM post_tags')).fetchall()
        for r in rows:
            data['post_tags'].append({'post_id': r[0], 'tag_name': r[1]})

        rows = db.session.execute(db.text('SELECT post_id, user_id FROM post_likes')).fetchall()
        for r in rows:
            data['post_likes'].append({'post_id': r[0], 'user_id': r[1]})

        for pr in PasswordReset.query.all():
            data['password_resets'].append({
                'id': pr.id, 'user_id': pr.user_id, 'token': pr.token,
                'used': pr.used, 'created_at': pr.created_at,
            })

        return data


def save_backup_file():
    """保存备份到本地文件，返回文件路径"""
    data = export_backup_json()
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'backup_{date_str}.json'
    filepath = os.path.join(BACKUP_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 清理旧备份，只保留最近 7 份
    backup_files = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith('backup_') and f.endswith('.json')],
        reverse=True
    )
    for old_file in backup_files[7:]:
        os.remove(os.path.join(BACKUP_DIR, old_file))

    print(f'💾 数据库备份已保存: {filename} (共 {len(data["users"])} 用户, {len(data["posts"])} 帖子)')
    return filepath


def push_backup_to_github(filepath):
    """将备份文件推送到 GitHub 仓库（需要 GH_TOKEN 环境变量）"""
    token = os.environ.get('GH_TOKEN', '')
    repo = os.environ.get('GH_REPO', 'Xiaohei1204/sailing-community')
    if not token:
        return False

    filename = os.path.basename(filepath)
    branch = os.environ.get('GH_BACKUP_BRANCH', 'main')

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    import base64
    encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')

    # 先检查文件是否已存在（获取 SHA）
    api_url = f'https://api.github.com/repos/{repo}/contents/backups/{filename}'
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
    }

    try:
        # 尝试创建文件
        payload = {
            'message': f'💾 自动数据库备份 {filename}',
            'content': encoded,
            'branch': branch,
        }

        # 检查文件是否已存在
        existing = http_requests.get(api_url, headers=headers, timeout=10)
        if existing.status_code == 200:
            payload['sha'] = existing.json().get('sha', '')

        resp = http_requests.put(api_url, headers=headers, json=payload, timeout=30)
        if resp.status_code in (200, 201):
            print(f'☁️  备份已推送到 GitHub: backups/{filename}')
            return True
        else:
            print(f'⚠️ GitHub 推送失败: {resp.status_code} {resp.text[:200]}')
            return False
    except Exception as e:
        print(f'⚠️ GitHub 推送异常: {e}')
        return False


def auto_backup_job():
    """定时备份任务：保存本地 + 推送 GitHub"""
    try:
        filepath = save_backup_file()
        push_backup_to_github(filepath)
    except Exception as e:
        print(f'⚠️ 自动备份失败: {e}')


def restore_from_data(data):
    """从备份数据字典恢复到数据库（跳过已存在的记录）"""
    if not data or data.get('version') != 1:
        print('❌ 备份数据格式无效')
        return {'users': 0, 'posts': 0, 'comments': 0, 'tags': 0, 'skipped': 0}

    restored = {'users': 0, 'posts': 0, 'comments': 0, 'tags': 0, 'skipped': 0}

    for u_data in data.get('users', []):
        if User.query.get(u_data['id']):
            restored['skipped'] += 1
            continue
        db.session.add(User(
            id=u_data['id'], username=u_data['username'],
            password=u_data['password'], nickname=u_data['nickname'],
            email=u_data.get('email', ''), avatar=u_data.get('avatar', ''),
            bio=u_data.get('bio', '热爱帆船运动'),
            created_at=u_data.get('created_at', time.time()),
        ))
        restored['users'] += 1

    for t_data in data.get('tags', []):
        if not Tag.query.get(t_data['name']):
            db.session.add(Tag(name=t_data['name']))
            restored['tags'] += 1

    db.session.flush()

    for p_data in data.get('posts', []):
        if Post.query.get(p_data['id']):
            restored['skipped'] += 1
            continue
        post = Post(
            id=p_data['id'], title=p_data['title'], content=p_data['content'],
            likes=p_data.get('likes', 0), views=p_data.get('views', 0),
            user_id=p_data['user_id'], created_at=p_data.get('created_at', time.time()),
        )
        post.set_images(p_data.get('images', []))
        post.set_videos(p_data.get('videos', []))
        for tag_name in p_data.get('tags', []):
            tag_obj = Tag.query.get(tag_name)
            if tag_obj:
                post.tags.append(tag_obj)
        db.session.add(post)
        restored['posts'] += 1

    db.session.flush()

    for c_data in data.get('comments', []):
        if Comment.query.get(c_data['id']):
            continue
        db.session.add(Comment(
            id=c_data['id'], post_id=c_data['post_id'],
            user_id=c_data['user_id'], content=c_data['content'],
            parent_id=c_data.get('parent_id', None),
            created_at=c_data.get('created_at', time.time()),
        ))
        restored['comments'] += 1

    for lk in data.get('post_likes', []):
        exists = db.session.execute(db.text(
            "SELECT 1 FROM post_likes WHERE post_id=:pid AND user_id=:uid"
        ), {'pid': lk['post_id'], 'uid': lk['user_id']}).fetchone()
        if not exists:
            db.session.execute(db.text(
                "INSERT INTO post_likes (post_id, user_id) VALUES (:pid, :uid)"
            ), {'pid': lk['post_id'], 'uid': lk['user_id']})

    db.session.commit()
    return restored


@app.route('/api/backup', methods=['GET'])
@login_required
def download_backup():
    """手动下载数据库备份（JSON 文件）"""
    data = export_backup_json()
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'backup_{date_str}.json'

    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()

    return send_file(
        tmp.name,
        mimetype='application/json',
        as_attachment=True,
        download_name=filename
    )


@app.route('/api/restore', methods=['POST'])
@login_required
def restore_backup():
    """从 JSON 备份文件恢复数据"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '请上传备份文件'})

    file = request.files['file']
    if not file.filename.endswith('.json'):
        return jsonify({'success': False, 'message': '只支持 .json 备份文件'})

    try:
        data = json.load(file)
    except Exception:
        return jsonify({'success': False, 'message': '备份文件格式无效'})

    try:
        restored = restore_from_data(data)
        if not restored:
            return jsonify({'success': False, 'message': '备份版本不支持'})

        save_backup_file()
        return jsonify({
            'success': True,
            'message': f"恢复完成：{restored['users']} 用户, {restored['posts']} 帖子, {restored['comments']} 评论, {restored['tags']} 标签",
            'restored': restored
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'恢复失败: {str(e)}'})


@app.route('/api/backups/list', methods=['GET'])
@login_required
def list_backups():
    """列出本地备份文件"""
    files = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.startswith('backup_') and f.endswith('.json'):
            filepath = os.path.join(BACKUP_DIR, f)
            size = os.path.getsize(filepath)
            files.append({
                'filename': f,
                'size': f'{size / 1024:.1f}KB',
                'date': f.replace('backup_', '').replace('.json', '').replace('_', ' '),
            })
    return jsonify({'success': True, 'backups': files[:7]})


# ============ Render API & 28天自动迁移 ============

RENDER_API_BASE = 'https://api.render.com/v1'


def _render_headers():
    """Render API 请求头"""
    api_key = os.environ.get('RENDER_API_KEY', '')
    if not api_key:
        return None
    return {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }


def render_api(method, path, json_data=None, timeout=30):
    """调用 Render API"""
    headers = _render_headers()
    if not headers:
        return None
    try:
        resp = http_requests.request(
            method, f'{RENDER_API_BASE}{path}',
            headers=headers, json=json_data, timeout=timeout
        )
        if resp.status_code in (200, 201, 204):
            try:
                return resp.json()
            except:
                return True
        print(f'Render API {method} {path}: {resp.status_code} {resp.text[:200]}')
        return None
    except Exception as e:
        print(f'Render API 错误: {e}')
        return None


def find_render_resources():
    """自动查找 Render 上的 Web 服务和数据库"""
    result = {'service': None, 'database': None, 'owner_id': None}

    # 查找服务
    services = render_api('GET', '/services') or []
    for item in services:
        svc = item.get('service', item)
        if svc.get('type') == 'web_server':
            if result['service'] is None or 'sailing' in svc.get('name', '').lower():
                result['service'] = svc
                result['owner_id'] = svc.get('ownerId')

    # 查找数据库（Render API 用 /postgres 端点）
    databases = render_api('GET', '/postgres') or []
    for item in databases:
        db_item = item.get('postgres', item)
        if result['database'] is None or 'sailing' in db_item.get('name', '').lower():
            result['database'] = db_item
            if not result['owner_id']:
                result['owner_id'] = db_item.get('ownerId')

    return result


def get_db_age_days():
    """通过 Render API 获取数据库已运行天数"""
    resources = find_render_resources()
    db_info = resources.get('database')
    if not db_info or not db_info.get('createdAt'):
        return None
    try:
        created = datetime.fromisoformat(db_info['createdAt'].replace('Z', '+00:00'))
        return (datetime.now(timezone.utc) - created).days
    except:
        return None


def fetch_github_backup():
    """从 GitHub 仓库下载最新的备份 JSON"""
    token = os.environ.get('GH_TOKEN', '')
    repo = os.environ.get('GH_REPO', 'Xiaohei1204/sailing-community')
    branch = os.environ.get('GH_BACKUP_BRANCH', 'main')

    if not token:
        print('⚠️ GH_TOKEN 未配置，无法从 GitHub 获取备份')
        return None

    try:
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
        }
        resp = http_requests.get(
            f'https://api.github.com/repos/{repo}/contents/backups',
            headers=headers, params={'ref': branch}, timeout=15
        )
        if resp.status_code != 200:
            print(f'⚠️ GitHub 备份目录不存在或无法访问: {resp.status_code}')
            return None

        files = [f for f in resp.json()
                 if isinstance(f, dict) and f.get('name', '').startswith('backup_') and f.get('name', '').endswith('.json')]
        if not files:
            print('⚠️ GitHub 备份目录中没有备份文件')
            return None

        # 按文件名排序取最新的
        files.sort(key=lambda f: f.get('name', ''), reverse=True)
        download_url = files[0].get('download_url')
        if not download_url:
            return None

        resp = http_requests.get(download_url, timeout=60)
        if resp.status_code == 200:
            print(f'✅ 从 GitHub 下载备份: {files[0]["name"]}')
            return resp.json()
        return None
    except Exception as e:
        print(f'⚠️ GitHub 备份获取失败: {e}')
        return None


def auto_restore_if_empty():
    """启动时检测：如果数据库为空，自动从 GitHub 备份恢复"""
    try:
        user_count = User.query.count()
        if user_count > 0:
            return

        print('🔄 数据库为空，尝试从 GitHub 备份自动恢复...')
        data = fetch_github_backup()
        if data:
            restored = restore_from_data(data)
            print(f'✅ 自动恢复完成: {restored["users"]} 用户, {restored["posts"]} 帖子, {restored["comments"]} 评论')
            # 恢复后再备份一次确保安全
            save_backup_file()
        else:
            print('⚠️ 没有找到 GitHub 备份，跳过自动恢复（新数据库）')
    except Exception as e:
        print(f'⚠️ 自动恢复异常: {e}')


def perform_migration():
    """28天自动迁移：备份 → 创建新数据库 → 更新环境变量 → 删除旧库 → 重新部署"""
    def _migrate():
        with app.app_context():
            try:
                print('🚀 ========== 开始28天自动数据库迁移 ==========')

                # 1. 查找当前资源
                resources = find_render_resources()
                old_db = resources.get('database')
                svc = resources.get('service')

                if not old_db or not svc:
                    print('❌ 找不到 Render 服务或数据库，迁移中止')
                    return

                old_db_id = old_db.get('id')
                old_db_name = old_db.get('name', 'unknown')
                owner_id = resources.get('owner_id') or old_db.get('ownerId') or svc.get('ownerId')
                region = old_db.get('region', 'oregon')
                print(f'📦 当前数据库: {old_db_name} (ID: {old_db_id})')
                print(f'📦 当前服务: {svc.get("name", "unknown")} (ID: {svc.get("id")})')
                print(f'📦 Owner ID: {owner_id}')

                # 2. 备份当前数据到 GitHub（安全第一）
                print('💾 步骤 1/6: 备份当前数据到 GitHub...')
                filepath = save_backup_file()
                github_ok = push_backup_to_github(filepath)
                if not github_ok:
                    print('❌ GitHub 备份失败，迁移中止（数据安全第一）')
                    return
                print('✅ GitHub 备份成功')

                # 3. 创建新数据库（使用正确的 /postgres 端点）
                print('🆕 步骤 2/6: 创建新免费数据库...')
                new_db_payload = {
                    'name': f'sailing-db-{int(time.time())}',
                    'region': region,
                    'plan': 'free',
                    'databaseName': 'sailing',
                    'databaseUser': 'sailing_user',
                    'ownerId': owner_id,
                    'version': '18',
                }

                new_db = render_api('POST', '/postgres', new_db_payload)
                if not new_db:
                    print('❌ 创建新数据库失败，迁移中止')
                    return

                new_db_info = new_db.get('postgres', new_db)
                new_db_id = new_db_info.get('id')
                print(f'✅ 新数据库已创建: ID={new_db_id}')

                # 4. 等待新数据库就绪（最多 10 分钟）
                print('⏳ 步骤 3/6: 等待新数据库就绪（约5-10分钟）...')
                ready = False
                new_conn_str = ''
                for i in range(20):
                    time.sleep(30)
                    result = render_api('GET', f'/postgres/{new_db_id}')
                    if result:
                        d = result.get('postgres', result)
                        status = d.get('status', '')
                        print(f'   数据库状态: {status} ({(i+1)*30}秒)')
                        if status == 'available':
                            new_conn_str = d.get('connectionString', '')
                            ready = True
                            break

                if not ready:
                    print('❌ 新数据库创建超时（10分钟），迁移中止')
                    print('⚠️ 请手动到 Render 检查数据库状态')
                    return

                # 修复连接字符串
                if new_conn_str.startswith('postgres://'):
                    new_conn_str = new_conn_str.replace('postgres://', 'postgresql://', 1)

                # 5. 更新环境变量（使用正确的 /services/{id}/env-vars/{key} 端点）
                print('🔧 步骤 4/6: 更新 DATABASE_URL 环境变量...')
                env_ok = render_api('PUT', f'/services/{svc["id"]}/env-vars/DATABASE_URL', {'value': new_conn_str})
                if not env_ok:
                    print('❌ 更新环境变量失败，迁移中止')
                    return
                print('✅ DATABASE_URL 已更新')

                # 6. 删除旧数据库
                print('🗑️  步骤 5/6: 删除旧数据库...')
                if old_db_id:
                    render_api('DELETE', f'/postgres/{old_db_id}')
                    print(f'✅ 旧数据库 {old_db_name} 已删除')

                # 7. 触发重新部署（新部署启动后会自动从 GitHub 恢复数据）
                print('🚀 步骤 6/6: 触发重新部署...')
                render_api('POST', f'/services/{svc["id"]}/deploys', {})

                print('✅ ========== 28天自动迁移完成！==========')
                print('📌 新部署启动后将自动从 GitHub 备份恢复数据')

            except Exception as e:
                print(f'❌ 自动迁移异常: {e}')

    thread = threading.Thread(target=_migrate, daemon=True)
    thread.start()


def daily_check_job():
    """每日定时任务：备份 + 检查数据库年龄 + 触发迁移"""
    try:
        # 1. 始终备份
        auto_backup_job()

        # 2. 如果配置了 Render API，检查数据库年龄
        if os.environ.get('RENDER_API_KEY'):
            age = get_db_age_days()
            if age is not None:
                print(f'📊 数据库已运行 {age} 天')
                if age >= 25:
                    print('⚠️ 数据库即将过期（30天），启动自动迁移！')
                    perform_migration()
                elif age >= 20:
                    print(f'⚠️ 数据库将在 {30 - age} 天后过期')
    except Exception as e:
        print(f'⚠️ 每日检查异常: {e}')


@app.route('/api/migration/status', methods=['GET'])
@login_required
def migration_status():
    """查看数据库迁移状态"""
    result = {
        'success': True,
        'has_render_api': bool(os.environ.get('RENDER_API_KEY', '')),
        'has_github_token': bool(os.environ.get('GH_TOKEN', '')),
        'db_age_days': None,
        'expires_in': None,
        'auto_migrate_enabled': bool(os.environ.get('RENDER_API_KEY', '')),
    }

    if result['has_render_api']:
        age = get_db_age_days()
        if age is not None:
            result['db_age_days'] = age
            result['expires_in'] = max(0, 30 - age)

    return jsonify(result)


@app.route('/api/migration/trigger', methods=['POST'])
@login_required
def trigger_migration():
    """手动触发数据库迁移"""
    if not os.environ.get('RENDER_API_KEY'):
        return jsonify({'success': False, 'message': 'RENDER_API_KEY 未配置，无法自动迁移'})

    perform_migration()
    return jsonify({'success': True, 'message': '迁移已在后台启动，请稍后检查服务状态'})


# ============ 初始化数据库 & 启动 ============

def init_db():
    """安全初始化数据库，自动迁移表结构（保留旧数据）+ 空库自动恢复"""
    with app.app_context():
        try:
            db.create_all()

            is_postgres = 'postgresql' in str(db.engine.url)

            # --- 迁移1：添加 email 列 ---
            email_exists = False
            if is_postgres:
                result = db.session.execute(db.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='users' AND column_name='email'"
                ))
                email_exists = result.fetchone() is not None
            else:
                result = db.session.execute(db.text("PRAGMA table_info(users)"))
                email_exists = any(row[1] == 'email' for row in result)

            if not email_exists:
                print('🔄 迁移：为 users 表添加 email 列（保留旧数据）...')
                db.session.execute(db.text(
                    "ALTER TABLE users ADD COLUMN email VARCHAR(120) DEFAULT ''"
                ))
                db.session.commit()
                print('✅ email 列已添加，旧数据完整保留')

            # --- 迁移2：添加 parent_id 列（评论回复功能） ---
            parent_id_exists = False
            if is_postgres:
                result = db.session.execute(db.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='comments' AND column_name='parent_id'"
                ))
                parent_id_exists = result.fetchone() is not None
            else:
                result = db.session.execute(db.text("PRAGMA table_info(comments)"))
                parent_id_exists = any(row[1] == 'parent_id' for row in result)

            if not parent_id_exists:
                print('🔄 迁移：为 comments 表添加 parent_id 列（保留旧数据）...')
                db.session.execute(db.text(
                    "ALTER TABLE comments ADD COLUMN parent_id VARCHAR(8) DEFAULT NULL"
                ))
                db.session.commit()
                print('✅ parent_id 列已添加，旧数据完整保留')

            if email_exists and parent_id_exists:
                print('✅ 数据库表结构正常')

        except Exception as e:
            err = str(e)
            if 'does not exist' in err and ('users' in err or 'comments' in err):
                print('🔄 表不存在，创建所有表...')
                db.create_all()
                print('✅ 数据库表已创建')
            elif 'already exists' in err or 'duplicate' in err:
                print('✅ 列已存在，跳过迁移')
            else:
                print(f'⚠️ 数据库初始化异常: {e}')
                raise

        # 数据库为空时自动从 GitHub 备份恢复
        auto_restore_if_empty()

init_db()

# ============ 定时任务调度 ============
# 启动时立即备份一次
try:
    with app.app_context():
        save_backup_file()
except Exception as e:
    print(f'⚠️ 启动备份失败: {e}')

# 启动时检查数据库年龄（如果配置了 Render API）
if os.environ.get('RENDER_API_KEY'):
    try:
        with app.app_context():
            age = get_db_age_days()
            if age is not None:
                print(f'📊 当前数据库已运行 {age} 天（Render 免费库30天过期）')
                if age >= 25:
                    print('⚠️ 数据库即将过期！将在后台启动自动迁移...')
                    perform_migration()
    except Exception as e:
        print(f'⚠️ 数据库年龄检查失败: {e}')

# 每天凌晨 3:00 自动备份 + 检查迁移
scheduler = BackgroundScheduler()
scheduler.add_job(daily_check_job, 'cron', hour=3, minute=0)
scheduler.start()
print('⏰ 每日定时任务已启动（凌晨 3:00: 备份 + 数据库年龄检查）')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print('⛵ 帆船交流平台启动中...')
    print(f'🖼️  图片目录: {UPLOAD_FOLDER_IMAGES}')
    print(f'🎬 视频目录: {UPLOAD_FOLDER_VIDEOS}')
    print(f'🌐 监听端口: {port}')
    auto_migrate = '✅ 已启用' if os.environ.get('RENDER_API_KEY') else '❌ 未配置 RENDER_API_KEY'
    github_backup = '✅ 已启用' if os.environ.get('GH_TOKEN') else '❌ 未配置 GH_TOKEN'
    print(f'🔄 28天自动迁移: {auto_migrate}')
    print(f'☁️  GitHub备份推送: {github_backup}')
    app.run(host='0.0.0.0', port=port, debug=False)
