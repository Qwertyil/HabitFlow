document.addEventListener('DOMContentLoaded', function() {
    const authForms = document.querySelectorAll('.auth-form');

    authForms.forEach((form) => {
        const errorBox = document.querySelector('[data-auth-client-error]');
        if (!errorBox) {
            return;
        }

        const authCard = form.closest('.auth-card');
        const serverErrorBox = authCard?.querySelector('[data-auth-server-error]');

        const emailInput = form.querySelector('input[name="email"]');
        const passwordInput = form.querySelector('input[name="password"]');
        const errorTextEl = errorBox.querySelector('[data-auth-client-error-text]');

        function showError(message) {
            if (errorTextEl) {
                errorTextEl.textContent = message;
            }
            errorBox.hidden = false;
            if (serverErrorBox) {
                serverErrorBox.hidden = true;
            }
        }

        function clearError() {
            if (errorTextEl) {
                errorTextEl.textContent = '';
            }
            errorBox.hidden = true;
        }

        function getEmailMessage() {
            if (!emailInput) {
                return null;
            }

            const value = emailInput.value.trim();
            if (!value) {
                return 'Введите email.';
            }

            // Используем встроенную проверку формата email (type="email")
            if (emailInput.validity && (emailInput.validity.typeMismatch || emailInput.validity.badInput)) {
                return 'Введите корректный email.';
            }

            return null;
        }

        function getPasswordMessage() {
            if (!passwordInput) {
                return null;
            }

            const value = passwordInput.value || '';
            if (value.length < 8) {
                return 'Пароль должен быть длиной от 8 до 256 символов.';
            }

            return null;
        }

        // На старте всегда скрываем, чтобы не отображать пустую красную плашку.
        clearError();

        if (emailInput && passwordInput) {
            // Требование: если email валидный и пользователь переключился на пароль - ничего не показывать,
            // а если email невалидный - показать предупреждение про email.
            emailInput.addEventListener('blur', function() {
                window.setTimeout(function() {
                    if (document.activeElement === passwordInput) {
                        const emailMessage = getEmailMessage();
                        if (emailMessage) {
                            showError(emailMessage);
                        } else {
                            clearError();
                        }
                    }
                }, 0);
            });

            // Если пользователь уже на поле пароля и правит email - обновляем сообщение.
            emailInput.addEventListener('input', function() {
                if (document.activeElement === passwordInput) {
                    const emailMessage = getEmailMessage();
                    if (emailMessage) {
                        showError(emailMessage);
                    } else {
                        clearError();
                    }
                }
            });
        }

        // Требование: пароль проверяем ДО отправки формы и не трогаем backend, если он короче 8 символов.
        form.addEventListener('submit', function(event) {
            const passwordMessage = getPasswordMessage();
            if (passwordMessage) {
                event.preventDefault();
                passwordInput?.focus();
                showError(passwordMessage);
                return;
            }

            const emailMessage = getEmailMessage();
            if (emailMessage) {
                event.preventDefault();
                emailInput?.focus();
                showError(emailMessage);
                return;
            }

            // Клиентская валидация прошла: ошибки можно скрыть.
            clearError();
        });
    });
});
