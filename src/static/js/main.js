function initMainPageInteractions(root = document) {
    root.querySelectorAll('.task-checkbox input[type="checkbox"]').forEach((checkbox) => {
        if (checkbox.dataset.boundToggle === "1") {
            return;
        }
        checkbox.dataset.boundToggle = "1";
        checkbox.addEventListener("change", async () => {
            const taskId = checkbox.dataset.taskId || checkbox.closest("[data-task-id]")?.dataset.taskId;
            if (!taskId) {
                return;
            }

            const endpoint = checkbox.checked
                ? `/tasks/${taskId}/complete`
                : `/tasks/${taskId}/incomplete`;
            checkbox.disabled = true;

            try {
                const response = await fetch(endpoint, {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": window.HabitFlowUI.getCsrfToken(),
                    },
                    credentials: "same-origin",
                });

                if (!response.ok) {
                    throw new Error("Task toggle failed");
                }

                window.HabitFlowUI.showNotification(
                    checkbox.checked ? "Задача выполнена" : "Задача возвращена в активные",
                    "success"
                );
                await window.HabitFlowUI.navigate(window.location.href, {
                    replace: true,
                    preserveScroll: true,
                });
            } catch (error) {
                console.error(error);
                checkbox.checked = !checkbox.checked;
                window.HabitFlowUI.showNotification("Не удалось обновить задачу", "error");
                checkbox.disabled = false;
            }
        });
    });

    root.querySelectorAll(".btn-habit-complete").forEach((button) => {
        if (button.dataset.boundHabitComplete === "1" || button.disabled) {
            return;
        }
        button.dataset.boundHabitComplete = "1";
        button.addEventListener("click", async () => {
            const habitId = button.dataset.habitId;
            if (!habitId) {
                return;
            }
            button.disabled = true;

            try {
                const response = await fetch(`/habits/${habitId}/complete`, {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": window.HabitFlowUI.getCsrfToken(),
                    },
                    credentials: "same-origin",
                });

                if (!response.ok) {
                    throw new Error("Habit complete failed");
                }

                window.HabitFlowUI.showNotification("Привычка отмечена как выполненная", "success");
                await window.HabitFlowUI.navigate(window.location.href, {
                    replace: true,
                    preserveScroll: true,
                });
            } catch (error) {
                console.error(error);
                window.HabitFlowUI.showNotification("Не удалось обновить привычку", "error");
                button.disabled = false;
            }
        });
    });

    root.querySelectorAll(".btn-task-delete").forEach((button) => {
        if (button.dataset.boundDeleteTask === "1") {
            return;
        }
        button.dataset.boundDeleteTask = "1";
        button.addEventListener("click", async () => {
            const taskId = button.dataset.taskId;
            if (!taskId || !window.confirm("Удалить эту задачу?")) {
                return;
            }
            button.disabled = true;

            try {
                const response = await fetch(`/tasks/${taskId}`, {
                    method: "DELETE",
                    headers: {
                        "X-CSRFToken": window.HabitFlowUI.getCsrfToken(),
                    },
                    credentials: "same-origin",
                });
                if (response.status !== 204) {
                    throw new Error("Task delete failed");
                }
                window.HabitFlowUI.showNotification("Задача удалена", "success");
                await window.HabitFlowUI.navigate(window.location.href, {
                    replace: true,
                    preserveScroll: true,
                });
            } catch (error) {
                console.error(error);
                window.HabitFlowUI.showNotification("Не удалось удалить задачу", "error");
                button.disabled = false;
            }
        });
    });
}

window.HabitFlowUI.registerInit(initMainPageInteractions);
