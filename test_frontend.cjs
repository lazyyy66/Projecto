// Проверки логики фронтенда без браузера и сторонних зависимостей.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, 'frontend/script.js'), 'utf8');

function setup(fetch) {
    const nodes = new Map();
    const document = {
        querySelector(selector) {
            if (!nodes.has(selector)) {
                nodes.set(selector, {
                    style: {}, textContent: '', innerHTML: '', value: '',
                    classList: { add() {}, remove() {} }, reset() {},
                    querySelectorAll: () => [],
                });
            }
            return nodes.get(selector);
        },
    };
    const context = vm.createContext({ document, fetch, URLSearchParams, Date });
    vm.runInContext(script, context);
    return { context, nodes, run: code => vm.runInContext(code, context) };
}

const response = (data, ok = true, status = 200) => ({
    ok, status, json: async () => data,
});

test('Ошибки валидации выводятся читаемым текстом', async () => {
    const app = setup(async () => response({
        detail: [{ loc: ['body', 'username'], msg: 'Too long' }],
    }, false, 422));
    await assert.rejects(app.run("api('/auth/register')"), /username: Too long/);
});

test('Изменение задачи обновляет список с текущими фильтрами и сохраняет форму', async () => {
    const calls = [];
    const app = setup(async (url, options) => {
        calls.push({ url, method: options.method });
        return response(options.method === 'PATCH' ? { id: 1, status: 'done' } : []);
    });
    app.run(`
        state.selectedProjectId = 10;
        state.tasks = [{ id: 1, status: 'not done' }];
        state.filters.status = 'not done';
        state.filters.priority = 'high';
        renderTaskList = () => {};
        renderProjectContent = () => { throw new Error('Form was rebuilt'); };
    `);
    await app.run("updateTask(1, { status: 'done' })");
    assert.equal(calls[0].method, 'PATCH');
    assert.equal(calls[1].url, 'http://127.0.0.1:8000/projects/10/tasks?status=not+done&priority=high');
    assert.equal(app.run('state.tasks.length'), 0);
});

test('Поздний ответ предыдущего проекта не заменяет задачи текущего', async () => {
    const pending = [];
    const app = setup(() => new Promise(resolve => pending.push(resolve)));
    app.run('renderTaskList = () => {}; state.selectedProjectId = 1;');
    const oldRequest = app.run('loadTasks()');
    app.run('state.selectedProjectId = 2;');
    const newRequest = app.run('loadTasks()');
    pending[1](response([{ id: 20, project_id: 2 }]));
    await newRequest;
    pending[0](response([{ id: 10, project_id: 1 }]));
    await oldRequest;
    assert.equal(app.run('state.tasks[0].project_id'), 2);
});

test('При быстрой смене фильтра применяется только последний ответ', async () => {
    const pending = [];
    const app = setup(() => new Promise(resolve => pending.push(resolve)));
    app.run('renderTaskList = () => {}; state.selectedProjectId = 1;');
    const first = app.run('loadTasks()');
    app.run("state.filters.status = 'done';");
    const second = app.run('loadTasks()');
    pending[1](response([{ id: 2, status: 'done' }]));
    await second;
    pending[0](response([{ id: 1, status: 'not done' }]));
    await first;
    assert.equal(app.run('state.tasks[0].status'), 'done');
});

test('Выход очищает фильтры и отклоняет незавершённую загрузку', async () => {
    let finishLoading;
    const app = setup(url => url.endsWith('/auth/logout')
        ? Promise.resolve(response({ success: true }))
        : new Promise(resolve => { finishLoading = resolve; }));
    app.run(`
        renderProjects = () => {};
        renderProjectContent = () => {};
        renderTaskList = () => {};
        state.token = 'test-token';
        state.selectedProjectId = 1;
        state.filters.status = 'done';
    `);
    const pending = app.run('loadTasks()');
    await app.run('handleLogout()');
    finishLoading(response([{ id: 1 }]));
    await pending;
    assert.equal(app.run('state.token'), null);
    assert.equal(app.run('state.selectedProjectId'), null);
    assert.equal(app.run('state.tasks.length'), 0);
    assert.equal(app.run('state.filters.status'), '');
});

test('Дата дедлайна не смещается на предыдущий день из-за часового пояса', () => {
    const previousTimezone = process.env.TZ;
    try {
        process.env.TZ = 'America/Los_Angeles';
        const app = setup();
        assert.equal(app.run("formatDate('2026-08-01T00:00:00Z')"), '01.08.2026');
    } finally {
        if (previousTimezone === undefined) delete process.env.TZ;
        else process.env.TZ = previousTimezone;
    }
});
