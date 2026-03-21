function initTaskFilters(root = document) {
    const form = root.querySelector("#tasks-filters-form");
    const statusFilter = root.querySelector("#status-filter");
    const sortSelect = root.querySelector("#sort-tasks");
    const orderInput = root.querySelector("#tasks-order-input");
    const sortAscBtn = root.querySelector("#sort-asc");
    const sortDescBtn = root.querySelector("#sort-desc");

    if (!form || !statusFilter || !sortSelect || !orderInput || !sortAscBtn || !sortDescBtn) {
        return;
    }

    if (form.dataset.boundFilters === "1") {
        return;
    }
    form.dataset.boundFilters = "1";

    const submitFilters = async () => {
        const params = new URLSearchParams(window.location.search);
        params.set("status", statusFilter.value);
        params.set("sort", sortSelect.value);
        params.set("order", orderInput.value);
        params.delete("page");
        await window.HabitFlowUI.navigate(`${window.location.pathname}?${params.toString()}`);
    };

    statusFilter.addEventListener("change", submitFilters);
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

window.HabitFlowUI.registerInit(initTaskFilters);
