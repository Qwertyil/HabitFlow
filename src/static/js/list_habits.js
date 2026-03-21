function initHabitFiltersAndDelete(root = document) {
    const form = root.querySelector("#habits-filters-form");
    const statusFilter = root.querySelector("#habit-status-filter");
    const scheduleFilter = root.querySelector("#habit-schedule-filter");
    const sortSelect = root.querySelector("#sort-habits");
    const orderInput = root.querySelector("#habits-order-input");
    const sortAscBtn = root.querySelector("#habit-sort-asc");
    const sortDescBtn = root.querySelector("#habit-sort-desc");

    if (form && statusFilter && scheduleFilter && sortSelect && orderInput && sortAscBtn && sortDescBtn) {
        if (form.dataset.boundFilters !== "1") {
            form.dataset.boundFilters = "1";
            const submitFilters = async () => {
                const params = new URLSearchParams(window.location.search);
                params.set("status", statusFilter.value);
                params.set("schedule_type", scheduleFilter.value);
                params.set("sort", sortSelect.value);
                params.set("order", orderInput.value);
                params.delete("page");
                await window.HabitFlowUI.navigate(`${window.location.pathname}?${params.toString()}`);
            };

            statusFilter.addEventListener("change", submitFilters);
            scheduleFilter.addEventListener("change", submitFilters);
            sortSelect.addEventListener("change", submitFilters);

            [sortAscBtn, sortDescBtn].forEach((button) => {
                button.addEventListener("click", async () => {
                    orderInput.value = button.dataset.order || "desc";
                    sortAscBtn.classList.toggle("active", orderInput.value === "asc");
                    sortDescBtn.classList.toggle("active", orderInput.value === "desc");
                    await submitFilters();
                });
            });
        }
    }

    root.querySelectorAll(".btn-habit-delete").forEach((button) => {
        if (button.dataset.boundDelete === "1") {
            return;
        }
        button.dataset.boundDelete = "1";
        button.addEventListener("click", async () => {
            const habitId = button.dataset.habitId;
            if (!habitId || !window.confirm("Удалить эту привычку?")) {
                return;
            }
            button.disabled = true;

            try {
                const response = await fetch(`/habits/${habitId}`, {
                    method: "DELETE",
                    headers: {
                        "X-CSRFToken": window.HabitFlowUI.getCsrfToken(),
                    },
                    credentials: "same-origin",
                });

                if (response.status !== 204) {
                    throw new Error("Habit delete failed");
                }

                window.HabitFlowUI.showNotification("Привычка удалена", "success");
                await window.HabitFlowUI.navigate(window.location.href, {
                    replace: true,
                    preserveScroll: true,
                });
            } catch (error) {
                console.error(error);
                window.HabitFlowUI.showNotification("Не удалось удалить привычку", "error");
                button.disabled = false;
            }
        });
    });
}

window.HabitFlowUI.registerInit(initHabitFiltersAndDelete);
