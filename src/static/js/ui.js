(function() {
    const inits = [];

    function getTheme() {
        return localStorage.getItem("habitflow-ui-theme") === "dark"
            ? "dark"
            : "light";
    }

    function applyTheme(theme) {
        const nextTheme = theme === "dark" ? "dark" : "light";
        document.documentElement.setAttribute("data-ui-theme", nextTheme);
        localStorage.setItem("habitflow-ui-theme", nextTheme);

        document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
            const icon = button.querySelector("i");
            if (icon) {
                icon.className =
                    nextTheme === "dark"
                        ? "fa-solid fa-sun"
                        : "fa-solid fa-moon";
            }
            button.setAttribute(
                "aria-label",
                nextTheme === "dark" ? "Включить светлую тему" : "Включить темную тему"
            );
            button.setAttribute(
                "title",
                nextTheme === "dark" ? "Светлая тема" : "Темная тема"
            );
        });

        document.querySelectorAll("[data-theme-label]").forEach((label) => {
            label.textContent = nextTheme === "dark" ? "Тёмная" : "Светлая";
        });
    }

    function getCsrfToken() {
        return (
            document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") ||
            document.querySelector('input[name="csrf_token"]')?.value ||
            ""
        );
    }

    function ensureNotificationStack() {
        let stack = document.querySelector(".notification-stack");
        if (!stack) {
            stack = document.createElement("div");
            stack.className = "notification-stack";
            document.body.appendChild(stack);
        }
        return stack;
    }

    function showNotification(message, type = "info") {
        const stack = ensureNotificationStack();
        const notification = document.createElement("div");
        notification.className = `notification notification-${type}`;
        const iconName =
            type === "success"
                ? "fa-circle-check"
                : type === "error"
                  ? "fa-circle-exclamation"
                  : "fa-circle-info";
        notification.innerHTML = `
            <span class="notification-icon"><i class="fa-solid ${iconName}"></i></span>
            <span>${message}</span>
            <button type="button" class="notification-close" aria-label="Закрыть"><i class="fa-solid fa-xmark"></i></button>
        `;
        notification
            .querySelector(".notification-close")
            ?.addEventListener("click", () => notification.remove());
        stack.appendChild(notification);
        window.setTimeout(() => notification.remove(), 4200);
    }

    function confirmAction(options = {}) {
        const modal = document.getElementById("confirm-modal");
        if (!modal) {
            return Promise.resolve(window.confirm(options.message || "Подтвердите действие"));
        }

        const title = modal.querySelector("#confirm-modal-title");
        const message = modal.querySelector("#confirm-modal-message");
        const acceptButton = modal.querySelector("[data-confirm-accept]");
        const cancelButton = modal.querySelector("[data-confirm-cancel]");
        const backdrop = modal.querySelector("[data-confirm-close='backdrop']");
        const previousActive = document.activeElement;

        title.textContent = options.title || "Подтвердите действие";
        message.textContent = options.message || "Это действие нельзя отменить.";
        acceptButton.textContent = options.confirmText || "Подтвердить";
        cancelButton.textContent = options.cancelText || "Отмена";

        acceptButton.classList.toggle("btn-danger", options.variant !== "primary");
        acceptButton.classList.toggle("btn-primary", options.variant === "primary");

        modal.hidden = false;

        return new Promise((resolve) => {
            let settled = false;

            function cleanup(result) {
                if (settled) {
                    return;
                }
                settled = true;
                modal.hidden = true;
                acceptButton.removeEventListener("click", onAccept);
                cancelButton.removeEventListener("click", onCancel);
                backdrop?.removeEventListener("click", onCancel);
                document.removeEventListener("keydown", onKeyDown);
                previousActive?.focus?.({ preventScroll: true });
                resolve(result);
            }

            function onAccept() {
                cleanup(true);
            }

            function onCancel() {
                cleanup(false);
            }

            function onKeyDown(event) {
                if (event.key === "Escape") {
                    event.preventDefault();
                    cleanup(false);
                }
            }

            acceptButton.addEventListener("click", onAccept);
            cancelButton.addEventListener("click", onCancel);
            backdrop?.addEventListener("click", onCancel);
            document.addEventListener("keydown", onKeyDown);
            window.setTimeout(() => acceptButton.focus(), 0);
        });
    }

    async function navigate(url, options = {}) {
        const targetUrl = new URL(url, window.location.origin);
        const currentScroll = window.scrollY;

        try {
            const response = await fetch(targetUrl.toString(), {
                headers: {
                    Accept: "text/html",
                    "X-Requested-With": "fetch",
                },
                credentials: "same-origin",
            });

            if (!response.ok) {
                window.location.assign(targetUrl.toString());
                return;
            }

            const html = await response.text();
            const parser = new DOMParser();
            const nextDoc = parser.parseFromString(html, "text/html");
            const nextNavbar = nextDoc.getElementById("app-navbar");
            const nextMain = nextDoc.getElementById("app-shell-main");

            if (!nextNavbar || !nextMain) {
                window.location.assign(targetUrl.toString());
                return;
            }

            document.title = nextDoc.title;
            document.body.dataset.page = nextDoc.body.dataset.page || "app";
            document.getElementById("app-navbar")?.replaceWith(nextNavbar);
            document.getElementById("app-shell-main")?.replaceWith(nextMain);

            if (options.replace) {
                window.history.replaceState({}, "", targetUrl.toString());
            } else if (!options.fromPopState) {
                window.history.pushState({}, "", targetUrl.toString());
            }

            if (options.preserveScroll) {
                window.scrollTo({ top: currentScroll });
            } else {
                window.scrollTo({ top: 0 });
            }

            runPageInits(document);
        } catch (error) {
            console.error("Navigation failed", error);
            window.location.assign(targetUrl.toString());
        }
    }

    function registerInit(initFn) {
        inits.push(initFn);
    }

    function initStatsTabs(root) {
        const page = root.querySelector(".stats-page");
        if (!page) {
            return;
        }

        const buttons = Array.from(page.querySelectorAll("[data-stats-target]"));
        const panels = Array.from(page.querySelectorAll("[data-stats-panel]"));
        const rangeLinks = Array.from(page.querySelectorAll(".stats-range-link"));
        if (!buttons.length || !panels.length) {
            return;
        }

        const allowed = new Set(
            panels
                .map((panel) => panel.dataset.statsPanel)
                .filter(Boolean)
        );

        function syncRangeLinks(target) {
            if (!rangeLinks.length) {
                return;
            }

            const nextTarget = allowed.has(target) ? target : "overview";

            rangeLinks.forEach((link) => {
                const url = new URL(link.href, window.location.origin);
                url.hash = `stats-${nextTarget}`;
                link.href = `${url.pathname}${url.search}${url.hash}`;
            });
        }

        function setActive(target, updateHash = false) {
            const nextTarget = allowed.has(target) ? target : "overview";

            buttons.forEach((button) => {
                const isActive = button.dataset.statsTarget === nextTarget;
                button.classList.toggle("active", isActive);
                button.setAttribute("aria-selected", isActive ? "true" : "false");
            });

            panels.forEach((panel) => {
                panel.hidden = panel.dataset.statsPanel !== nextTarget;
            });

            page.dataset.statsTabsReady = "true";
            syncRangeLinks(nextTarget);

            if (updateHash) {
                const url = new URL(window.location.href);
                url.hash = `stats-${nextTarget}`;
                window.history.replaceState({}, "", url.toString());
            }
        }

        const hashTarget = window.location.hash.startsWith("#stats-")
            ? window.location.hash.slice(7)
            : "overview";

        setActive(hashTarget, false);

        buttons.forEach((button) => {
            button.addEventListener("click", () => {
                setActive(button.dataset.statsTarget, true);
            });
        });
    }

    function runPageInits(root) {
        applyTheme(getTheme());
        inits.forEach((initFn) => {
            try {
                initFn(root);
            } catch (error) {
                console.error("Page init failed", error);
            }
        });
    }

    function isEnhancedLink(anchor) {
        if (!anchor || anchor.dataset.noEnhance === "true") {
            return false;
        }
        if (anchor.target || anchor.hasAttribute("download")) {
            return false;
        }
        const href = anchor.getAttribute("href") || "";
        if (!href || href.startsWith("#") || href.startsWith("javascript:")) {
            return false;
        }
        const url = new URL(href, window.location.origin);
        if (url.pathname === "/auth/google/start") {
            return false;
        }
        return url.origin === window.location.origin;
    }

    document.addEventListener("click", (event) => {
        const themeToggle = event.target.closest("[data-theme-toggle]");
        if (themeToggle) {
            event.preventDefault();
            applyTheme(getTheme() === "dark" ? "light" : "dark");
            return;
        }

        const anchor = event.target.closest("a[href]");
        if (!isEnhancedLink(anchor)) {
            return;
        }

        if (
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey ||
            event.button !== 0
        ) {
            return;
        }

        event.preventDefault();
        navigate(anchor.href);
    });

    window.addEventListener("popstate", () => {
        navigate(window.location.href, {
            replace: true,
            fromPopState: true,
            preserveScroll: true,
        });
    });

    window.HabitFlowUI = {
        applyTheme,
        confirmAction,
        getCsrfToken,
        initStatsTabs,
        navigate,
        registerInit,
        runPageInits,
        showNotification,
    };

    registerInit(initStatsTabs);

    document.addEventListener("DOMContentLoaded", () => {
        applyTheme(getTheme());
        runPageInits(document);
    });
})();
