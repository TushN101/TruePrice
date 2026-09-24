/**
 * dashboard.js — multi-product dashboard.
 *
 * Reads the list of tracked eBay item IDs from chrome.storage.local
 * (populated by content.js), fetches each product's price history via
 * the background worker, and renders a card with a mini Chart.js line
 * chart per product.
 */

function formatPrice(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return "-";
    return "$" + value.toLocaleString("en-US");
}

function prettifyName(raw) {
    const s = String(raw || "").trim();
    if (!s) return "";
    return s.replace(/\s+/g, " ").trim();
}

function openOnEbay(itemId) {
    const url = `https://www.ebay.com/itm/${encodeURIComponent(itemId)}`;
    try {
        if (chrome.tabs && chrome.tabs.create) {
            chrome.tabs.create({ url });
            return;
        }
    } catch (e) { /* fall through */ }
    window.open(url, "_blank");
}

function fetchHistory(itemId) {
    return new Promise((resolve) => {
        chrome.runtime.sendMessage(
            { type: "FETCH_HISTORY", productId: itemId },
            (response) => resolve(response || { status: "error", message: "no response" }),
        );
    });
}

function buildCard({ itemId, title, history }) {
    const card = document.createElement("div");
    card.className = "card";

    const top = document.createElement("div");
    top.className = "top";

    const nameWrap = document.createElement("div");
    nameWrap.className = "meta";

    const nameEl = document.createElement("div");
    nameEl.className = "name";
    nameEl.innerText = title || itemId;
    nameEl.title = title || itemId;

    const codeEl = document.createElement("div");
    codeEl.className = "code";
    codeEl.innerText = "eBay: " + itemId;

    nameWrap.appendChild(nameEl);
    nameWrap.appendChild(codeEl);

    const last = history[history.length - 1];
    const lastPrice = last.canonicalPrice;

    const priceEl = document.createElement("div");
    priceEl.className = "price";
    priceEl.innerText = formatPrice(lastPrice);

    top.appendChild(nameWrap);
    top.appendChild(priceEl);

    const actionsRow = document.createElement("div");
    actionsRow.className = "actionsRow";

    const stats = document.createElement("div");
    stats.className = "stats";

    const openBtn = document.createElement("button");
    openBtn.className = "btn";
    openBtn.type = "button";
    openBtn.innerText = "Open on eBay";
    openBtn.addEventListener("click", () => openOnEbay(itemId));

    actionsRow.appendChild(stats);
    actionsRow.appendChild(openBtn);

    const chartWrap = document.createElement("div");
    chartWrap.className = "chart";
    const canvas = document.createElement("canvas");
    chartWrap.appendChild(canvas);

    card.appendChild(top);
    card.appendChild(actionsRow);
    card.appendChild(chartWrap);

    const labels = [];
    const prices = [];
    let min = Infinity, max = -Infinity;
    let minIndex = -1, maxIndex = -1;

    history.forEach((e) => {
        const p = e.canonicalPrice;
        const d = new Date(e.hour);
        if (!d.getTime() || typeof p !== "number") return;
        labels.push(d.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
        prices.push(p);
        if (p < min) { min = p; minIndex = prices.length - 1; }
        if (p > max) { max = p; maxIndex = prices.length - 1; }
    });

    if (prices.length === 1) {
        const d = new Date(history[0].hour);
        const d2 = new Date(d.getTime() + 24 * 60 * 60 * 1000);
        labels.push(d2.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
        prices.push(prices[0]);
        minIndex = 0;
        maxIndex = 0;
    }

    if (Number.isFinite(min) && Number.isFinite(max) && prices.length > 0) {
        stats.innerText = `min ${formatPrice(min)} • max ${formatPrice(max)} • ${prices.length}h`;
    } else {
        stats.innerText = "Not enough data yet.";
    }

    const ctx = canvas.getContext("2d");
    const theme = getComputedStyle(document.body);
    const chartLine = theme.getPropertyValue("--chart-1").trim() || "#3794ff";
    const chartMin = theme.getPropertyValue("--chart-2").trim() || "#4ec9b0";
    const chartMax = theme.getPropertyValue("--destructive").trim() || "#f14c4c";

    const gradient = ctx.createLinearGradient(0, 0, 0, 160);
    gradient.addColorStop(0, "rgba(0, 0, 0, 0.18)");
    gradient.addColorStop(1, "rgba(0, 0, 0, 0.00)");

    const spread = max - min;
    const padding = Math.max(spread * 0.10, Math.max(25, (Number.isFinite(lastPrice) ? lastPrice : 0) * 0.02));
    const yMin = Number.isFinite(min) ? Math.max(0, Math.floor(min - padding)) : undefined;
    const yMax = Number.isFinite(max) ? Math.ceil(max + padding) : undefined;

    new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [{
                data: prices,
                borderColor: chartLine,
                backgroundColor: gradient,
                borderWidth: 2.25,
                fill: true,
                tension: 0.3,
                pointRadius: (c) => {
                    if (prices.length === 1) return 3.5;
                    const i = c.dataIndex;
                    return (i === minIndex || i === maxIndex) ? 3.5 : 0;
                },
                pointHoverRadius: 5,
                pointBorderWidth: (c) => {
                    const i = c.dataIndex;
                    return (i === minIndex || i === maxIndex) ? 2.25 : 0;
                },
                pointBorderColor: (c) => {
                    const i = c.dataIndex;
                    if (i === minIndex) return chartMin;
                    if (i === maxIndex) return chartMax;
                    return chartLine;
                },
                pointBackgroundColor: "#ffffff",
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (c) => formatPrice(c.parsed.y),
                    },
                },
            },
            scales: {
                x: { display: false },
                y: { display: false, min: yMin, max: yMax },
            },
        },
    });

    return card;
}

async function loadDashboard() {
    const grid = document.getElementById("grid");
    const empty = document.getElementById("empty");
    grid.innerHTML = "";
    empty.style.display = "block";
    empty.innerText = "Loading tracked prices...";

    const result = await new Promise((resolve) => {
        chrome.storage.local.get(["itemIds", "productNames"], resolve);
    });
    const itemIds = result.itemIds || [];
    const productNames = result.productNames || {};

    if (itemIds.length === 0) {
        empty.innerText = "No tracked products yet. Browse eBay product pages to start collecting prices.";
        return;
    }

    let renderedCount = 0;

    for (const itemId of itemIds) {
        try {
            const data = await fetchHistory(itemId);
            if (data.status !== "success" || !Array.isArray(data.history) || data.history.length === 0) continue;

            const rawName = productNames[itemId] || itemId;
            const title = prettifyName(rawName) || itemId;
            const card = buildCard({ itemId, title, history: data.history });
            grid.appendChild(card);
            renderedCount += 1;
        } catch (err) {
            console.error("Error loading:", itemId, err);
        }
    }

    if (renderedCount === 0) {
        empty.innerText = "No price history available yet. Reopen product pages to trigger computation.";
        empty.style.display = "block";
    } else {
        empty.style.display = "none";
    }
}

loadDashboard();
