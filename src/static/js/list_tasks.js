document.addEventListener('DOMContentLoaded', () => {
    const statusFilter = document.getElementById('status-filter');
    const sortSelect = document.getElementById('sort-tasks');
    const sortAscBtn = document.getElementById('sort-asc');
    const sortDescBtn = document.getElementById('sort-desc');
    const paginationContainer = document.getElementById('tasks-pagination');

    if (!statusFilter || !sortSelect || !sortAscBtn || !sortDescBtn) {
        return;
    }

    // Initial UI state должен приходить с сервера (из шаблона).
    // Поэтому здесь мы не переустанавливаем значения select'ов и не переключаем active-классы —
    // только читаем текущее состояние из DOM.
    let currentOrder = 'desc';
    if (sortAscBtn.classList.contains('active')) {
        currentOrder = 'asc';
    } else if (sortDescBtn.classList.contains('active')) {
        currentOrder = 'desc';
    }

    function setOrderButtons(order) {
        sortAscBtn.classList.toggle('active', order === 'asc');
        sortDescBtn.classList.toggle('active', order === 'desc');
    }

    function buildTasksUrl() {
        const nextParams = new URLSearchParams(window.location.search);
        nextParams.set('status', statusFilter.value);
        nextParams.set('sort', sortSelect.value);
        nextParams.set('order', currentOrder);
        nextParams.delete('page');
        const query = nextParams.toString();
        return query ? `${window.location.pathname}?${query}` : window.location.pathname;
    }

    function submitFilters() {
        const nextUrl = buildTasksUrl();
        const currentUrl = `${window.location.pathname}${window.location.search}`;
        if (nextUrl !== currentUrl) {
            window.location.assign(nextUrl);
        }
    }

    function syncThemeLinks() {
        const filterParams = new URLSearchParams(window.location.search);
        const keysToKeep = ['status', 'sort', 'order', 'per_page'];
        const themeLinks = document.querySelectorAll('.theme-filter-link');

        themeLinks.forEach((link) => {
            const linkUrl = new URL(link.getAttribute('href'), window.location.href);
            keysToKeep.forEach((key) => {
                if (filterParams.has(key)) {
                    linkUrl.searchParams.set(key, filterParams.get(key));
                }
            });
            linkUrl.searchParams.delete('page');
            const nextHref = `${linkUrl.pathname}?${linkUrl.searchParams.toString()}`;
            link.setAttribute('href', nextHref);
        });
    }

    function parsePositiveInt(value, fallback) {
        const parsed = Number.parseInt(value, 10);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
    }

    function buildUrlWithPage(page) {
        const params = new URLSearchParams(window.location.search);
        if (page <= 1) {
            params.delete('page');
        } else {
            params.set('page', String(page));
        }
        const query = params.toString();
        return query ? `${window.location.pathname}?${query}` : window.location.pathname;
    }

    function createPageControl({ label, href, disabled = false, active = false }) {
        const element = document.createElement(disabled || active ? 'span' : 'a');
        element.className = 'btn btn-outline btn-sm tasks-page-btn';
        element.textContent = label;

        if (active) {
            element.classList.add('active');
            element.setAttribute('aria-current', 'page');
        }

        if (disabled) {
            element.classList.add('disabled');
            element.setAttribute('aria-disabled', 'true');
        }

        if (!disabled && !active && href) {
            element.href = href;
        }

        return element;
    }

    function renderPagination() {
        if (!paginationContainer) {
            return;
        }

        const params = new URLSearchParams(window.location.search);
        const currentPage = parsePositiveInt(params.get('page'), 1);
        const perPage = parsePositiveInt(params.get('per_page'), 20);
        const filteredTotal = parsePositiveInt(
            paginationContainer.dataset.tasksCount,
            0
        );

        const totalPages =
            filteredTotal > 0 ? Math.ceil(filteredTotal / perPage) : 0;

        const hasPrev = currentPage > 1;
        const hasNext = totalPages > 0 && currentPage < totalPages;

        if (!hasPrev && !hasNext) {
            paginationContainer.innerHTML = '';
            return;
        }

        paginationContainer.innerHTML = '';

        const controls = document.createElement('div');
        controls.className = 'tasks-pagination-controls';

        controls.appendChild(
            createPageControl({
                label: 'Назад',
                href: buildUrlWithPage(currentPage - 1),
                disabled: !hasPrev,
            })
        );

        if (hasPrev) {
            controls.appendChild(
                createPageControl({
                    label: String(currentPage - 1),
                    href: buildUrlWithPage(currentPage - 1),
                })
            );
        }

        controls.appendChild(
            createPageControl({
                label: String(currentPage),
                active: true,
            })
        );

        if (hasNext) {
            controls.appendChild(
                createPageControl({
                    label: String(currentPage + 1),
                    href: buildUrlWithPage(currentPage + 1),
                })
            );
        }

        controls.appendChild(
            createPageControl({
                label: 'Вперёд',
                href: buildUrlWithPage(currentPage + 1),
                disabled: !hasNext,
            })
        );

        const info = document.createElement('div');
        info.className = 'tasks-pagination-info';
        info.textContent =
            totalPages > 0
                ? `Страница ${currentPage} из ${totalPages}`
                : `Страница ${currentPage}`;

        paginationContainer.appendChild(controls);
        paginationContainer.appendChild(info);
    }

    syncThemeLinks();

    statusFilter.addEventListener('change', submitFilters);
    sortSelect.addEventListener('change', submitFilters);

    sortAscBtn.addEventListener('click', () => {
        if (currentOrder === 'asc') return;
        currentOrder = 'asc';
        setOrderButtons(currentOrder);
        submitFilters();
    });

    sortDescBtn.addEventListener('click', () => {
        if (currentOrder === 'desc') return;
        currentOrder = 'desc';
        setOrderButtons(currentOrder);
        submitFilters();
    });
});
