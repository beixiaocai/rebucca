/*
 * 作者：北小菜
 * 官网：https://www.yuturuishi.com
 * 微信：bilibili_bxc
 * 哔哩哔哩主页：https://space.bilibili.com/487906612
 * gitee地址：https://gitee.com/Vanishi/rebucca
 * github地址：https://github.com/beixiaocai/rebucca
 */

/* ==========================================================================
   rebucca Admin · 新版 UI 核心 JS
   ========================================================================== */

/* ---------- 多语言翻译函数 ---------- */
function _t(key, defaultVal) {
    if (typeof T !== 'undefined' && T && T[key]) {
        return T[key];
    }
    return defaultVal || key;
}

/* ---------- CSRF ---------- */
function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
}

function csrfHeaders(extra) {
    var h = extra || {};
    var t = getCsrfToken();
    if (t) h['X-CSRFToken'] = t;
    return h;
}

/* ---------- API 请求封装 ---------- */
const Api = {
    get: function(url, params) {
        if (params) {
            const qs = new URLSearchParams(params).toString();
            url = url + (url.includes('?') ? '&' : '?') + qs;
        }
        return fetch(url, { method: 'GET', credentials: 'same-origin' })
            .then(r => r.json())
            .catch(e => { console.error('API GET error:', url, e); return { code: 0, msg: 'network error' }; });
    },
    post: function(url, data) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: csrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(data || {})
        })
        .then(r => r.json())
        .catch(e => { console.error('API POST error:', url, e); return { code: 0, msg: 'network error' }; });
    },
    postForm: function(url, formData) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: csrfHeaders(),
            body: formData
        })
        .then(r => r.json())
        .catch(e => { console.error('API POST FORM error:', url, e); return { code: 0, msg: 'network error' }; });
    }
};

/* ---------- Toast 提示 ---------- */
function showToast(msg, type, duration) {
    type = type || 'info';
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const icons = { success: '✓', error: '✕', warning: '!', info: 'i' };
    const toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.innerHTML = '<span class="toast-icon">' + (icons[type] || icons.info) + '</span><span class="toast-msg">' + escapeHtml(msg) + '</span>';
    container.appendChild(toast);
    setTimeout(function() {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'all .25s ease';
        setTimeout(function() { toast.remove(); }, 250);
    }, duration || 3000);
}

/* ---------- HTML 转义 ---------- */
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/* ---------- 确认对话框 ---------- */
function confirmDialog(msg, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay show';
    overlay.style.zIndex = '400';
    overlay.innerHTML =
        '<div class="modal" style="max-width:400px">' +
        '  <div class="modal-header"><span class="modal-title">' + _t('confirm_title','确认') + '</span></div>' +
        '  <div class="modal-body"><p style="font-size:14px;color:var(--c-text-secondary)">' + escapeHtml(msg) + '</p></div>' +
        '  <div class="modal-footer">' +
        '    <button class="btn" id="cd_cancel">' + _t('cancel','取消') + '</button>' +
        '    <button class="btn btn-primary" id="cd_ok">' + _t('confirm','确定') + '</button>' +
        '  </div>' +
        '</div>';
    document.body.appendChild(overlay);
    overlay.querySelector('#cd_cancel').onclick = function() { overlay.remove(); };
    overlay.querySelector('#cd_ok').onclick = function() { overlay.remove(); if (onConfirm) onConfirm(); };
    overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };
}

/* ---------- 通用弹窗控制 ---------- */
function openModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.add('show');
}
function closeModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.remove('show');
}

/* ---------- 折叠区域 ---------- */
function toggleCollapse(headerEl) {
    const body = headerEl.nextElementSibling;
    headerEl.classList.toggle('expanded');
    body.classList.toggle('show');
}

/* ---------- 标签页切换 ---------- */
function switchTab(tabId, tabGroup) {
    document.querySelectorAll('[data-tab-group="' + tabGroup + '"] .tab-item').forEach(function(t) {
        t.classList.remove('active');
    });
    document.querySelectorAll('[data-tab-group="' + tabGroup + '"] .tab-pane').forEach(function(p) {
        p.classList.remove('show');
    });
    document.querySelector('[data-tab="' + tabId + '"]').classList.add('active');
    document.getElementById(tabId).classList.add('show');
}

/* ---------- 语言切换 ---------- */
function switchLang(lang) {
    Api.get('/index/openSwitchLang', { lang: lang }).then(function(res) {
        if (res.code === 1000) {
            location.reload();
        }
    });
}

