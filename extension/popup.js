// popup.js — TruePrice extension popup.
//
// Two states:
//   1. No credentials → show Register button.
//   2. Credentials present → detect active eBay tab, fetch price
//      history, render chart + stats.

const API_BASE = "http://vm:5000";

let chartInstance = null;

// ─── Credential helpers ────────────────────────────────────────────────

function getCredentials() {
    return new Promise((resolve) => {
        chrome.storage.local.get(
            ["clientId", "accessToken", "refreshToken"],
            (result) => resolve(result),
        );
    });
}

// ─── View switching ────────────────────────────────────────────────────

function showRegisterView() {
    document.getElementById("registerView").style.display = "flex";
    document.getElementById("loading").style.display = "none";
    document.getElementById("content").style.display = "none";
    document.getElementById("error").style.display = "none";
    document.getElementById("footer").style.display = "none";
}

function showError(title, message) {
    document.getElementById("loading").style.display = "none";
    document.getElementById("content").style.display = "none";
    document.getElementById("registerView").style.display = "none";
    document.getElementById("footer").style.display = "none";
    const errDiv = document.getElementById("error");
    errDiv.style.display = "flex";
    document.getElementById("errorTitle").innerText = title || "Error";
    document.getElementById("errorMsg").innerText = message || "";
}

function showLoading(text) {
    document.getElementById("registerView").style.display = "none";
    document.getElementById("content").style.display = "none";
    document.getElementById("error").style.display = "none";
    document.getElementById("footer").style.display = "none";
    document.getElementById("loading").style.display = "flex";
    if (text) document.getElementById("loadingText").innerText = text;
}

function showContent() {
    document.getElementById("loading").style.display = "none";
    document.getElementById("error").style.display = "none";
    document.getElementById("registerView").style.display = "none";
    document.getElementById("content").style.display = "flex";
    document.getElementById("footer").style.display = "flex";
}

// ─── Registration ──────────────────────────────────────────────────────

function setupRegisterButton() {
    const btn = document.getElementById("registerBtn");
    if (!btn) return;
    btn.addEventListener("click", () => {
        btn.disabled = true;
        btn.innerText = "Registering...";
        chrome.runtime.sendMessage(
            { type: "REGISTER_CLIENT" },
            (response) => {
                if (response && response.status === "success") {
                    window.location.reload();
                } else {
                    btn.disabled = false;
                    btn.innerText = "Register";
                    const errEl = document.getElementById("registerError");
                    errEl.style.display = "block";
                    errEl.innerText =
                        (response && response.message) ||
                        "Registration failed. Is the backend running on " + API_BASE + "?";
                }
            },
        );
    });
}

// ─── eBay tab detection ────────────────────────────────────────────────

async function getActiveTabItemId() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) return null;
    const m = tab.url.match(/\/itm\/(?:[^/?#]+\/)?(\d{6,})/i);
    return m ? m[1] : null;
}

async function getCurrentPagePrice() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) return null;
    try {
        const results = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: () => {
                const selectors = [
                    "div.x-price-primary", ".x-price-primary",
                    "#prcIsum", "span#prcIsum", "div#prcIsum",
                    "[itemprop='price']", "meta[itemprop='price']",
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (!el) continue;
                    const raw = (el.tagName === "META")
                        ? el.getAttribute("content")
                        : el.textContent;
                    if (!raw) continue;
                    const cleaned = raw.replace(/[^\d.]/g, "");
                    const n = parseFloat(cleaned);
                    if (!isNaN(n)) return n;
                }
                return null;
            },
        });
        return results?.[0]?.result ?? null;
    } catch (e) {
        return null;
    }
}

// ─── Chart rendering ───────────────────────────────────────────────────

function renderSinglePrice(price) {
    showContent();
    document.getElementById("productLabel").innerText = "Live Page Price";
    document.getElementById("currentPrice").innerText = "$" + Number(price).toLocaleString("en-US");
    const changeEl = document.getElementById("priceChange");
    changeEl.className = "priceBadge badge-accent";
    changeEl.innerText = "LIVE";
    document.getElementById("minStat").innerText = "—";
    document.getElementById("maxStat").innerText = "—";
    document.getElementById("hoursStat").innerText = "0";
    document.getElementById("confidenceValue").innerText = "—";
    document.getElementById("confidenceFill").style.width = "0%";
    document.getElementById("chartMeta").innerText = "No history yet";
    setFooterStatus("amber", "No history");
}

