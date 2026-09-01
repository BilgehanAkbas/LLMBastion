(() => {
    const input = document.getElementById("promptInput");
    const sendButton = document.getElementById("sendButton");
    const messages = document.getElementById("messages");
    const characterCount = document.getElementById("characterCount");

    if (!input || !sendButton || !messages) {
        return;
    }

    let sending = false;

    const createElement = (tag, className, text) => {
        const element = document.createElement(tag);
        if (className) {
            element.className = className;
        }
        if (text !== undefined && text !== null) {
            element.textContent = text;
        }
        return element;
    };

    const renderMarkdownSafely = (element, markdownText) => {
        if (
            typeof window.marked === "undefined"
            || typeof window.DOMPurify === "undefined"
        ) {
            element.textContent = markdownText;
            return;
        }

        const parsed = window.marked.parse(markdownText, {
            gfm: true,
            breaks: true,
        });

        element.innerHTML = window.DOMPurify.sanitize(parsed);

        element.querySelectorAll("a").forEach((link) => {
            link.target = "_blank";
            link.rel = "noopener noreferrer";
        });
    };

    const scrollToBottom = () => {
        messages.scrollTop = messages.scrollHeight;
    };

    const formatScore = (value) => {
        const number = Number(value);
        return Number.isFinite(number)
            ? number.toFixed(3)
            : "—";
    };

    const makeMessage = (role, text, options = {}) => {
        const wrapper = createElement(
            "div",
            `message ${role === "user" ? "user-message" : "assistant-message"}`
        );
        const avatar = createElement(
            "div",
            "message-avatar",
            role === "user" ? "YOU" : "LB"
        );
        const content = createElement("div", "message-content");
        const label = createElement(
            "div",
            "message-label",
            role === "user" ? "You" : "LLMBastion"
        );
        const bubble = createElement("div", "message-bubble");

        if (options.markdown && role === "assistant") {
            bubble.classList.add("markdown-body");
            renderMarkdownSafely(bubble, text);
        } else {
            bubble.textContent = text;
        }

        content.append(label, bubble);
        wrapper.append(avatar, content);
        messages.appendChild(wrapper);
        scrollToBottom();

        return {wrapper, content, bubble};
    };

    const addStat = (grid, label, value) => {
        const stat = createElement("div", "security-stat");
        stat.append(
            createElement("span", "", label),
            createElement("strong", "", value)
        );
        grid.appendChild(stat);
    };

    const addBadges = (card, values) => {
        if (!Array.isArray(values) || values.length === 0) {
            return;
        }

        const row = createElement("div", "badge-row");
        values.forEach((value) => {
            row.appendChild(
                createElement("span", "security-badge", value)
            );
        });
        card.appendChild(row);
    };

    const addDashboardLink = (card, requestId) => {
        if (!requestId) {
            return;
        }

        const link = createElement(
            "a",
            "security-link",
            "View request in Security Dashboard →"
        );
        link.href = `/dashboard/requests/${encodeURIComponent(requestId)}`;
        card.appendChild(link);
    };

    const makeSecurityCard = (data) => {
        const isBlocked = data.action === "BLOCK";
        const isRedacted = data.output_action === "REDACT";
        const cardClass = isBlocked
            ? "security-card blocked"
            : isRedacted
                ? "security-card redacted"
                : "security-card";

        const card = createElement("div", cardClass);
        const title = createElement("div", "security-title");

        const titleText = isBlocked
            ? "⚠ Request blocked by LLMBastion"
            : isRedacted
                ? "⚠ Response sanitized by DataGuard"
                : "✓ Security checks passed";

        title.append(
            createElement("span", "", titleText),
            createElement(
                "span",
                "action-badge",
                data.action || "UNKNOWN"
            )
        );
        card.appendChild(title);

        const grid = createElement("div", "security-grid");
        addStat(grid, "Risk", formatScore(data.risk_score));
        addStat(
            grid,
            "Semantic",
            formatScore(data.semantic_score)
        );
        addStat(
            grid,
            "Provider",
            isBlocked ? "SKIPPED" : "CALLED"
        );

        if (!isBlocked) {
            addStat(
                grid,
                "DataGuard",
                data.output_action || "PASS"
            );
            addStat(
                grid,
                "Redactions",
                String(data.output_redaction_count || 0)
            );
        }

        card.appendChild(grid);

        const detectorBadges = Array.isArray(data.triggered_detectors)
            ? data.triggered_detectors
            : [];
        addBadges(card, detectorBadges);

        if (isRedacted) {
            addBadges(card, data.output_findings || []);
        }

        addDashboardLink(card, data.request_id);
        return card;
    };

    const makeErrorCard = (message, retryAfter) => {
        const card = createElement("div", "security-card error");
        card.appendChild(
            createElement("div", "security-title", "Gateway request failed")
        );

        const detail = createElement("div", "", message);
        card.appendChild(detail);

        if (retryAfter) {
            const retry = createElement("div", "badge-row");
            retry.appendChild(
                createElement(
                    "span",
                    "security-badge",
                    `Retry after ${retryAfter}s`
                )
            );
            card.appendChild(retry);
        }

        return card;
    };

    const showLoading = () => {
        const message = makeMessage("assistant", "");
        message.bubble.textContent = "";

        const dots = createElement("div", "typing-dots");
        dots.append(
            createElement("span"),
            createElement("span"),
            createElement("span")
        );
        message.bubble.appendChild(dots);
        return message.wrapper;
    };

    const autoResize = () => {
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    };

    const updateComposer = () => {
        const length = input.value.length;
        characterCount.textContent = `${length} / 4000`;
        sendButton.disabled = sending || input.value.trim().length === 0;
        autoResize();
    };

    const submitPrompt = async () => {
        const prompt = input.value.trim();
        if (!prompt || sending) {
            return;
        }

        sending = true;
        makeMessage("user", prompt);

        input.value = "";
        updateComposer();

        const loading = showLoading();

        try {
            const response = await fetch("/api/v1/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({message: prompt}),
            });

            let payload = {};
            try {
                payload = await response.json();
            } catch (_) {
                payload = {};
            }

            loading.remove();

            if (!response.ok) {
                const assistant = makeMessage(
                    "assistant",
                    response.status === 429
                        ? "The gateway rate limit was reached."
                        : "The gateway could not complete this request."
                );
                assistant.content.appendChild(
                    makeErrorCard(
                        payload.detail || `HTTP ${response.status}`,
                        response.headers.get("Retry-After")
                    )
                );
                return;
            }

            if (payload.action === "BLOCK") {
                const assistant = makeMessage(
                    "assistant",
                    "I did not send this prompt to the LLM provider because the input security policy blocked it."
                );
                assistant.content.appendChild(
                    makeSecurityCard(payload)
                );
                scrollToBottom();
                return;
            }

            const assistant = makeMessage(
                "assistant",
                payload.response || "The provider returned no response text.",
                {markdown: true}
            );
            assistant.content.appendChild(
                makeSecurityCard(payload)
            );
            scrollToBottom();
        } catch (_) {
            loading.remove();
            const assistant = makeMessage(
                "assistant",
                "Could not reach the LLMBastion API."
            );
            assistant.content.appendChild(
                makeErrorCard(
                    "Check that the FastAPI server is running."
                )
            );
        } finally {
            sending = false;
            updateComposer();
            input.focus();
        }
    };

    input.addEventListener("input", updateComposer);

    input.addEventListener("keydown", (event) => {
        if (
            event.key === "Enter"
            && !event.shiftKey
        ) {
            event.preventDefault();
            submitPrompt();
        }
    });

    sendButton.addEventListener("click", submitPrompt);

    updateComposer();
    input.focus();
})();