/* ---------- 下拉菜单控制 ---------- */
document.addEventListener('click', function(e) {
    // 点击外部关闭下拉
    if (!e.target.closest('.lang-switch')) {
        document.querySelectorAll('.lang-switch-dropdown').forEach(function(d) { d.classList.remove('show'); });
    }
    if (!e.target.closest('.user-menu')) {
        document.querySelectorAll('.user-dropdown').forEach(function(d) { d.classList.remove('show'); });
    }
});

function toggleDropdown(selector) {
    const el = document.querySelector(selector);
    if (el) el.classList.toggle('show');
}

/* ---------- 分页渲染 ---------- */
function renderPagination(container, pageData, onPageChange) {
    if (!container || !pageData) return;
    const page = pageData.page || 1;
    const pageNum = pageData.page_num || 1;
    const count = pageData.count || 0;

    let html = '';
    const labels = pageData.pageLabels || [];

    if (labels.length > 0) {
        // 使用后端提供的完整页码标签（含首页/上一页/页码/下一页/尾页）
        labels.forEach(function(l) {
            var isActive = l.cur === 1 || l.page === page;
            html += '<span class="page-item ' + (isActive ? 'active' : '') + '" data-page="' + l.page + '">' + escapeHtml(String(l.name)) + '</span>';
        });
    } else {
        // 后端未提供 labels 时自行生成
        html += '<span class="page-item ' + (page <= 1 ? 'disabled' : '') + '" data-page="' + (page - 1) + '">&lt;</span>';
        let start = Math.max(1, page - 2);
        let end = Math.min(pageNum, page + 2);
        for (let i = start; i <= end; i++) {
            html += '<span class="page-item ' + (i === page ? 'active' : '') + '" data-page="' + i + '">' + i + '</span>';
        }
        html += '<span class="page-item ' + (page >= pageNum ? 'disabled' : '') + '" data-page="' + (page + 1) + '">&gt;</span>';
    }

    html += '<span class="page-info">' + _t('camera_total','共') + ' ' + count + ' ' + _t('camera_item_unit','条') + '</span>';

    container.innerHTML = html;
    container.querySelectorAll('.page-item:not(.disabled)').forEach(function(item) {
        item.onclick = function() {
            const p = parseInt(this.getAttribute('data-page'));
            if (p && p !== page && onPageChange) onPageChange(p);
        };
    });
}

/* ---------- 协议类型映射 ---------- */
function getPullStreamTypeName(type) {
    const types = { 1: 'RTSP', 2: 'RTMP', 3: 'FLV', 4: 'HLS', 21: 'GB28181', 31: 'cRTSP', 32: 'cRTMP' };
    return types[type] || 'Unknown';
}

/* ---------- 状态文本 ---------- */
function getForwardStateText(state) {
    return state === 1 ? _t('camera_forwarding', '转发中') : _t('camera_not_forwarding', '未转发');
}

/* ---------- 复制到剪贴板 ---------- */
function copyToClipboard(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function() {
            showToast(_t('player_copied', '已复制'), 'success');
        }).catch(function() {
            fallbackCopy(text);
        });
    } else {
        fallbackCopy(text);
    }
}
function fallbackCopy(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); showToast(_t('player_copied', '已复制'), 'success'); }
    catch(e) { showToast(_t('player_copy_fail', '复制失败'), 'error'); }
    ta.remove();
}

/* ---------- 格式化时间 ---------- */
function formatTime(seconds) {
    if (!seconds || seconds <= 0) return '0s';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return h + 'h ' + m + 'm ' + s + 's';
    if (m > 0) return m + 'm ' + s + 's';
    return s + 's';
}

/* ---------- 加载状态 ---------- */
function showLoading(container, msg) {
    if (!container) return;
    container.innerHTML =
        '<div class="empty-state">' +
        '  <div class="empty-icon">⟳</div>' +
        '  <div class="empty-text">' + (msg || _t('index_loading', '加载中...')) + '</div>' +
        '</div>';
}

/* ---------- 空状态 ---------- */
function showEmpty(container, msg) {
    if (!container) return;
    container.innerHTML =
        '<div class="empty-state">' +
        '  <div class="empty-icon">○</div>' +
        '  <div class="empty-text">' + (msg || _t('camera_no_data', '暂无数据')) + '</div>' +
        '</div>';
}

/* ---------- 侧边栏折叠 / 展开 ---------- */
var SIDEBAR_STORAGE_KEY = 'rebucca_sidebar_expanded';