function renderHistory(history) {
    if (!history || history.length === 0) {
        showError("No History Yet", "Submit an observation from an eBay product page, then reopen this popup.");
        return;
    }

    showContent();

    const labels = [];
    const prices = [];
    const confidences = [];
    const validationFlags = [];
    let min = Infinity, max = -Infinity;
    let minIndex = -1, maxIndex = -1;

    history.forEach((entry) => {
        const d = new Date(entry.hour);
        if (isNaN(d.getTime())) return;
        const p = entry.canonicalPrice;
        if (typeof p !== "number") return;

        labels.push(d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" }));
        prices.push(p);
        confidences.push(entry.confidence || 0);
        validationFlags.push(entry.validationPerformed || false);
        if (p < min) { min = p; minIndex = prices.length - 1; }
        if (p > max) { max = p; maxIndex = prices.length - 1; }
    });

    if (prices.length === 0) {
        showError("Data Error", "No valid price data in history response.");
        return;
    }

    const current = prices[prices.length - 1];
    const previous = prices.length > 1 ? prices[prices.length - 2] : current;
    let pctChange = 0;
    if (prices.length > 1 && previous > 0) {
        pctChange = ((current - previous) / previous) * 100;
    }

    // Price change badge
    const changeEl = document.getElementById("priceChange");
    if (prices.length === 1) {
        changeEl.className = "priceBadge badge-accent";
        changeEl.innerText = "NEW";
    } else if (pctChange < -0.5) {
        changeEl.className = "priceBadge badge-green";
        changeEl.innerHTML = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="6 9 12 15 18 9"/></svg>${Math.abs(pctChange).toFixed(1)}%`;
    } else if (pctChange > 0.5) {
        changeEl.className = "priceBadge badge-red";
        changeEl.innerHTML = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="18 15 12 9 6 15"/></svg>${pctChange.toFixed(1)}%`;
    } else {
        changeEl.className = "priceBadge badge-neutral";
        changeEl.innerText = "0.0%";
    }

    document.getElementById("productLabel").innerText = "Canonical Price";
    document.getElementById("currentPrice").innerText = "$" + current.toLocaleString("en-US");
    document.getElementById("minStat").innerText = "$" + min.toLocaleString("en-US");
    document.getElementById("maxStat").innerText = "$" + max.toLocaleString("en-US");
    document.getElementById("hoursStat").innerText = String(prices.length);

    // Confidence bar (average of last few entries)
    const recentConfs = confidences.slice(-5);
    const avgConf = recentConfs.reduce((a, b) => a + b, 0) / recentConfs.length;
    const confPct = Math.round(avgConf * 100);
    document.getElementById("confidenceValue").innerText = confPct + "%";
    const fillEl = document.getElementById("confidenceFill");
    fillEl.style.width = confPct + "%";
    if (avgConf >= 0.8) {
        fillEl.style.background = "var(--green)";
    } else if (avgConf >= 0.6) {
        fillEl.style.background = "var(--accent)";
    } else {
        fillEl.style.background = "var(--red)";
    }

    // Chart meta
    const validatedCount = validationFlags.filter(Boolean).length;
    document.getElementById("chartMeta").innerText =
        `${prices.length}h • ${validatedCount} validated`;

    // Chart
    const ctx = document.getElementById("priceChart").getContext("2d");
    let gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, "rgba(245, 158, 11, 0.2)");
    gradient.addColorStop(1, "rgba(245, 158, 11, 0.0)");

    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }

    const spread = max - min;
    const padding = Math.max(spread * 0.10, Math.max(25, current * 0.02));
    const yMin = Math.max(0, Math.floor(min - padding));
    const yMax = Math.ceil(max + padding);

    chartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [{
                data: prices,
                borderColor: "#f59e0b",
                backgroundColor: gradient,
                borderWidth: 2,
                pointBackgroundColor: (c) => {
                    const i = c.dataIndex;
                    if (i === minIndex) return "#10b981";
                    if (i === maxIndex) return "#ef4444";
                    return "#f59e0b";
                },
                pointBorderColor: "#1c1c20",
                pointBorderWidth: (c) => {
                    const i = c.dataIndex;
                    return (i === minIndex || i === maxIndex) ? 2 : 0;
                },
                pointRadius: (c) => {
                    const i = c.dataIndex;
                    if (prices.length === 1) return 4;
                    if (i === minIndex || i === maxIndex) return 4;
                    return 0;
                },
                pointHoverRadius: 5,
                fill: true,
                tension: 0.3,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: { right: 8, top: 4 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "#18181b",
                    titleColor: "#a1a1aa",
                    bodyColor: "#f4f4f5",
                    borderColor: "#2a2a30",
                    borderWidth: 1,
                    padding: 10,
                    cornerRadius: 8,
                    displayColors: false,
                    titleFont: { family: "Inter", size: 10, weight: "600" },
                    bodyFont: { family: "JetBrains Mono", size: 12, weight: "700" },
                    callbacks: {
                        label: (context) => {
                            const i = context.dataIndex;
                            const parts = ["$" + context.parsed.y.toLocaleString("en-US")];
                            if (i === minIndex) parts.push("↓ Low");
                            if (i === maxIndex) parts.push("↑ High");
                            const conf = Math.round((confidences[i] || 0) * 100);
                            parts.push(conf + "% conf");
                            if (validationFlags[i]) parts.push("✓ validated");
                            return parts;
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    border: { display: false },
                    ticks: {
                        maxTicksLimit: 4,
                        color: "#71717a",
                        font: { family: "Inter", size: 9 },
                    },
                },
                y: {
                    border: { display: false },
                    grid: { color: "rgba(255,255,255,0.04)" },
                    ticks: {
                        maxTicksLimit: 4,
                        color: "#71717a",
                        font: { family: "JetBrains Mono", size: 9 },
                        callback: (v) => "$" + v,
                    },
                    min: yMin,
                    max: yMax,
                },
            },
        },
    });

    // Footer status
    if (avgConf >= 0.8) {
        setFooterStatus("green", "High confidence");
    } else if (avgConf >= 0.6) {
        setFooterStatus("amber", "Moderate confidence");
    } else {
        setFooterStatus("red", "Low confidence");
    }
}

