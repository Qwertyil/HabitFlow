function initThemeDelete(root = document) {
    root.querySelectorAll(".btn-theme-delete").forEach((button) => {
        if (button.dataset.boundDelete === "1") {
            return;
        }
        button.dataset.boundDelete = "1";
        button.addEventListener("click", async () => {
            const themeId = button.dataset.themeId;
            if (
                !themeId ||
                !window.confirm(
                    'Удалить эту тему? Все связанные задачи и привычки останутся, но станут "Без темы".'
                )
            ) {
                return;
            }
            button.disabled = true;

            try {
                const response = await fetch(`/themes/${themeId}`, {
                    method: "DELETE",
                    headers: {
                        "X-CSRFToken": window.HabitFlowUI.getCsrfToken(),
                    },
                    credentials: "same-origin",
                });

                if (response.status !== 204) {
                    throw new Error("Theme delete failed");
                }

                window.HabitFlowUI.showNotification("Тема удалена", "success");
                await window.HabitFlowUI.navigate(window.location.href, {
                    replace: true,
                    preserveScroll: true,
                });
            } catch (error) {
                console.error(error);
                window.HabitFlowUI.showNotification("Не удалось удалить тему", "error");
                button.disabled = false;
            }
        });
    });
}

window.HabitFlowUI.registerInit(initThemeDelete);
