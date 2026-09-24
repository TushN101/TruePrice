console.log("[TruePrice] Content script loaded on:", window.location.href);

// content.js — eBay product-page extraction.
//
// Runs on eBay item pages. Extracts:
//   - itemId   (eBay numeric item ID from the URL)
//   - title    (product title from the DOM)
//   - price    (current displayed price)
//   - url      (canonical product URL)
//
// Sends one observation per item per hour to the background worker.
//
// DEBUGGING: Open the browser console (F12) on an eBay product page
// and look for lines prefixed with "[TruePrice]".

// ─── Extraction helpers ────────────────────────────────────────────────

function getItemId() {
    const href = window.location.href;
    // eBay URLs: /itm/<ID> or /itm/<slug>/<ID>
    // Match the first 6+ digit number after /itm/
    const m = href.match(/\/itm\/(?:[^/?#]+\/)?(\d{6,})/i);
    if (m) {
        return m[1];
    }
    console.warn("[TruePrice] Could not extract item ID from URL:", href);
    return null;
}

function getProductTitle() {
    const el =
        document.querySelector("h1.x-item-title__mainTitle") ||
        document.querySelector("#itemTitle") ||
        document.querySelector("h1[itemprop='name']") ||
        document.querySelector("h1.ux-textspans");
    if (!el) return null;
    return el.textContent.replace(/\s+/g, " ").trim() || null;
}

function getPrice() {
    // Try multiple selectors in priority order.
    // eBay changes their DOM occasionally so we cast a wide net.
    const selectors = [
        "div.x-price-primary",
        ".x-price-primary",
        "#prcIsum",
        "span#prcIsum",
        "div#prcIsum",
        ".ux-price span",
        "[itemprop='price']",
        "meta[itemprop='price']",
        ".x-price-approx__price",
        ".displayprice",
    ];

    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const raw = (el.tagName === "META")
            ? el.getAttribute("content")
            : el.textContent;
        if (!raw) continue;
        const num = parsePriceText(raw);
        if (num != null) {
            console.log("[TruePrice] Found price:", num, "via selector:", sel);
            return num;
        }
    }

    console.warn("[TruePrice] Could not find price element on page.");
    return null;
}

function parsePriceText(text) {
    if (!text) return null;
    const cleaned = String(text).replace(/[^\d.]/g, "");
    if (!cleaned) return null;
    // Handle multiple dots — keep only the first.
    const parts = cleaned.split(".");
    if (parts.length > 2) {
        return parseFloat(parts[0] + "." + parts.slice(1).join(""));
    }
    const n = parseFloat(cleaned);
    return isNaN(n) ? null : n;
}

function canonicalUrl(itemId) {
    if (!itemId) return null;
    return "https://www.ebay.com/itm/" + itemId;
}

// ─── Throttle: one observation per item per hour ───────────────────────
// The throttle key is set ONLY after a successful send, so a failed
// first attempt will be retried on the next poll tick.

function checkThrottle(itemId, price) {
    const hourKey = new Date().toISOString().slice(0, 13); // YYYY-MM-DDTHH
    const key = "lastSent_" + itemId;
    return new Promise((resolve) => {
        chrome.storage.local.get([key], (result) => {
            const prev = result[key];
            if (prev && prev.hourKey === hourKey && String(prev.price) === String(price)) {
                console.log("[TruePrice] Throttled: already sent this hour for item", itemId);
                resolve(false);
                return;
            }
            resolve(true);
        });
    });
}

function setThrottle(itemId, price) {
    const hourKey = new Date().toISOString().slice(0, 13);
    const key = "lastSent_" + itemId;
    chrome.storage.local.set({ [key]: { hourKey, price } });
}

// ─── Local tracking (for the dashboard) ────────────────────────────────

function upsertItemId(itemId) {
    if (!itemId) return;
    chrome.storage.local.get(["itemIds"], (result) => {
        const ids = result.itemIds || [];
        if (ids.includes(itemId)) return;
        ids.push(itemId);
        chrome.storage.local.set({ itemIds: ids });
    });
}

function upsertProductName(itemId, name) {
    if (!itemId || !name) return;
    chrome.storage.local.get(["productNames"], (result) => {
        const names = result.productNames || {};
        if (names[itemId]) return;
        names[itemId] = name;
        chrome.storage.local.set({ productNames: names });
    });
}

// ─── Send observation via the background service worker ────────────────

function sendObservation(payload) {
    return new Promise((resolve) => {
        console.log("[TruePrice] Sending observation to background:", payload);
        chrome.runtime.sendMessage(
            { type: "SAVE_OBSERVATION", data: payload },
            (response) => {
                if (chrome.runtime.lastError) {
                    console.error("[TruePrice] Runtime error:", chrome.runtime.lastError.message);
                    resolve(false);
                    return;
                }
                if (response && response.status === "success") {
                    console.log("[TruePrice] OK - Observation stored by backend");
                    resolve(true);
                } else {
                    console.error("[TruePrice] FAIL - Observation failed:", response);
                    resolve(false);
                }
            },
        );
    });
}

// ─── Main polling loop ─────────────────────────────────────────────────

function startTracking() {
    console.log("[TruePrice] Starting price tracking...");

    let savedItemId = false;
    let savedName = false;
    let priceSent = false;
    let lastItemId = null;

    const MAX_ATTEMPTS = 60;   // ~30s at 500ms
    const INTERVAL_MS = 500;

    let attempts = 0;

    const poll = async () => {
        attempts++;
        const itemId = getItemId();
        const price = getPrice();

        // Reset flags if item changed (SPA navigation).
        if (itemId && itemId !== lastItemId) {
            console.log("[TruePrice] Item detected:", itemId);
            lastItemId = itemId;
            savedItemId = false;
            savedName = false;
            priceSent = false;
        }

        if (itemId && !savedItemId) {
            savedItemId = true;
            upsertItemId(itemId);
        }

        if (itemId && !savedName) {
            savedName = true;
            const title = getProductTitle();
            upsertProductName(itemId, title || itemId);
        }

        if (itemId && price != null && !priceSent) {
            const shouldSend = await checkThrottle(itemId, price);
            if (!shouldSend) {
                priceSent = true;
                return; // done — throttled
            }

            const success = await sendObservation({
                productId: itemId,
                price: price,
                currency: "USD",
                url: canonicalUrl(itemId),
                title: getProductTitle(),
            });

            if (success) {
                priceSent = true;
                setThrottle(itemId, price);
            }
            // If failed, DON'T set priceSent — allow retry on next tick.
        }

        if (!priceSent && attempts < MAX_ATTEMPTS) {
            setTimeout(poll, INTERVAL_MS);
        } else if (!priceSent) {
            console.warn(
                "[TruePrice] Gave up after", MAX_ATTEMPTS,
                "attempts. Item:", lastItemId,
                " — Check: (1) backend running at the configured URL,",
                "(2) extension registered, (3) eBay page fully loaded.",
            );
        }
    };

    poll(); // start immediately
}

startTracking();
