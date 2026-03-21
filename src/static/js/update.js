function initPutForms(root = document) {
    root.querySelectorAll(".item-form").forEach((form) => {
        const method = (
            form.dataset.method ||
            form.getAttribute("method") ||
            "post"
        ).toLowerCase();
        if (method !== "put" || form.dataset.boundPut === "1") {
            return;
        }
        form.dataset.boundPut = "1";

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (typeof validateForm === "function" && !validateForm(form)) {
                showFormError("Пожалуйста, проверьте обязательные поля.");
                return;
            }

            const formData = new FormData(form);
            const payload = Object.fromEntries(formData.entries());

            try {
                const response = await fetch(form.action, {
                    method: "PUT",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": window.HabitFlowUI.getCsrfToken(),
                    },
                    body: JSON.stringify(payload),
                    credentials: "same-origin",
                });

                if (!response.ok) {
                    throw new Error("Update failed");
                }

                window.HabitFlowUI.showNotification("Изменения сохранены", "success");
                const currentPath = window.location.pathname;
                if (currentPath.startsWith("/tasks")) {
                    await window.HabitFlowUI.navigate("/tasks");
                } else if (currentPath.startsWith("/habits")) {
                    await window.HabitFlowUI.navigate("/habits");
                } else {
                    await window.HabitFlowUI.navigate("/themes");
                }
            } catch (error) {
                console.error(error);
                showFormError("Не удалось сохранить изменения.");
            }
        });
    });
}

window.HabitFlowUI.registerInit(initPutForms);
