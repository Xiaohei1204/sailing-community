/**
 * 帆船交流平台 - 前端交互逻辑
 */

// ============ 全局状态 ============
const state = {
    currentUser: null,
    currentPage: 'home',
    currentSort: 'latest',
    currentTag: '',
    currentKeyword: '',
    currentPostId: null,
    authMode: 'login', // login | register
    uploadImages: [],
    uploadVideos: []
};

// ============ API 工具 ============
async function api(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            credentials: 'same-origin',
            ...options
        });
        return await response.json();
    } catch (e) {
        console.error('API Error:', e);
        return { success: false, message: '网络请求失败' };
    }
}

// ============ Toast 提示 ============
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = { success: 'fa-check-circle', error: 'fa-times-circle', info: 'fa-info-circle' };
    toast.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i> ${message}`;
    container.appendChild(toast);

    setTimeout(() => toast.remove(), 3000);
}

// ============ 页面切换 ============
function showPage(page, data) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));

    switch (page) {
        case 'home':
            document.getElementById('homePage').classList.add('active');
            state.currentPage = 'home';
            loadPosts();
            break;
        case 'detail':
            document.getElementById('detailPage').classList.add('active');
            state.currentPage = 'detail';
            state.currentPostId = data;
            loadPostDetail(data);
            break;
        case 'create':
            if (!state.currentUser) {
                showToast('请先登录', 'error');
                showAuthModal('login');
                return;
            }
            document.getElementById('createPage').classList.add('active');
            state.currentPage = 'create';
            break;
        case 'profile':
            document.getElementById('profilePage').classList.add('active');
            state.currentPage = 'profile';
            loadProfile(data || (state.currentUser ? state.currentUser.id : null));
            break;
    }

    window.scrollTo(0, 0);
}

// ============ 用户系统 ============
async function checkLogin() {
    const res = await api('/api/current_user');
    if (res.success && res.user) {
        state.currentUser = res.user;
        updateNavUser();

        // 未绑定邮箱时弹出提示
        if (!res.user.has_email) {
            setTimeout(() => showEmailModal(), 1000);
        }
    }
}

function updateNavUser() {
    if (state.currentUser) {
        document.getElementById('navAuth').style.display = 'none';
        document.getElementById('navUser').style.display = 'flex';
        document.getElementById('navNickname').textContent = state.currentUser.nickname;
        const avatar = document.getElementById('navAvatar');
        avatar.textContent = state.currentUser.nickname.charAt(0).toUpperCase();
    } else {
        document.getElementById('navAuth').style.display = 'flex';
        document.getElementById('navUser').style.display = 'none';
    }
}

function showAuthModal(mode) {
    state.authMode = mode;
    document.getElementById('authModal').classList.add('show');
    updateAuthModal();
}

function closeAuthModal() {
    document.getElementById('authModal').classList.remove('show');
    document.getElementById('authForm').reset();
}

function switchAuthMode() {
    state.authMode = state.authMode === 'login' ? 'register' : 'login';
    updateAuthModal();
}

function updateAuthModal() {
    const isLogin = state.authMode === 'login';
    document.getElementById('authTitle').textContent = isLogin ? '登录' : '注册';
    document.getElementById('emailGroup').style.display = isLogin ? 'none' : 'block';
    document.getElementById('nicknameGroup').style.display = isLogin ? 'none' : 'block';
    document.getElementById('confirmPasswordGroup').style.display = isLogin ? 'none' : 'block';
    document.getElementById('authSubmit').textContent = isLogin ? '登录' : '注册';
    document.getElementById('authSwitchText').textContent = isLogin ? '还没有账号？' : '已有账号？';
    document.getElementById('authSwitchLink').textContent = isLogin ? '注册' : '登录';
    document.getElementById('forgotPasswordLink').style.display = isLogin ? 'inline' : 'none';

    // 注册时邮箱和确认密码必填
    document.getElementById('authEmail').required = !isLogin;
    document.getElementById('authConfirmPassword').required = !isLogin;
}

async function submitAuth(e) {
    e.preventDefault();
    const username = document.getElementById('authUsername').value.trim();
    const password = document.getElementById('authPassword').value.trim();
    const email = document.getElementById('authEmail').value.trim();
    const nickname = document.getElementById('authNickname').value.trim();
    const confirm_password = document.getElementById('authConfirmPassword').value.trim();

    const isLogin = state.authMode === 'login';

    // 注册时前端校验
    if (!isLogin) {
        if (!email) {
            showToast('请输入邮箱地址', 'error');
            return;
        }
        if (password !== confirm_password) {
            showToast('两次输入的密码不一致', 'error');
            return;
        }
    }

    const url = isLogin ? '/api/login' : '/api/register';
    const body = isLogin
        ? { username, password }
        : { username, password, confirm_password, email, nickname };

    const res = await api(url, {
        method: 'POST',
        body: JSON.stringify(body)
    });

    if (res.success) {
        state.currentUser = res.user;
        updateNavUser();
        closeAuthModal();
        showToast(isLogin ? '登录成功' : '注册成功', 'success');
        if (state.currentPage === 'home') loadPosts();

        // 登录后检测是否绑定邮箱（老用户可能没有）
        if (isLogin && !res.user.has_email) {
            setTimeout(() => showEmailModal(), 500);
        }
    } else {
        showToast(res.message, 'error');
    }
}

async function logout() {
    await api('/api/logout', { method: 'POST' });
    state.currentUser = null;
    updateNavUser();
    showPage('home');
    showToast('已退出登录', 'info');
}

function toggleUserDropdown() {
    document.getElementById('userDropdown').classList.toggle('show');
}

// 点击外部关闭下拉菜单
document.addEventListener('click', (e) => {
    if (!e.target.closest('.user-menu')) {
        document.getElementById('userDropdown').classList.remove('show');
    }
});

// ============ 帖子列表 ============
async function loadPosts() {
    const container = document.getElementById('postsContainer');
    container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';

    let url = `/api/posts?sort=${state.currentSort}`;
    if (state.currentTag) url += `&tag=${encodeURIComponent(state.currentTag)}`;
    if (state.currentKeyword) url += `&keyword=${encodeURIComponent(state.currentKeyword)}`;

    const res = await api(url);

    if (res.success && res.posts.length > 0) {
        container.innerHTML = res.posts.map(p => renderPostCard(p)).join('');
    } else {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-sailboat"></i>
                <p>${state.currentTag || state.currentKeyword ? '没有找到相关帖子' : '还没有帖子，来发表第一篇吧！'}</p>
            </div>`;
    }

    // 加载统计
    loadStats();
}

