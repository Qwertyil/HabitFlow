const formValidators = new WeakMap();

function getFormErrorTarget(form) {
    return form.querySelector("[data-form-feedback]") || form;
}

function getSubmitButton(form) {
    return form.querySelector('button[type="submit"]');
}

function clearFormErrors(form) {
    form.querySelectorAll(".form-error").forEach((error) => error.remove());
}

function clearFieldErrors(form) {
    form.querySelectorAll(".field-error").forEach((error) => error.remove());
    form
        .querySelectorAll(".error")
        .forEach((element) => element.classList.remove("error"));
}

function revealFormIssue(target) {
    if (!target) {
        return;
    }

    target.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
    });

    if (typeof target.focus === "function") {
        target.focus({ preventScroll: true });
    }
}

function findErrorContainer(target) {
    if (!target) {
        return null;
    }

    if (
        target.matches(
            ".form-group, .schedule-config-block, .selection-grid, .form-inline-grid"
        )
    ) {
        return target;
    }

    return (
        target.closest(
            ".form-group, .schedule-config-block, .selection-grid, .form-inline-grid"
        ) || target.parentElement
    );
}

function showInlineError(target, message) {
    const container = findErrorContainer(target);
    if (!container) {
        return null;
    }

    container.querySelectorAll(".field-error").forEach((error) => error.remove());
    const error = document.createElement("div");
    error.className = "field-error";
    error.textContent = message;
    container.appendChild(error);

    if (typeof target.classList?.add === "function") {
        target.classList.add("error");
    }

    return error;
}

function showFormError(message, options = {}) {
    const form = options.form || document.querySelector(".item-form");
    if (!form) {
        return null;
    }

    clearFormErrors(form);

    const errorElement = document.createElement("div");
    errorElement.className = "form-error";
    errorElement.textContent = message;

    getFormErrorTarget(form).appendChild(errorElement);

    if (options.reveal !== false) {
        revealFormIssue(options.revealTarget || errorElement);
    }

    return errorElement;
}

function setFormLoading(form, isLoading) {
    const submitButton = getSubmitButton(form);
    if (!submitButton) {
        return;
    }
    submitButton.classList.toggle("btn-loading", Boolean(isLoading));
    submitButton.disabled = Boolean(isLoading);
}

function registerFormValidator(form, validator) {
    if (!form || typeof validator !== "function") {
        return;
    }

    const registered = formValidators.get(form) || [];
    registered.push(validator);
    formValidators.set(form, registered);
}

function validateField(field) {
    const wrapper = findErrorContainer(field);
    wrapper?.querySelectorAll(".field-error").forEach((error) => error.remove());
    field.classList.remove("error");

    if (field.hasAttribute("required") && !field.value.trim()) {
        showInlineError(field, "Заполните обязательное поле.");
        return false;
    }

    if (field.type === "email" && field.value && !field.validity.valid) {
        showInlineError(field, "Введите корректный email.");
        return false;
    }

    return true;
}

function runRequiredValidation(form) {
    let isValid = true;
    let firstInvalidField = null;

    form.querySelectorAll("[required]").forEach((field) => {
        if (!validateField(field)) {
            isValid = false;
            firstInvalidField ||= field;
        }
    }); 

    return {
        isValid,
        firstInvalidField,
    };
}

function runCustomValidators(form) {
    const validators = formValidators.get(form) || [];

    for (const validator of validators) {
        const result = validator({ form });
        if (!result || result.isValid !== false) {
            continue;
        }

        if (result.target) {
            showInlineError(result.target, result.message);
        }

        showFormError(result.message, {
            form,
            revealTarget: result.target || getFormErrorTarget(form),
        });

        return result;
    }

    return { isValid: true };
}

function buildPutRedirectPath() {
    const currentPath = window.location.pathname;
    if (currentPath.startsWith("/tasks")) {
        return "/tasks";
    }
    if (currentPath.startsWith("/habits")) {
        return "/habits";
    }
    return "/themes";
}

async function submitPutForm(form) {
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());

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
        let message = "Не удалось сохранить изменения.";

        try {
            const payloadJson = await response.json();
            message =
                payloadJson?.error?.message ||
                payloadJson?.detail ||
                message;
        } catch (error) {
            console.error("Unable to parse PUT error response", error);
        }

        throw new Error(message);
    }

    window.HabitFlowUI.showNotification("Изменения сохранены", "success");
    await window.HabitFlowUI.navigate(buildPutRedirectPath());
}

function initGenericForms(root = document) {
    root.querySelectorAll(".item-form").forEach((form) => {
        if (form.dataset.boundSubmitPipeline === "1") {
            return;
        }
        form.dataset.boundSubmitPipeline = "1";

        form.querySelectorAll("input, select, textarea").forEach((field) => {
            field.addEventListener("blur", () => validateField(field));
            field.addEventListener("input", () => {
                if (field.classList.contains("error")) {
                    validateField(field);
                }
            });
        });

        form.addEventListener("submit", async (event) => {
            const method = (
                form.dataset.method ||
                form.getAttribute("method") ||
                "post"
            ).toLowerCase();
            const submitButton = getSubmitButton(form);

            if (submitButton?.disabled || submitButton?.classList.contains("btn-loading")) {
                event.preventDefault();
                return;
            }

            clearFormErrors(form);
            clearFieldErrors(form);

            const validation = runRequiredValidation(form);
            if (!validation.isValid) {
                event.preventDefault();
                showFormError("Пожалуйста, проверьте обязательные поля.", {
                    form,
                    revealTarget: validation.firstInvalidField || getFormErrorTarget(form),
                });
                return;
            }

            const customValidation = runCustomValidators(form);
            if (customValidation.isValid === false) {
                event.preventDefault();
                return;
            }

            if (method === "put") {
                event.preventDefault();
                setFormLoading(form, true);

                try {
                    await submitPutForm(form);
                } catch (error) {
                    console.error(error);
                    setFormLoading(form, false);
                    showFormError(
                        error instanceof Error
                            ? error.message
                            : "Не удалось сохранить изменения.",
                        {
                            form,
                            revealTarget: getFormErrorTarget(form),
                        }
                    );
                }
                return;
            }

            setFormLoading(form, true);
        });
    });
}

window.validateForm = (form) => runRequiredValidation(form).isValid;
window.showFormError = showFormError;
window.HabitFlowForms = window.HabitFlowForms || {};
window.HabitFlowForms.registerValidator = registerFormValidator;
window.HabitFlowForms.revealFormIssue = revealFormIssue;
window.HabitFlowForms.setFormLoading = setFormLoading;
window.HabitFlowForms.showFormError = showFormError;
window.HabitFlowUI.registerInit(initGenericForms);
