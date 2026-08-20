document.addEventListener("DOMContentLoaded", () => {
    const todoForm = document.getElementById("todoForm");
    if (todoForm) {
        todoForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const data = Object.fromEntries(new FormData(event.target).entries());

            const payload = {
                title: data.title,
                description: data.description,
                priority: parseInt(data.priority, 10),
                complete: false
            };

            const response = await authenticatedFetch("/todo/todo", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                window.location.href = "/todo/todo-page";
                return;
            }

            await showApiError(response);
        });
    }

    const editTodoForm = document.getElementById("editTodoForm");
    if (editTodoForm) {
        editTodoForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const data = Object.fromEntries(new FormData(event.target).entries());
            const todoId = window.location.pathname.split("/").pop();

            const payload = {
                title: data.title,
                description: data.description,
                priority: parseInt(data.priority, 10),
                complete: data.complete === "on"
            };

            const response = await authenticatedFetch(`/todo/todo/${todoId}`, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                window.location.href = "/todo/todo-page";
                return;
            }

            await showApiError(response);
        });

        const deleteButton = document.getElementById("deleteButton");
        if (deleteButton) {
            deleteButton.addEventListener("click", async () => {
                const todoId = window.location.pathname.split("/").pop();

                const response = await authenticatedFetch(`/todo/todo/${todoId}`, {
                    method: "DELETE"
                });

                if (response.ok) {
                    window.location.href = "/todo/todo-page";
                    return;
                }

                await showApiError(response);
            });
        }
    }

    const loginForm = document.getElementById("loginForm");
    if (loginForm) {
        loginForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const formData = new FormData(event.target);
            const payload = new URLSearchParams();

            for (const [key, value] of formData.entries()) {
                payload.append(key, value);
            }

            const response = await fetch("/auth/token", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                body: payload.toString()
            });

            if (!response.ok) {
                await showApiError(response);
                return;
            }

            const data = await response.json();

            logout(false);
            document.cookie = `access_token=${encodeURIComponent(data.access_token)}; path=/; SameSite=Lax`;

            window.location.href = "/todo/todo-page";
        });
    }

    const registerForm = document.getElementById("registerForm");
    if (registerForm) {
        registerForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const data = Object.fromEntries(new FormData(event.target).entries());

            if (data.password !== data.password2) {
                alert("Passwords do not match");
                return;
            }

            const payload = {
                email: data.email,
                username: data.username,
                first_name: data.firstname,
                last_name: data.lastname,
                phone_number: data.phone_number,
                password: data.password
            };

            const response = await fetch("/auth/", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                window.location.href = "/auth/login-page";
                return;
            }

            await showApiError(response);
        });
    }
});


function getCookie(name) {
    if (!document.cookie) {
        return null;
    }

    const cookies = document.cookie.split(";");

    for (const cookiePart of cookies) {
        const cookie = cookiePart.trim();

        if (cookie.startsWith(`${name}=`)) {
            return decodeURIComponent(cookie.substring(name.length + 1));
        }
    }

    return null;
}


async function authenticatedFetch(url, options = {}) {
    const token = getCookie("access_token");

    if (!token) {
        window.location.href = "/auth/login-page";
        throw new Error("Authentication token not found");
    }

    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${token}`);

    return fetch(url, {
        ...options,
        headers
    });
}


async function showApiError(response) {
    let message = `Request failed (${response.status})`;

    try {
        const error = await response.json();
        message = error.detail || error.message || message;
    } catch (_) {
        // Keep fallback message.
    }

    alert(message);
}


function logout(redirect = true) {
    const cookies = document.cookie.split(";");

    for (const cookie of cookies) {
        const eqPos = cookie.indexOf("=");
        const name = eqPos > -1 ? cookie.substring(0, eqPos).trim() : cookie.trim();

        document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax`;
    }

    if (redirect) {
        window.location.href = "/auth/login-page";
    }
}
