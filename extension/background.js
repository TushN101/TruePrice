/**
 * background.js — service worker.
 *
 * Handles message types from content scripts and popups:
 *
 *   SAVE_OBSERVATION  → POST /api/observations (JWT auth)
 *   REGISTER_CLIENT   → POST /api/registerClient
 *   FETCH_HISTORY     → POST /api/history
 *
 * Credentials (clientId, accessToken, refreshToken) are stored in
 * chrome.storage.local and attached to authenticated requests.
 *
 * DEBUGGING: Click "Service Worker" on the TruePrice extension card in
 * chrome://extensions to see console.log output from this file.
 */

const API_BASE = "http://vm:5000";

console.log("[TruePrice] Background service worker loaded. API_BASE:", API_BASE);

// ─── Credential helpers ────────────────────────────────────────────────

async function getCredentials() {
    return new Promise((resolve) => {
        chrome.storage.local.get(
            ["clientId", "accessToken", "refreshToken"],
            (result) => resolve(result),
        );
    });
}

async function setCredentials(creds) {
    return new Promise((resolve) => {
        chrome.storage.local.set(creds, () => resolve());
    });
}

// ─── Token refresh ─────────────────────────────────────────────────────

async function tryRefresh() {
    const { refreshToken } = await getCredentials();
    if (!refreshToken) {
        console.warn("[TruePrice] No refresh token available — client may not be registered.");
        return null;
    }

    try {
        const res = await fetch(`${API_BASE}/api/refresh`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${refreshToken}`,
                "Content-Type": "application/json",
            },
        });
        if (!res.ok) {
            console.warn("[TruePrice] Token refresh failed:", res.status);
            return null;
        }
        const data = await res.json();
        if (data.status !== "success") return null;
        await setCredentials({
            accessToken: data.accessToken,
            refreshToken: data.refreshToken,
        });
        console.log("[TruePrice] Token refreshed successfully");
        return data.accessToken;
    } catch (e) {
        console.error("[TruePrice] Token refresh error:", e);
        return null;
    }
}

// ─── Authenticated fetch with auto-refresh on 401 ──────────────────────

async function authedFetch(path, options = {}) {
    const { accessToken } = await getCredentials();
    if (!accessToken) {
        console.warn("[TruePrice] No access token — have you registered?");
    }
    options.headers = options.headers || {};
    options.headers["Authorization"] = `Bearer ${accessToken}`;
    options.headers["Content-Type"] = "application/json";

    let response = await fetch(`${API_BASE}${path}`, options);

    if (response.status === 401) {
        console.log("[TruePrice] Got 401, attempting token refresh...");
        const newToken = await tryRefresh();
        if (newToken) {
            options.headers["Authorization"] = `Bearer ${newToken}`;
            response = await fetch(`${API_BASE}${path}`, options);
        }
    }
    return response;
}

// ─── Message handler ───────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log("[TruePrice] Message received:", request.type, request.data);

    if (request.type === "REGISTER_CLIENT") {
        fetch(`${API_BASE}/api/registerClient`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        })
            .then((r) => r.json())
            .then(async (data) => {
                if (data.status === "success") {
                    await setCredentials({
                        clientId: data.clientId,
                        accessToken: data.accessToken,
                        refreshToken: data.refreshToken,
                    });
                    console.log("[TruePrice] Client registered:", data.clientId);
                } else {
                    console.error("[TruePrice] Registration failed:", data);
                }
                sendResponse(data);
            })
            .catch((err) => {
                console.error("[TruePrice] Registration network error:", err);
                sendResponse({
                    status: "error",
                    message: `Cannot reach backend at ${API_BASE}. Is the server running? (${err})`,
                });
            });
        return true; // async response
    }

    if (request.type === "SAVE_OBSERVATION") {
        authedFetch("/api/observations", {
            method: "POST",
            body: JSON.stringify(request.data),
        })
            .then((r) => r.json())
            .then((data) => {
                console.log("[TruePrice] Observation response:", data);
                if (data.refreshToken) {
                    getCredentials().then((creds) => {
                        setCredentials({
                            ...creds,
                            refreshToken: data.refreshToken,
                        });
                    });
                }
                sendResponse(data);
            })
            .catch((err) => {
                console.error("[TruePrice] Observation network error:", err);
                sendResponse({ status: "error", message: String(err) });
            });
        return true; // async response
    }

    if (request.type === "FETCH_HISTORY") {
        authedFetch("/api/history", {
            method: "POST",
            body: JSON.stringify({ productId: request.productId }),
        })
            .then((r) => r.json())
            .then((data) => {
                console.log("[TruePrice] History response status:", data.status);
                if (data.refreshToken) {
                    getCredentials().then((creds) => {
                        setCredentials({
                            ...creds,
                            refreshToken: data.refreshToken,
                        });
                    });
                }
                sendResponse(data);
            })
            .catch((err) => {
                console.error("[TruePrice] History network error:", err);
                sendResponse({ status: "error", message: String(err) });
            });
        return true; // async response
    }
});
