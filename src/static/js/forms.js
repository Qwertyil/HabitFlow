function showFormError(message) {
    const form = document.querySelector(".item-form");
    if (!form) {
        return;
    }

    form.querySelectorAll(".form-error").forEach((error) => error.remove());
    const errorElement = document.createElement("div");
    errorElement.className = "form-error";
    errorElement.textContent = message;
    form.prepend(errorElement);
}

function validateField(field) {
    const wrapper = field.closest(".form-group") || field.parentElement;
    wrapper?.querySelectorAll(".field-error").forEach((error) => error.remove());
    field.classList.remove("error");

    if (field.hasAttribute("required") && !field.value.trim()) {
        const error = document.createElement("div");
        error.className = "field-error";
        error.textContent = "Заполните обязательное поле.";
        wrapper?.appendChild(error);
        field.classList.add("error");
        return false;
    }

    if (field.type === "email" && field.value && !field.validity.valid) {
        const error = document.createElement("div");
        error.className = "field-error";
        error.textContent = "Введите корректный email.";
        wrapper?.appendChild(error);
        field.classList.add("error");
        return false;
    }

    return true;
}

function validateForm(form) {
    let isValid = true;
    form.querySelectorAll("[required]").forEach((field) => {
        if (!validateField(field)) {
            isValid = false;
        }
    });
    return isValid;
}

function initGenericForms(root = document) {
    root.querySelectorAll(".item-form").forEach((form) => {
        if (form.dataset.boundValidation === "1") {
            return;
        }
        form.dataset.boundValidation = "1";

        form.querySelectorAll("input, select, textarea").forEach((field) => {
            field.addEventListener("blur", () => validateField(field));
            field.addEventListener("input", () => {
                if (field.classList.contains("error")) {
                    validateField(field);
                }
            });
        });

        form.addEventListener("submit", (event) => {
            const method = (
                form.dataset.method ||
                form.getAttribute("method") ||
                "post"
            ).toLowerCase();

            if (!validateForm(form)) {
                event.preventDefault();
                showFormError("Пожалуйста, проверьте обязательные поля.");
                return;
            }

            if (method !== "put") {
                form.querySelector('button[type="submit"]')?.classList.add("btn-loading");
            }
        });
    });
}

window.validateForm = validateForm;
window.showFormError = showFormError;
window.HabitFlowUI.registerInit(initGenericForms);
