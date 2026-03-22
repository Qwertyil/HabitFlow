function initHabitForm(root = document) {
    const form = root.querySelector(".item-form");
    const scheduleTypeSelect = root.querySelector("#schedule_type");
    const scheduleConfigInput = root.querySelector("#schedule_config");
    const periodInfiniteCheckbox = root.querySelector("#period-infinite");
    const endsOnInput = root.querySelector("#ends_on");
    const hint = root.querySelector("#scheduleHint");

    if (!form || !scheduleTypeSelect || !scheduleConfigInput) {
        return;
    }

    if (form.dataset.boundHabitForm === "1") {
        return;
    }
    form.dataset.boundHabitForm = "1";

    const hints = {
        daily: "Привычка выполняется каждый день.",
        weekly_days: "Выберите конкретные дни недели.",
        monthly_day: "Привычка срабатывает в выбранный день месяца.",
        yearly_date: "Привычка повторяется раз в год в конкретную дату.",
        interval_cycle: "Чередуйте активные дни и паузы.",
    };

    const blocks = {
        daily: root.querySelector("#schedule-config-daily"),
        weekly_days: root.querySelector("#schedule-config-weekly-days"),
        monthly_day: root.querySelector("#schedule-config-monthly-day"),
        yearly_date: root.querySelector("#schedule-config-yearly-date"),
        interval_cycle: root.querySelector("#schedule-config-interval-cycle"),
    };

    function toggleBlocks() {
        const currentValue = scheduleTypeSelect.value;
        Object.entries(blocks).forEach(([key, block]) => {
            if (!block) {
                return;
            }
            block.classList.toggle("is-visible", key === currentValue);
        });
        if (hint) {
            hint.textContent = hints[currentValue] || hints.daily;
        }
    }

    function togglePeriod() {
        if (!endsOnInput || !periodInfiniteCheckbox) {
            return;
        }
        endsOnInput.disabled = periodInfiniteCheckbox.checked;
        if (periodInfiniteCheckbox.checked) {
            endsOnInput.value = "";
        }
    }

    function buildScheduleConfig() {
        const currentValue = scheduleTypeSelect.value;
        if (currentValue === "daily") {
            return {};
        }
        if (currentValue === "weekly_days") {
            const days = Array.from(
                root.querySelectorAll('input[name="weekly_days"]:checked')
            ).map((input) => input.value);
            if (days.length === 0) {
                throw new Error('Для режима "По дням недели" выберите хотя бы один день.');
            }
            return { days };
        }
        if (currentValue === "monthly_day") {
            return { day: Number.parseInt(root.querySelector("#monthly_day")?.value || "0", 10) };
        }
        if (currentValue === "yearly_date") {
            return {
                month: Number.parseInt(root.querySelector("#yearly_month")?.value || "0", 10),
                day: Number.parseInt(root.querySelector("#yearly_day")?.value || "0", 10),
            };
        }
        return {
            active_days: Number.parseInt(root.querySelector("#interval_active_days")?.value || "0", 10),
            break_days: Number.parseInt(root.querySelector("#interval_break_days")?.value || "0", 10),
        };
    }

    function getScheduleErrorTarget() {
        const currentValue = scheduleTypeSelect.value;
        return blocks[currentValue] || scheduleTypeSelect;
    }

    function validatePeriod() {
        const startsOn = root.querySelector("#starts_on")?.value;
        const endsOn = root.querySelector("#ends_on")?.value;

        if (startsOn && endsOn && endsOn < startsOn) {
            return {
                isValid: false,
                message: "Дата конца периода не может быть раньше даты начала.",
                target: endsOnInput || scheduleTypeSelect,
            };
        }

        return { isValid: true };
    }

    toggleBlocks();
    togglePeriod();

    scheduleTypeSelect.addEventListener("change", toggleBlocks);
    periodInfiniteCheckbox?.addEventListener("change", togglePeriod);

    window.HabitFlowForms?.registerValidator(form, () => {
        try {
            const config = buildScheduleConfig();
            scheduleConfigInput.value = JSON.stringify(config);
        } catch (error) {
            return {
                isValid: false,
                message:
                    error instanceof Error
                        ? error.message
                        : "Проверьте параметры привычки.",
                target: getScheduleErrorTarget(),
            };
        }

        return validatePeriod();
    });
}

window.HabitFlowUI.registerInit(initHabitForm);
