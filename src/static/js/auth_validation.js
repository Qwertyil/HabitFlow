function initAuthForms(root = document) {
    root.querySelectorAll(".auth-form").forEach((form) => {
        if (form.dataset.boundAuth === "1") {
            return;
        }
        form.dataset.boundAuth = "1";

        const authCard = form.closest(".auth-card");
        const clientError = authCard?.querySelector("[data-auth-client-error]");
        const serverError = authCard?.querySelector("[data-auth-server-error]");
        const clientErrorText = authCard?.querySelector("[data-auth-client-error-text]");
        const emailInput = form.querySelector('input[name="email"]');
        const passwordInput = form.querySelector('input[name="password"]');

        const setError = (message) => {
            if (!clientError || !clientErrorText) {
                return;
            }
            clientErrorText.textContent = message;
            clientError.hidden = false;
            if (serverError) {
                serverError.hidden = true;
            }
        };

        const clearError = () => {
            if (!clientError || !clientErrorText) {
                return;
            }
            clientErrorText.textContent = "";
            clientError.hidden = true;
        };

        form.querySelectorAll("[data-password-toggle]").forEach((button) => {
            button.addEventListener("click", () => {
                const targetId = button.dataset.passwordToggle;
                const input = targetId ? form.querySelector(`#${targetId}`) : null;
                if (!(input instanceof HTMLInputElement)) {
                    return;
                }
                const isPassword = input.type === "password";
                input.type = isPassword ? "text" : "password";
                const icon = button.querySelector("i");
                if (icon) {
                    icon.className = isPassword
                        ? "fa-regular fa-eye-slash"
                        : "fa-regular fa-eye";
                }
            });
        });

        form.addEventListener("submit", (event) => {
            clearError();

            if (emailInput && !emailInput.value.trim()) {
                event.preventDefault();
                setError("Введите email.");
                return;
            }

            if (emailInput && !emailInput.validity.valid) {
                event.preventDefault();
                setError("Введите корректный email.");
                return;
            }

            if (passwordInput && passwordInput.value.length < 8) {
                event.preventDefault();
                setError("Пароль должен быть длиной от 8 до 256 символов.");
            }
        });
    });
}

window.HabitFlowUI.registerInit(initAuthForms);