function renderPostCard(post) {
    const imagesHtml = post.images.length > 0 ? renderPostImages(post.images) : '';
    const videosHtml = post.videos.length > 0 ? renderPostVideos(post.videos) : '';
    const tagsHtml = post.tags.length > 0
        ? `<div class="post-tags">${post.tags.map(t => `<span class="post-tag" onclick="filterByTag('${t}')">${t}</span>`).join('')}</div>`
        : '';
    const initial = post.author.nickname.charAt(0).toUpperCase();

    return `
        <div class="post-card">
            <div class="post-card-body">
                <div class="post-card-header">
                    <div class="post-author-avatar" onclick="showPage('profile','${post.author.id}')">${initial}</div>
                    <div class="post-author-info">
                        <div class="post-author-name" onclick="showPage('profile','${post.author.id}')" style="cursor:pointer">${post.author.nickname}</div>
                        <div class="post-time">${post.time_ago}</div>
                    </div>
                </div>
                <h3 class="post-card-title" onclick="showPage('detail','${post.id}')">${escapeHtml(post.title)}</h3>
                <div class="post-card-content">${escapeHtml(post.content)}</div>
                ${imagesHtml}
                ${videosHtml}
                ${tagsHtml}
                <div class="post-card-footer">
                    <button class="post-action" onclick="showPage('detail','${post.id}')">
                        <i class="far fa-eye"></i> ${post.views}
                    </button>
                    <button class="post-action" onclick="toggleLike('${post.id}', this)">
                        <i class="far fa-heart"></i> <span>${post.likes}</span>
                    </button>
                    <button class="post-action" onclick="showPage('detail','${post.id}')">
                        <i class="far fa-comment"></i> ${post.comment_count}
                    </button>
                </div>
            </div>
        </div>`;
}

