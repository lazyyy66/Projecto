// ---------- Настройка ----------
// Если бэкенд запущен на другом порту/адресе — поменяй строку ниже.
const API_BASE = 'http://127.0.0.1:8000';

// ---------- Состояние (только в памяти — обновишь страницу, придётся войти заново) ----------
const state = {
    token: null,
    userEmail: null,
    projects: [],
    selectedProjectId: null,
    tasks: [],
    filters: { status: '', priority: '' },
};

const $ = (sel) => document.querySelector(sel);

// ---------- Обёртка над fetch ----------
async function api(path, { method = 'GET', body, auth = true } = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (auth && state.token) headers['Authorization'] = `Bearer ${state.token}`;

    const response = await fetch(API_BASE + path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    let data = null;
    try { data = await response.json(); } catch (e) { /* пустой ответ */ }

    if (!response.ok) {
        const message = (data && data.detail) ? data.detail : `Ошибка ${response.status}`;
        throw new Error(message);
    }
    return data;
}

function showError(target, message) {
    target.textContent = message;
    target.style.display = 'block';
}
function clearError(target) {
    target.style.display = 'none';
    target.textContent = '';
}

function withErrorHandling(bannerEl, fn) {
    return async (...args) => {
        try {
            clearError(bannerEl);
            await fn(...args);
        } catch (err) {
            showError(bannerEl, err.message);
        }
    };
}

// ---------- Авторизация ----------
async function handleRegister(username, email, password) {
    await api('/auth/register', { method: 'POST', auth: false, body: { username, email, password } });
    await handleLogin(email, password);
}

async function handleLogin(email, password) {
    const data = await api('/auth/login', { method: 'POST', auth: false, body: { email, password } });
    state.token = data.access_token;
    state.userEmail = email;
    showAppScreen();
    await loadProjects();
}

async function handleLogout() {
    try { await api('/auth/logout', { method: 'POST' }); } catch (e) { /* токен уже мог истечь — не страшно */ }
    state.token = null;
    state.userEmail = null;
    state.projects = [];
    state.tasks = [];
    state.selectedProjectId = null;
    showAuthScreen();
}

function showAppScreen() {
    $('#auth-screen').style.display = 'none';
    $('#app-screen').style.display = 'block';
    $('#user-info').style.display = 'flex';
    $('#user-email').textContent = state.userEmail;
}

function showAuthScreen() {
    $('#app-screen').style.display = 'none';
    $('#auth-screen').style.display = 'block';
    $('#user-info').style.display = 'none';
    $('#login-form').reset();
    $('#register-form').reset();
}

// ---------- Проекты ----------
async function loadProjects() {
    state.projects = await api('/projects');
    renderProjects();
    renderProjectContent();
}

async function createProject(name, description) {
    const project = await api('/projects', { method: 'POST', body: { name, description } });
    state.projects.push(project);
    $('#new-project-form').reset();
    renderProjects();
}

async function deleteProject(id) {
    if (!confirm('Удалить проект вместе со всеми его задачами?')) return;
    await api(`/projects/${id}`, { method: 'DELETE' });
    state.projects = state.projects.filter(p => p.id !== id);
    if (state.selectedProjectId === id) {
        state.selectedProjectId = null;
        state.tasks = [];
    }
    renderProjects();
    renderProjectContent();
}

async function renameProject(id) {
    const project = state.projects.find(p => p.id === id);
    const newName = prompt('Новое название проекта:', project.name);
    if (newName === null || newName.trim() === '') return;
    const updated = await api(`/projects/${id}`, { method: 'PATCH', body: { name: newName } });
    state.projects = state.projects.map(p => p.id === id ? updated : p);
    renderProjects();
    renderProjectContent();
}

async function selectProject(id) {
    state.selectedProjectId = id;
    renderProjects();
    await loadTasks();
}

// ---------- Таски ----------
async function loadTasks() {
    if (!state.selectedProjectId) { state.tasks = []; renderProjectContent(); return; }
    const params = new URLSearchParams();
    if (state.filters.status) params.set('status', state.filters.status);
    if (state.filters.priority) params.set('priority', state.filters.priority);
    const query = params.toString() ? `?${params}` : '';
    state.tasks = await api(`/projects/${state.selectedProjectId}/tasks${query}`);
    renderProjectContent();
}

async function createTask(payload) {
    const task = await api(`/projects/${state.selectedProjectId}/tasks`, { method: 'POST', body: payload });
    await loadTasks();
}

async function updateTask(id, patch) {
    const updated = await api(`/tasks/${id}`, { method: 'PATCH', body: patch });
    state.tasks = state.tasks.map(t => t.id === id ? updated : t);
    renderProjectContent();
}

async function deleteTask(id) {
    if (!confirm('Удалить задачу?')) return;
    await api(`/tasks/${id}`, { method: 'DELETE' });
    state.tasks = state.tasks.filter(t => t.id !== id);
    renderProjectContent();
}

// ---------- Рендер ----------
function renderProjects() {
    const list = $('#project-list');
    if (state.projects.length === 0) {
        list.innerHTML = `<div class="empty-state">Пока нет проектов</div>`;
        return;
    }
    list.innerHTML = state.projects.map(p => `
<div class="project-item ${p.id === state.selectedProjectId ? 'selected' : ''}" data-id="${p.id}">
<span class="name" data-action="select">${escapeHtml(p.name)}</span>
<span>
    <button class="danger-text" data-action="rename" title="Переименовать">✎</button>
    <button class="danger-text" data-action="delete" title="Удалить">✕</button>
</span>
</div>
`).join('');

    list.querySelectorAll('.project-item').forEach(el => {
        const id = Number(el.dataset.id);
        el.querySelector('[data-action="select"]').onclick = withErrorHandling($('#app-error-banner'), () => selectProject(id));
        el.querySelector('[data-action="rename"]').onclick = withErrorHandling($('#app-error-banner'), () => renameProject(id));
        el.querySelector('[data-action="delete"]').onclick = withErrorHandling($('#app-error-banner'), () => deleteProject(id));
    });
}

function renderProjectContent() {
    const container = $('#project-content');
    if (!state.selectedProjectId) {
        container.innerHTML = `<div class="empty-state">Выбери проект слева или создай новый</div>`;
        return;
    }
    const project = state.projects.find(p => p.id === state.selectedProjectId);

    container.innerHTML = `
<div id="project-header">
<h2>${escapeHtml(project.name)}</h2>
</div>
<p id="project-description">${escapeHtml(project.description)}</p>

<div id="filters">
<select id="filter-status">
    <option value="">Все статусы</option>
    <option value="not done">Не сделано</option>
    <option value="in process">В процессе</option>
    <option value="done">Сделано</option>
</select>
<select id="filter-priority">
    <option value="">Все приоритеты</option>
    <option value="low">Низкий</option>
    <option value="medium">Средний</option>
    <option value="high">Высокий</option>
</select>
</div>

<form id="new-task-form">
<label for="task-title">Название задачи</label>
<input type="text" id="task-title" required maxlength="100">
<label for="task-description">Описание</label>
<textarea id="task-description" rows="2" required maxlength="400"></textarea>
<div class="row">
    <div>
    <label for="task-due-date">Дедлайн</label>
    <input type="date" id="task-due-date" required>
    </div>
    <div>
    <label for="task-priority">Приоритет</label>
    <select id="task-priority">
        <option value="low">Низкий</option>
        <option value="medium" selected>Средний</option>
        <option value="high">Высокий</option>
    </select>
    </div>
</div>
<button type="submit" class="primary">Добавить задачу</button>
</form>

<div id="task-list"></div>
`;

    $('#filter-status').value = state.filters.status;
    $('#filter-priority').value = state.filters.priority;
    $('#filter-status').onchange = withErrorHandling($('#app-error-banner'), (e) => {
        state.filters.status = e.target.value;
        return loadTasks();
    });
    $('#filter-priority').onchange = withErrorHandling($('#app-error-banner'), (e) => {
        state.filters.priority = e.target.value;
        return loadTasks();
    });

    $('#new-task-form').onsubmit = withErrorHandling($('#app-error-banner'), async (e) => {
        e.preventDefault();
        const payload = {
            title: $('#task-title').value,
            description: $('#task-description').value,
            due_date: `${$('#task-due-date').value}T00:00:00`,
            priority: $('#task-priority').value,
        };
        await createTask(payload);
        e.target.reset();
        $('#task-priority').value = 'medium';
    });

    renderTaskList();
}

function renderTaskList() {
    const list = $('#task-list');
    if (!list) return;
    if (state.tasks.length === 0) {
        list.innerHTML = `<div class="empty-state">Задач пока нет — добавь первую выше</div>`;
        return;
    }

    const priorityColor = { high: 'var(--priority-high)', medium: 'var(--priority-medium)', low: 'var(--priority-low)' };

    list.innerHTML = state.tasks.map(t => `
<div class="task-card">
<div class="accent-bar" style="background:${priorityColor[t.priority]}"></div>
<div class="body">
    <div class="top-row">
    <div>
        <p class="title">${escapeHtml(t.title)}</p>
        <p class="description">${escapeHtml(t.description)}</p>
    </div>
    <button class="danger-text" data-action="delete" data-id="${t.id}">Удалить</button>
    </div>
    <div class="meta">
    <span class="due-date">до ${formatDate(t.due_date)}</span>
    <select data-action="status" data-id="${t.id}">
        <option value="not done" ${t.status === 'not done' ? 'selected' : ''}>Не сделано</option>
        <option value="in process" ${t.status === 'in process' ? 'selected' : ''}>В процессе</option>
        <option value="done" ${t.status === 'done' ? 'selected' : ''}>Сделано</option>
    </select>
    <select data-action="priority" data-id="${t.id}">
        <option value="low" ${t.priority === 'low' ? 'selected' : ''}>Низкий приоритет</option>
        <option value="medium" ${t.priority === 'medium' ? 'selected' : ''}>Средний приоритет</option>
        <option value="high" ${t.priority === 'high' ? 'selected' : ''}>Высокий приоритет</option>
    </select>
    </div>
</div>
</div>
`).join('');

    list.querySelectorAll('[data-action="delete"]').forEach(el => {
        el.onclick = withErrorHandling($('#app-error-banner'), () => deleteTask(Number(el.dataset.id)));
    });
    list.querySelectorAll('[data-action="status"]').forEach(el => {
        el.onchange = withErrorHandling($('#app-error-banner'), () => updateTask(Number(el.dataset.id), { status: el.value }));
    });
    list.querySelectorAll('[data-action="priority"]').forEach(el => {
        el.onchange = withErrorHandling($('#app-error-banner'), () => updateTask(Number(el.dataset.id), { priority: el.value }));
    });
}

// ---------- Утилиты ----------
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str ?? '';
    return div.innerHTML;
}
function formatDate(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString('ru-RU');
}

// ---------- Инициализация ----------
const authError = $('#error-banner');

$('#tab-login').onclick = () => {
    $('#tab-login').classList.add('active');
    $('#tab-register').classList.remove('active');
    $('#login-form').classList.add('active');
    $('#register-form').classList.remove('active');
    clearError(authError);
};
$('#tab-register').onclick = () => {
    $('#tab-register').classList.add('active');
    $('#tab-login').classList.remove('active');
    $('#register-form').classList.add('active');
    $('#login-form').classList.remove('active');
    clearError(authError);
};

$('#login-form').onsubmit = withErrorHandling(authError, async (e) => {
    e.preventDefault();
    await handleLogin($('#login-email').value, $('#login-password').value);
});

$('#register-form').onsubmit = withErrorHandling(authError, async (e) => {
    e.preventDefault();
    await handleRegister($('#register-username').value, $('#register-email').value, $('#register-password').value);
});

$('#logout-btn').onclick = withErrorHandling($('#app-error-banner'), handleLogout);

$('#new-project-form').onsubmit = withErrorHandling($('#app-error-banner'), async (e) => {
    e.preventDefault();
    await createProject($('#new-project-name').value, $('#new-project-description').value);
});

renderProjectContent();