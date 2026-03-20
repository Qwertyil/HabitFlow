document.addEventListener('DOMContentLoaded', () => {
    const statusFilter = document.getElementById('habit-status-filter');
    const scheduleFilter = document.getElementById('habit-schedule-filter');
    const sortSelect = document.getElementById('sort-habits');
    const sortAscBtn = document.getElementById('habit-sort-asc');
    const sortDescBtn = document.getElementById('habit-sort-desc');
    const paginationContainer = document.getElementById('habits-pagination');

    if (!statusFilter || !scheduleFilter || !sortSelect || !sortAscBtn || !sortDescBtn) {
        bindDeleteButtons();
        return;
    }

    // Initial UI state должен приходить с сервера (из шаблона).
    // Поэтому здесь мы не переустанавливаем values select'ов и не переключаем active-классы —
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

    function buildHabitsUrl() {
        const next = new URLSearchParams(window.location.search);
        next.set('status', statusFilter.value);
        next.set('schedule_type', scheduleFilter.value);
        next.set('sort', sortSelect.value);
        next.set('order', currentOrder);
        next.delete('page');
        const query = next.toString();
        return query ? `${window.location.pathname}?${query}` : window.location.pathname;
    }

    function submitFilters() {
        const nextUrl = buildHabitsUrl();
        const currentUrl = `${window.location.pathname}${window.location.search}`;
        if (nextUrl !== currentUrl) {
            window.location.assign(nextUrl);
        }
    }

    function syncThemeLinks() {
        const filterParams = new URLSearchParams(window.location.search);
        const keysToKeep = ['status', 'schedule_type', 'sort', 'order', 'per_page'];
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
        const nextParams = new URLSearchParams(window.location.search);
        if (page <= 1) {
            nextParams.delete('page');
        } else {
            nextParams.set('page', String(page));
        }
        const query = nextParams.toString();
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

        const currentParams = new URLSearchParams(window.location.search);
        const currentPage = parsePositiveInt(currentParams.get('page'), 1);
        const perPage = parsePositiveInt(currentParams.get('per_page'), 20);
        const filteredTotal = parsePositiveInt(paginationContainer.dataset.habitsCount, 0);

        const totalPages = filteredTotal > 0 ? Math.ceil(filteredTotal / perPage) : 0;
        const hasPrev = currentPage > 1;
        const hasNext = totalPages > 0 && currentPage < totalPages;

        if (!hasPrev && !hasNext) {
            paginationContainer.innerHTML = '';
            return;
        }

        paginationContainer.innerHTML = '';
        const controls = document.createElement('div');
        controls.className = 'tasks-pagination-controls';

        controls.appendChild(createPageControl({
            label: 'Назад',
            href: buildUrlWithPage(currentPage - 1),
            disabled: !hasPrev,
        }));

        if (hasPrev) {
            controls.appendChild(createPageControl({
                label: String(currentPage - 1),
                href: buildUrlWithPage(currentPage - 1),
            }));
        }

        controls.appendChild(createPageControl({
            label: String(currentPage),
            active: true,
        }));

        if (hasNext) {
            controls.appendChild(createPageControl({
                label: String(currentPage + 1),
                href: buildUrlWithPage(currentPage + 1),
            }));
        }

        controls.appendChild(createPageControl({
            label: 'Вперёд',
            href: buildUrlWithPage(currentPage + 1),
            disabled: !hasNext,
        }));

        const info = document.createElement('div');
        info.className = 'tasks-pagination-info';
        info.textContent = totalPages > 0
            ? `Страница ${currentPage} из ${totalPages}`
            : `Страница ${currentPage}`;

        paginationContainer.appendChild(controls);
        paginationContainer.appendChild(info);
    }

    syncThemeLinks();
    bindDeleteButtons();

    statusFilter.addEventListener('change', submitFilters);
    scheduleFilter.addEventListener('change', submitFilters);
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

function bindDeleteButtons() {
    const deleteButtons = document.querySelectorAll('.btn-habit-delete[data-habit-id]');
    deleteButtons.forEach((button) => {
        if (button.dataset.boundDelete === '1') {
            return;
        }
        button.dataset.boundDelete = '1';
        button.addEventListener('click', async () => {
            const habitId = button.dataset.habitId;
            if (!habitId) {
                return;
            }
            await deleteHabit(habitId, button);
        });
    });
}

function parseNonNegativeInt(value, fallback = 0) {
    return window.habitFlowUtils.parseNonNegativeInt(value, fallback);
}

function decrementCounterValue(elementId, delta = 1) {
    if (delta <= 0) {
        return 0;
    }

    const element = document.getElementById(elementId);
    if (!element) {
        return 0;
    }

    const currentValue = parseNonNegativeInt(element.textContent, 0);
    const nextValue = Math.max(0, currentValue - delta);
    element.textContent = String(nextValue);
    return currentValue - nextValue;
}

function detectHabitStateForDeletion(habitCard) {
    if (!habitCard) {
        return {
            isArchived: false,
            isCompletedToday: false,
            isDueToday: false,
        };
    }

    const isArchived = habitCard.classList.contains('is-archived');
    const isCompletedToday = habitCard.classList.contains('is-completed');
    const completeButton = habitCard.querySelector('.btn-habit-complete');
    const isDueToday = isCompletedToday
        || (!isArchived && Boolean(completeButton) && !completeButton.disabled);

    return {
        isArchived,
        isCompletedToday,
        isDueToday,
    };
}

function updateHabitStatsAfterDelete(habitCard) {
    const { isArchived, isCompletedToday, isDueToday } = detectHabitStateForDeletion(habitCard);

    decrementCounterValue('stat-total-habits', 1);
    if (!isArchived) {
        decrementCounterValue('stat-active-habits', 1);
    }
    if (isDueToday) {
        decrementCounterValue('stat-due-habits-today', 1);
    }

    const successElement = document.getElementById('stat-success-rate');
    if (!successElement) {
        return;
    }

    const dueFromDataset = parseNonNegativeInt(successElement.dataset.dueHabitsToday, 0);
    const completedFromDataset = parseNonNegativeInt(successElement.dataset.completedHabitsToday, 0);
    const nextDue = Math.max(0, dueFromDataset - (isDueToday ? 1 : 0));
    const nextCompleted = Math.max(
        0,
        Math.min(
            nextDue,
            completedFromDataset - (isCompletedToday ? 1 : 0)
        )
    );

    successElement.dataset.dueHabitsToday = String(nextDue);
    successElement.dataset.completedHabitsToday = String(nextCompleted);

    if (typeof initializeHabitStatsState === 'function') {
        initializeHabitStatsState();
        return;
    }

    const successRate = nextDue > 0 ? Math.round((nextCompleted / nextDue) * 100) : 0;
    successElement.textContent = `${successRate}%`;
}

async function deleteHabit(habitId, button) {
    if (!window.confirm('Удалить эту привычку?')) {
        return;
    }

    const habitCard = button.closest('.habit-card');
    try {
        const response = await fetch(`/habits/${habitId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            }
        });

        if (response.status === 204) {
            updateHabitStatsAfterDelete(habitCard);
            if (habitCard) {
                habitCard.remove();
            }
            if (typeof showNotification === 'function') {
                showNotification('Привычка удалена', 'success');
            }
        } else if (typeof showNotification === 'function') {
            showNotification('Ошибка при удалении привычки', 'error');
        }
    } catch (error) {
        console.error('Error deleting habit:', error);
        if (typeof showNotification === 'function') {
            showNotification('Ошибка соединения с сервером', 'error');
        }
    }
}