function setFooterStatus(color, text) {
    const el = document.getElementById("footerStatus");
    el.innerHTML = `<span class="footerDot dot-${color}"></span>${text}`;
}

// ─── Main flow ─────────────────────────────────────────────────────────

async function init() {
    const creds = await getCredentials();

    if (!creds.clientId || !creds.accessToken) {
        showRegisterView();
        setupRegisterButton();
        return;
    }

    // Show client ID in footer
    const clientEl = document.getElementById("footerClient");
    if (clientEl) {
        clientEl.innerText = creds.clientId.slice(0, 8) + "…";
    }

    const itemId = await getActiveTabItemId();
    if (!itemId) {
        showError(
            "Not an eBay Product Page",
            "Open an eBay product page (https://www.ebay.com/itm/…) to see price history.",
        );
        return;
    }

    showLoading("Fetching price history…");

    chrome.runtime.sendMessage(
        { type: "FETCH_HISTORY", productId: itemId },
        async (response) => {
            if (!response) {
                showError("Connection Error", "No response from background worker.");
                return;
            }
            if (response.status === "error") {
                showError("Backend Error", response.message || "Unknown error.");
                return;
            }
            if (response.status === "missing" || !response.history || response.history.length === 0) {
                const livePrice = await getCurrentPagePrice();
                if (livePrice != null) {
                    renderSinglePrice(livePrice);
                } else {
                    showError(
                        "No History Yet",
                        "Browse eBay product pages to collect observations. The system will compute history automatically.",
                    );
                }
                return;
            }
            renderHistory(response.history);
        },
    );
}

// ─── Dashboard button ──────────────────────────────────────────────────

const dashBtn = document.getElementById("dashboardBtn");
if (dashBtn) {
    dashBtn.addEventListener("click", () => {
        const url = chrome.runtime.getURL("dashboard.html");
        try {
            if (chrome.tabs && chrome.tabs.create) {
                chrome.tabs.create({ url });
                return;
            }
        } catch (e) { /* fall through */ }
        window.open(url, "_blank");
    });
}

init();