function renderPostImages(images) {
    const colClass = images.length === 1 ? 'cols-1' : images.length <= 4 ? 'cols-2' : 'cols-3';
    return `<div class="post-images ${colClass}">
        ${images.map(src => `<img src="${src}" alt="帖子图片" onclick="openImageViewer('${src}')" loading="lazy">`).join('')}
    </div>`;
}

function renderPostVideos(videos) {
    return `<div class="post-videos">
        ${videos.map(src => `<video src="${src}" controls preload="metadata"></video>`).join('')}
    </div>`;
}

function switchSort(sort) {
    state.currentSort = sort;
    document.querySelectorAll('.feed-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.feed-tab[data-sort="${sort}"]`).classList.add('active');
    loadPosts();
}

function searchPosts() {
    state.currentKeyword = document.getElementById('searchInput').value.trim();
    state.currentTag = '';
    loadPosts();
}

function filterByTag(tag) {
    state.currentTag = tag;
    state.currentKeyword = '';
    document.getElementById('searchInput').value = '';
    // 更新标签高亮
    document.querySelectorAll('.tag-item').forEach(t => {
        t.classList.toggle('active', t.textContent === tag);
    });
    loadPosts();
}

// ============ 帖子详情 ============
async function loadPostDetail(postId) {
    const container = document.getElementById('detailContainer');
    container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';

    const res = await api(`/api/posts/${postId}`);
    if (!res.success) {
        container.innerHTML = `<div class="empty-state"><i class="fas fa-exclamation-circle"></i><p>${res.message}</p></div>`;
        return;
    }

    const post = res.post;
    const initial = post.author.nickname.charAt(0).toUpperCase();

    const imagesHtml = post.images.length > 0
        ? `<div class="detail-images">${post.images.map(src => `<img src="${src}" alt="帖子图片" onclick="openImageViewer('${src}')" loading="lazy">`).join('')}</div>`
        : '';

    const videosHtml = post.videos.length > 0
        ? `<div class="detail-videos">${post.videos.map(src => `<video src="${src}" controls preload="metadata"></video>`).join('')}</div>`
        : '';

    const tagsHtml = post.tags.length > 0
        ? `<div class="post-tags">${post.tags.map(t => `<span class="post-tag" onclick="filterByTag('${t}');showPage('home')">${t}</span>`).join('')}</div>`
        : '';

    const deleteHtml = state.currentUser && state.currentUser.id === post.author.id
        ? `<button class="detail-action" style="color:#ef4444" onclick="deletePost('${post.id}')"><i class="fas fa-trash"></i> 删除</button>`
        : '';

    container.innerHTML = `
        <button class="back-btn" onclick="showPage('home')"><i class="fas fa-arrow-left"></i> 返回列表</button>
        <div class="detail-card">
            <div class="detail-header">
                <div class="post-author-avatar" onclick="showPage('profile','${post.author.id}')" style="cursor:pointer">${initial}</div>
                <div>
                    <div class="post-author-name" onclick="showPage('profile','${post.author.id}')" style="cursor:pointer">${post.author.nickname}</div>
                    <div class="post-time">${post.time_ago}</div>
                </div>
            </div>
            <h1 class="detail-title">${escapeHtml(post.title)}</h1>
            <div class="detail-content">${escapeHtml(post.content)}</div>
            ${imagesHtml}
            ${videosHtml}
            ${tagsHtml}
            <div class="detail-actions">
                <button class="detail-action ${post.is_liked ? 'liked' : ''}" onclick="toggleLikeDetail('${post.id}', this)">
                    <i class="${post.is_liked ? 'fas' : 'far'} fa-heart"></i>
                    <span>${post.likes} 赞</span>
                </button>
                <button class="detail-action">
                    <i class="far fa-eye"></i> ${post.views} 浏览
                </button>
                <button class="detail-action">
                    <i class="far fa-comment"></i> ${post.comment_count} 评论
                </button>
                ${deleteHtml}
            </div>
            <div class="comments-section">
                <h3><i class="far fa-comment-dots"></i> 评论 (${post.comment_count})</h3>
                ${state.currentUser ? `
                    <div class="comment-input-area">
                        <div class="comment-avatar">${state.currentUser.nickname.charAt(0).toUpperCase()}</div>
                        <div class="comment-input-wrapper">
                            <textarea class="comment-input" id="commentInput" placeholder="写下你的评论..."></textarea>
                            <div class="comment-submit">
                                <button class="btn btn-primary btn-sm" onclick="submitComment('${post.id}')">发表评论</button>
                            </div>
                        </div>
                    </div>
                ` : `<p style="color:var(--text-light);font-size:0.9rem;margin-bottom:16px"><a href="#" onclick="showAuthModal('login');return false">登录</a> 后可以评论</p>`}
                <div class="comment-list">
                    ${post.comments.map(c => renderComment(c)).join('')}
                </div>
            </div>
        </div>`;
}

function renderComment(comment) {
    const initial = comment.author.nickname.charAt(0).toUpperCase();
    return `
        <div class="comment-item">
            <div class="comment-avatar" onclick="showPage('profile','${comment.author.id}')" style="cursor:pointer">${initial}</div>
            <div class="comment-body">
                <div class="comment-meta">
                    <span class="comment-author" onclick="showPage('profile','${comment.author.id}')" style="cursor:pointer">${comment.author.nickname}</span>
                    <span class="comment-time">${comment.time_ago}</span>
                </div>
                <div class="comment-text">${escapeHtml(comment.content)}</div>
            </div>
        </div>`;
}

// ============ 点赞 ============
async function toggleLike(postId, btn) {
    if (!state.currentUser) {
        showToast('请先登录', 'error');
        showAuthModal('login');
        return;
    }

    const res = await api(`/api/posts/${postId}/like`, { method: 'POST' });
    if (res.success) {
        const icon = btn.querySelector('i');
        const count = btn.querySelector('span');

        if (res.liked) {
            icon.className = 'fas fa-heart';
            btn.classList.add('liked');
        } else {
            icon.className = 'far fa-heart';
            btn.classList.remove('liked');
        }
        if (count) count.textContent = res.likes;
    }
}

async function toggleLikeDetail(postId, btn) {
    if (!state.currentUser) {
        showToast('请先登录', 'error');
        showAuthModal('login');
        return;
    }

    const res = await api(`/api/posts/${postId}/like`, { method: 'POST' });
    if (res.success) {
        const icon = btn.querySelector('i');
        const span = btn.querySelector('span');

        if (res.liked) {
            icon.className = 'fas fa-heart';
            btn.classList.add('liked');
        } else {
            icon.className = 'far fa-heart';
            btn.classList.remove('liked');
        }
        if (span) span.textContent = `${res.likes} 赞`;
    }
}

// ============ 评论 ============
async function submitComment(postId) {
    const input = document.getElementById('commentInput');
    const content = input.value.trim();
    if (!content) {
        showToast('评论内容不能为空', 'error');
        return;
    }

    const res = await api(`/api/posts/${postId}/comments`, {
        method: 'POST',
        body: JSON.stringify({ content })
    });

    if (res.success) {
        showToast('评论成功', 'success');
        loadPostDetail(postId); // 重新加载详情
    } else {
        showToast(res.message, 'error');
    }
}

// ============ 删除帖子 ============
async function deletePost(postId) {
    if (!confirm('确定要删除这篇帖子吗？')) return;

    const res = await api(`/api/posts/${postId}`, { method: 'DELETE' });
    if (res.success) {
        showToast('帖子已删除', 'success');
        showPage('home');
    } else {
        showToast(res.message, 'error');
    }
}

// ============ 发帖 ============
function handleImageUpload(input) {
    const files = Array.from(input.files);
    const maxImages = 9 - state.uploadImages.length;

    if (files.length > maxImages) {
        showToast(`最多上传9张图片，还可上传${maxImages}张`, 'error');
        return;
    }

    files.forEach(file => {
        if (file.size > 5 * 1024 * 1024) {
            showToast(`${file.name} 超过5MB限制，请压缩后上传`, 'error');
            return;
        }

        state.uploadImages.push(file);
    });

    renderImagePreview();
    input.value = '';
}

function handleVideoUpload(input) {
    const files = Array.from(input.files);
    const maxVideos = 3 - state.uploadVideos.length;

    if (files.length > maxVideos) {
        showToast(`最多上传3个视频，还可上传${maxVideos}个`, 'error');
        return;
    }

    files.forEach(file => {
        if (file.size > 100 * 1024 * 1024) {
            showToast(`${file.name} 超过100MB限制`, 'error');
            return;
        }

        state.uploadVideos.push(file);
    });

    renderVideoPreview();
    input.value = '';
}

function renderImagePreview() {
    const container = document.getElementById('imagePreview');
    container.innerHTML = state.uploadImages.map((file, i) => {
        const url = URL.createObjectURL(file);
        return `<div class="preview-item">
            <img src="${url}" alt="预览">
            <button class="preview-remove" onclick="removeImage(${i})">&times;</button>
        </div>`;
    }).join('');
}

function renderVideoPreview() {
    const container = document.getElementById('videoPreview');
    container.innerHTML = state.uploadVideos.map((file, i) => {
        return `<div class="video-preview-item">
            <i class="fas fa-film"></i>
            <span>${file.name}</span>
            <button class="preview-remove" onclick="removeVideo(${i})">&times;</button>
        </div>`;
    }).join('');
}

function removeImage(index) {
    state.uploadImages.splice(index, 1);
    renderImagePreview();
}

function removeVideo(index) {
    state.uploadVideos.splice(index, 1);
    renderVideoPreview();
}

async function submitPost(e) {
    e.preventDefault();

    const title = document.getElementById('postTitle').value.trim();
    const content = document.getElementById('postContent').value.trim();
    const tags = document.getElementById('postTags').value.trim();

    if (!title || !content) {
        showToast('标题和内容不能为空', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('title', title);
    formData.append('content', content);
    formData.append('tags', tags);

    state.uploadImages.forEach(file => formData.append('images', file));
    state.uploadVideos.forEach(file => formData.append('videos', file));

    try {
        const response = await fetch('/api/posts', {
            method: 'POST',
            body: formData,
            credentials: 'same-origin'
        });
        const res = await response.json();

        if (res.success) {
            showToast('发布成功！', 'success');
            state.uploadImages = [];
            state.uploadVideos = [];
            document.getElementById('createForm').reset();
            document.getElementById('imagePreview').innerHTML = '';
            document.getElementById('videoPreview').innerHTML = '';
            showPage('detail', res.post_id);
        } else {
            showToast(res.message, 'error');
        }
    } catch (err) {
        showToast('发布失败，请重试', 'error');
    }
}

// ============ 个人主页 ============
async function loadProfile(userId) {
    if (!userId) {
        showPage('home');
        return;
    }

    const container = document.getElementById('profileContainer');
    container.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';

    const [userRes, postsRes] = await Promise.all([
        api(`/api/user/${userId}`),
        api(`/api/posts?user_id=${userId}`)
    ]);

    if (!userRes.success) {
        container.innerHTML = `<div class="empty-state"><i class="fas fa-user-slash"></i><p>用户不存在</p></div>`;
        return;
    }

    const user = userRes.user;
    const posts = postsRes.success ? postsRes.posts : [];
    const initial = user.nickname.charAt(0).toUpperCase();

    container.innerHTML = `
        <button class="back-btn" onclick="showPage('home')"><i class="fas fa-arrow-left"></i> 返回</button>
        <div class="profile-header">
            <div class="profile-avatar">${initial}</div>
            <div class="profile-name">${escapeHtml(user.nickname)}</div>
            <div class="profile-bio">${escapeHtml(user.bio || '这个人很懒，什么都没写')}</div>
        </div>
        <div class="profile-stats-bar">
            <div class="profile-stat-item">
                <div class="profile-stat-value">${user.post_count}</div>
                <div class="profile-stat-label">帖子</div>
            </div>
            <div class="profile-stat-item">
                <div class="profile-stat-value">${posts.reduce((sum, p) => sum + p.likes, 0)}</div>
                <div class="profile-stat-label">获赞</div>
            </div>
            <div class="profile-stat-item">
                <div class="profile-stat-value">${user.joined}</div>
                <div class="profile-stat-label">加入</div>
            </div>
        </div>
        <div class="profile-posts-title"><i class="fas fa-file-alt"></i> TA的帖子</div>
        <div class="posts-list">
            ${posts.length > 0 ? posts.map(p => renderPostCard(p)).join('') : `
                <div class="empty-state">
                    <i class="fas fa-pen-fancy"></i>
                    <p>还没有发布帖子</p>
                </div>`}
        </div>`;
}

// ============ 绑定邮箱 ============

function showEmailModal() {
    document.getElementById('emailModal').classList.add('show');
}

function closeEmailModal() {
    document.getElementById('emailModal').classList.remove('show');
    document.getElementById('bindEmailInput').value = '';
}

async function submitBindEmail(e) {
    e.preventDefault();
    const email = document.getElementById('bindEmailInput').value.trim();
    if (!email) {
        showToast('请输入邮箱地址', 'error');
        return;
    }

    const res = await api('/api/user/bind-email', {
        method: 'POST',
        body: JSON.stringify({ email })
    });

    if (res.success) {
        state.currentUser = res.user;
        closeEmailModal();
        showToast('邮箱绑定成功！', 'success');
    } else {
        showToast(res.message, 'error');
    }
}

// ============ 忘记密码 ============

function showForgotPassword() {
    closeAuthModal();
    document.getElementById('forgotModal').classList.add('show');
}

function closeForgotModal() {
    document.getElementById('forgotModal').classList.remove('show');
    document.getElementById('forgotEmailInput').value = '';
}

async function submitForgotPassword(e) {
    e.preventDefault();
    const email = document.getElementById('forgotEmailInput').value.trim();
    if (!email) {
        showToast('请输入邮箱地址', 'error');
        return;
    }

    const res = await api('/api/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ email })
    });

    if (res.success) {
        closeForgotModal();
        showToast('重置链接已发送到你的邮箱，请查收', 'success');
    } else {
        showToast(res.message, 'error');
    }
}

// ============ 重置密码 ============

let resetToken = '';

function showResetModal(token) {
    resetToken = token;
    document.getElementById('resetModal').classList.add('show');
}

function closeResetModal() {
    document.getElementById('resetModal').classList.remove('show');
    document.getElementById('resetPasswordInput').value = '';
    document.getElementById('resetPasswordConfirm').value = '';
    resetToken = '';
}

async function submitResetPassword(e) {
    e.preventDefault();
    const password = document.getElementById('resetPasswordInput').value.trim();
    const confirm = document.getElementById('resetPasswordConfirm').value.trim();

    if (password.length < 4) {
        showToast('密码至少4个字符', 'error');
        return;
    }
    if (password !== confirm) {
        showToast('两次输入的密码不一致', 'error');
        return;
    }

    const res = await api('/api/reset-password', {
        method: 'POST',
        body: JSON.stringify({ token: resetToken, password })
    });

    if (res.success) {
        closeResetModal();
        showToast('密码重置成功，请使用新密码登录', 'success');
        // 清除 URL 中的 token
        window.location.hash = '';
        // 自动弹出登录框
        setTimeout(() => showAuthModal('login'), 500);
    } else {
        showToast(res.message, 'error');
    }
}

// 检查 URL 中是否有重置密码 token
function checkResetToken() {
    const hash = window.location.hash;
    if (hash.startsWith('#/reset-password?token=')) {
        const token = hash.replace('#/reset-password?token=', '');
        if (token) {
            // 先验证 token 是否有效
            api('/api/verify-reset-token', {
                method: 'POST',
                body: JSON.stringify({ token })
            }).then(res => {
                if (res.success) {
                    showResetModal(token);
                } else {
                    showToast(res.message || '重置链接无效', 'error');
                    window.location.hash = '';
                }
            });
        }
    }
}

// ============ 标签和统计 ============
async function loadTags() {
    const res = await api('/api/tags');
    if (res.success) {
        const container = document.getElementById('tagsContainer');
        if (res.tags.length > 0) {
            container.innerHTML = res.tags.slice(0, 15).map(t =>
                `<button class="tag-item" onclick="filterByTag('${t.name}')">${t.name} (${t.count})</button>`
            ).join('');
        } else {
            container.innerHTML = '<span style="color:var(--text-light);font-size:0.85rem">暂无标签</span>';
        }
    }
}

async function loadStats() {
    const res = await api('/api/stats');
    if (res.success) {
        document.getElementById('statsContainer').innerHTML = `
            <div class="stat-item"><span class="stat-label">帖子数</span><span class="stat-value">${res.stats.posts}</span></div>
            <div class="stat-item"><span class="stat-label">用户数</span><span class="stat-value">${res.stats.users}</span></div>
            <div class="stat-item"><span class="stat-label">评论数</span><span class="stat-value">${res.stats.comments}</span></div>`;

        document.getElementById('heroStats').innerHTML = `
            <div class="hero-stat"><span class="number">${res.stats.posts}</span><span class="label">帖子</span></div>
            <div class="hero-stat"><span class="number">${res.stats.users}</span><span class="label">用户</span></div>
            <div class="hero-stat"><span class="number">${res.stats.comments}</span><span class="label">评论</span></div>`;
    }
}

// ============ 图片查看器 ============
function openImageViewer(src) {
    document.getElementById('viewerImage').src = src;
    document.getElementById('imageViewer').classList.add('show');
}

function closeImageViewer() {
    document.getElementById('imageViewer').classList.remove('show');
}

// ============ 工具函数 ============
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============ 拖拽上传支持 ============
['imageUploadArea', 'videoUploadArea'].forEach(id => {
    const area = document.getElementById(id);
    if (!area) return;

    area.addEventListener('dragover', (e) => {
        e.preventDefault();
        area.style.borderColor = 'var(--primary)';
        area.style.background = 'var(--primary-light)';
    });

    area.addEventListener('dragleave', () => {
        area.style.borderColor = '';
        area.style.background = '';
    });

    area.addEventListener('drop', (e) => {
        e.preventDefault();
        area.style.borderColor = '';
        area.style.background = '';

        const inputId = id === 'imageUploadArea' ? 'imageInput' : 'videoInput';
        const input = document.getElementById(inputId);
        input.files = e.dataTransfer.files;
        input.dispatchEvent(new Event('change'));
    });
});

// ============ 初始化 ============
document.addEventListener('DOMContentLoaded', async () => {
    checkResetToken();
    await checkLogin();
    await loadPosts();
    await loadTags();
    await loadStats();
});
