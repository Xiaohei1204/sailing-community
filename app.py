"""
帆船交流平台 - 后端主程序（PostgreSQL 持久化版本）
Sailing Community Platform - Flask Backend with SQLAlchemy
"""

import os
import time
import uuid
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, jsonify, send_from_directory,
    render_template, session
)
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from PIL import Image

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
    avatar = db.Column(db.String(500), default='')
    bio = db.Column(db.String(500), default='热爱帆船运动')
    created_at = db.Column(db.Float, default=time.time)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'nickname': self.nickname,
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
    created_at = db.Column(db.Float, default=time.time)


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
        nickname = data.get('nickname', '').strip() or username

        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'})
        if len(username) < 2 or len(username) > 20:
            return jsonify({'success': False, 'message': '用户名长度2-20个字符'})
        if len(password) < 4:
            return jsonify({'success': False, 'message': '密码至少4个字符'})

        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'message': '用户名已存在'})

        user = User(
            id=generate_id(),
            username=username,
            password=password,
            nickname=nickname,
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
        comment_list.append({
            'id': c.id,
            'content': c.content,
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

    if not content:
        return jsonify({'success': False, 'message': '评论内容不能为空'})

    post = Post.query.get(post_id)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})

    comment = Comment(
        id=generate_id(),
        post_id=post_id,
        user_id=session['user_id'],
        content=content
    )
    db.session.add(comment)
    db.session.commit()

    user = User.query.get(session['user_id'])

    return jsonify({
        'success': True,
        'comment': {
            'id': comment.id,
            'content': comment.content,
            'time_ago': time_ago(comment.created_at),
            'author': {
                'id': user.id,
                'nickname': user.nickname,
                'avatar': user.avatar or ''
            }
        }
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


# ============ 初始化数据库 & 启动 ============

with app.app_context():
    # 删除旧表重建（模型结构变更后需要）
    db.drop_all()
    db.create_all()
    print('✅ 数据库表已创建/确认')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print('⛵ 帆船交流平台启动中...')
    print(f'🖼️  图片目录: {UPLOAD_FOLDER_IMAGES}')
    print(f'🎬 视频目录: {UPLOAD_FOLDER_VIDEOS}')
    print(f'🌐 监听端口: {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
