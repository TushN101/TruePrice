/**
 * dashboard.js — multi-product dashboard.
 *
 * Reads the list of tracked eBay item IDs from chrome.storage.local
 * (populated by content.js), fetches each product's price history via
 * the background worker, and renders a card with a mini Chart.js line
 * chart per product matching the Claude-inspired design system.
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
    card.className = "card card--interactive";
    card.setAttribute("data-item-id", itemId);
    card.setAttribute("data-title", (title || "").toLowerCase());

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
    openBtn.className = "btn btn--secondary btn--sm";
    openBtn.type = "button";
    openBtn.innerHTML = `<span>View on eBay</span><svg class="icon icon--sm" style="width:12px;height:12px;"><use href="#i-arrow-up-right"/></svg>`;
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

    const gradient = ctx.createLinearGradient(0, 0, 0, 140);
    gradient.addColorStop(0, "rgba(198, 97, 63, 0.12)");
    gradient.addColorStop(1, "rgba(198, 97, 63, 0.00)");

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
                borderColor: "#c6613f",
                backgroundColor: gradient,
                borderWidth: 2,
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
                    return (i === minIndex || i === maxIndex) ? 2 : 0;
                },
                pointBorderColor: "#ffffff",
                pointBackgroundColor: (c) => {
                    const i = c.dataIndex;
                    if (i === minIndex) return "#2f7d4f";
                    if (i === maxIndex) return "#b53333";
                    return "#c6613f";
                },
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: { top: 4, bottom: 2, left: 2, right: 2 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "#ffffff",
                    titleColor: "#73726c",
                    bodyColor: "#141413",
                    borderColor: "#e6e4da",
                    borderWidth: 1,
                    padding: 8,
                    cornerRadius: 6,
                    displayColors: false,
                    titleFont: { family: '"Anthropic Sans", system-ui, sans-serif', size: 10, weight: "500" },
                    bodyFont: { family: 'ui-monospace, monospace', size: 12, weight: "600" },
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

function renderEmptyState(type = "initial") {
    const empty = document.getElementById("empty");
    if (!empty) return;
    empty.style.display = "flex";

    if (type === "search") {
        empty.innerHTML = `
            <div class="empty-icon">
                <svg class="icon icon--lg"><use href="#i-search"/></svg>
            </div>
            <h3 class="heading-display" style="font-size: 1.15rem; margin-bottom: 4px;">No matching items</h3>
            <p class="text-muted text-sm" style="max-width: 320px;">
                No tracked products matched your search term.
            </p>
        `;
    } else {
        empty.innerHTML = `
            <div class="empty-icon">
                <svg class="icon icon--lg"><use href="#i-spark"/></svg>
            </div>
            <h3 class="heading-display" style="font-size: 1.15rem; margin-bottom: 4px;">No tracked products yet</h3>
            <p class="text-muted text-sm" style="max-width: 380px; margin-bottom: 16px;">
                Browse eBay product pages in Chrome. TruePrice will automatically record price observations and compute consensus histories.
            </p>
            <a href="https://www.ebay.com" target="_blank" rel="noopener noreferrer" class="btn btn--secondary btn--sm">
                <span>Browse eBay</span>
                <svg class="icon icon--sm"><use href="#i-arrow-up-right"/></svg>
            </a>
        `;
    }
}

async function loadDashboard() {
    const grid = document.getElementById("grid");
    const empty = document.getElementById("empty");
    const statusMsg = document.getElementById("statusMessage");
    const tabCount = document.getElementById("tabCount");
    const sidebarCount = document.getElementById("sidebarProductCount");

    grid.innerHTML = "";
    if (empty) {
        empty.style.display = "flex";
        empty.innerHTML = `<p class="text-muted text-sm">Loading tracked prices...</p>`;
    }
    if (statusMsg) statusMsg.innerText = "Syncing...";

    const result = await new Promise((resolve) => {
        chrome.storage.local.get(["itemIds", "productNames"], resolve);
    });
    const itemIds = result.itemIds || [];
    const productNames = result.productNames || {};

    if (itemIds.length === 0) {
        renderEmptyState("initial");
        if (statusMsg) statusMsg.innerText = "0 products";
        if (tabCount) tabCount.innerText = "0";
        if (sidebarCount) sidebarCount.innerText = "0";
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
        renderEmptyState("initial");
    } else {
        if (empty) empty.style.display = "none";
    }

    if (statusMsg) statusMsg.innerText = `${renderedCount} tracked`;
    if (tabCount) tabCount.innerText = String(renderedCount);
    if (sidebarCount) sidebarCount.innerText = String(renderedCount);
}

// ─── Search filter ─────────────────────────────────────────────────────

const searchInput = document.getElementById("searchInput");
if (searchInput) {
    searchInput.addEventListener("input", (e) => {
        const query = e.target.value.trim().toLowerCase();
        const cards = document.querySelectorAll("#grid .card");
        let visibleCount = 0;

        cards.forEach((card) => {
            const title = card.getAttribute("data-title") || "";
            const itemId = card.getAttribute("data-item-id") || "";
            const match = !query || title.includes(query) || itemId.includes(query);
            card.style.display = match ? "flex" : "none";
            if (match) visibleCount++;
        });

        const empty = document.getElementById("empty");
        if (cards.length > 0) {
            if (visibleCount === 0) {
                renderEmptyState("search");
            } else if (empty) {
                empty.style.display = "none";
            }
        }
    });
}

loadDashboard();