function isSidebarExpanded() {
    return document.documentElement.classList.contains('sidebar-expanded');
}

function setSidebarExpanded(expanded, persist) {
    var root = document.documentElement;
    root.classList.toggle('sidebar-expanded', expanded);
    root.classList.toggle('sidebar-collapsed', !expanded);
    var btn = document.getElementById('sidebarToggle');
    if (btn) {
        var expandLabel = btn.getAttribute('data-expand-label') || _t('sidebar_expand', '展开侧边栏');
        var collapseLabel = btn.getAttribute('data-collapse-label') || _t('sidebar_collapse', '收起侧边栏');
        btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        btn.setAttribute('aria-label', expanded ? collapseLabel : expandLabel);
        btn.title = expanded ? collapseLabel : expandLabel;
    }
    syncSidebarNavTitles(expanded);
    if (persist !== false) {
        try {
            localStorage.setItem(SIDEBAR_STORAGE_KEY, expanded ? '1' : '0');
        } catch (e) {}
    }
}

function syncSidebarNavTitles(expanded) {
    var collapsed = expanded === undefined ? !isSidebarExpanded() : !expanded;
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(function(el) {
        var tip = el.getAttribute('data-nav-title') || el.getAttribute('title') || '';
        if (!el.getAttribute('data-nav-title') && tip) {
            el.setAttribute('data-nav-title', tip);
        }
        tip = el.getAttribute('data-nav-title') || '';
        if (collapsed && tip) {
            el.setAttribute('title', tip);
        } else {
            el.removeAttribute('title');
        }
    });
}

function toggleSidebar() {
    setSidebarExpanded(!isSidebarExpanded());
}

function initSidebarToggle() {
    var btn = document.getElementById('sidebarToggle');
    if (!btn) return;
    btn.setAttribute('data-expand-label', btn.getAttribute('title') || _t('sidebar_expand', '展开侧边栏'));
    btn.setAttribute('data-collapse-label', _t('sidebar_collapse', '收起侧边栏'));
    document.querySelectorAll('.sidebar-nav .nav-item[title]').forEach(function(el) {
        if (!el.getAttribute('data-nav-title')) {
            el.setAttribute('data-nav-title', el.getAttribute('title'));
        }
    });
    setSidebarExpanded(isSidebarExpanded(), false);
    btn.addEventListener('click', toggleSidebar);
}

/* ---------- 侧边栏折叠组 ---------- */
function toggleNavGroup(btn) {
    var group = btn && btn.closest ? btn.closest('.nav-group-collapsible') : null;
    if (!group) return;
    var open = group.classList.toggle('open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function initNavGroups() {
    document.querySelectorAll('.nav-group-collapsible').forEach(function(group) {
        var btn = group.querySelector('.nav-group-toggle');
        if (group.querySelector('.nav-sub-item.active')) {
            group.classList.add('open');
            if (btn) btn.setAttribute('aria-expanded', 'true');
        }
    });
}

/* ---------- 移动端侧边栏抽屉 ---------- */
function isMobileView() {
    return window.matchMedia('(max-width: 768px)').matches;
}

function openMobileSidebar() {
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebarOverlay');
    if (sidebar) sidebar.classList.add('show');
    if (overlay) overlay.classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeMobileSidebar() {
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebarOverlay');
    if (sidebar) sidebar.classList.remove('show');
    if (overlay) overlay.classList.remove('show');
    document.body.style.overflow = '';
}

function toggleMobileSidebar() {
    var sidebar = document.getElementById('sidebar');
    if (sidebar && sidebar.classList.contains('show')) {
        closeMobileSidebar();
    } else {
        openMobileSidebar();
    }
}

function initMobileSidebar() {
    var btn = document.getElementById('sidebarMobileToggle');
    var overlay = document.getElementById('sidebarOverlay');
    if (btn) btn.addEventListener('click', toggleMobileSidebar);
    if (overlay) overlay.addEventListener('click', closeMobileSidebar);
    // 点击导航项后自动关闭（手机端体验）
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(function(item) {
        item.addEventListener('click', function() {
            if (isMobileView()) closeMobileSidebar();
        });
    });
    // 窗口尺寸变化时，回到桌面端清理手机端状态
    window.addEventListener('resize', function() {
        if (!isMobileView()) closeMobileSidebar();
    });
}

document.addEventListener('DOMContentLoaded', function() {
    initNavGroups();
    initSidebarToggle();
    initMobileSidebar();
});
