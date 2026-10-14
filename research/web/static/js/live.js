// Live Dashboard Controller for TruePrice Simulation (Claude Design System)
(function () {
  const runId = window.SIMULATION_RUN_ID;
  const attackStartTick = window.ATTACK_START_TICK;
  const totalTicks = window.TOTAL_TICKS;
  const reportUrl = window.REPORT_URL;

  let isPlaying = true;
  let intervalTimer = null;
  let speedMs = 50;

  // DOM Elements
  const btnPlayPause = document.getElementById("btnPlayPause");
  const btnStep = document.getElementById("btnStep");
  const btnFastForward = document.getElementById("btnFastForward");
  const speedSelect = document.getElementById("speedSelect");

  const counterTimeline = document.getElementById("counterTimeline");
  const counterSubTimeline = document.getElementById("counterSubTimeline");
  const counterSubmissions = document.getElementById("counterSubmissions");
  const counterValidation = document.getElementById("counterValidation");
  const counterCumulativeVal = document.getElementById("counterCumulativeVal");
  const counterConfidence = document.getElementById("counterConfidence");
  const counterTrustedRatio = document.getElementById("counterTrustedRatio");
  const phaseBadge = document.getElementById("phaseBadge");
  const topUsersTbody = document.getElementById("topUsersTbody");
  const finishedBanner = document.getElementById("finishedBanner");

  // Chart setup
  const ctx = document.getElementById("livePriceChart").getContext("2d");
  const chartLabels = [];
  const actualPriceData = [];
  const predictedPriceData = [];

  const priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: chartLabels,
      datasets: [
        {
          label: "Known Actual Price",
          data: actualPriceData,
          borderColor: "#141413",
          borderWidth: 1.8,
          pointRadius: 0,
          tension: 0.1,
          fill: false,
        },
        {
          label: "Crowd Predicted Price",
          data: predictedPriceData,
          borderColor: "#c6613f",
          borderWidth: 2.2,
          pointRadius: 0,
          tension: 0.1,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: {
        mode: "index",
        intersect: false,
      },
      scales: {
        x: {
          grid: { color: "rgba(230, 228, 218, 0.7)" },
          ticks: {
            color: "#73726c",
            maxTicksLimit: 10,
            font: { family: '-apple-system, system-ui, sans-serif', size: 11 },
          },
          title: {
            display: true,
            text: "Simulated Hours (Ticks)",
            color: "#73726c",
            font: { size: 12 },
          },
        },
        y: {
          grid: { color: "rgba(230, 228, 218, 0.7)" },
          ticks: {
            color: "#73726c",
            callback: (v) => "$" + v,
            font: { family: '-apple-system, system-ui, sans-serif', size: 11 },
          },
          title: {
            display: true,
            text: "Price ($ USD)",
            color: "#73726c",
            font: { size: 12 },
          },
        },
      },
      plugins: {
        legend: {
          labels: {
            color: "#141413",
            font: { family: '-apple-system, system-ui, sans-serif', size: 12, weight: "500" },
            boxWidth: 14,
            usePointStyle: false,
          },
        },
        tooltip: {
          backgroundColor: "#ffffff",
          titleColor: "#141413",
          bodyColor: "#3d3d3a",
          borderColor: "#d6d3c6",
          borderWidth: 1,
          padding: 10,
          callbacks: {
            label: (ctx) => ` ${ctx.dataset.label}: $${ctx.parsed.y.toFixed(2)}`,
          },
        },
      },
    },
  });

  function updatePhaseBadge(tick) {
    if (tick < attackStartTick) {
      phaseBadge.textContent = "Seed Phase (Honest History)";
      phaseBadge.className = "badge badge--accent";
    } else {
      phaseBadge.textContent = "⚡ Attack Window Active";
      phaseBadge.className = "badge badge--danger";
    }
  }

  function renderTopUsers(users) {
    if (!users || !users.length) return;
    let html = "";
    users.forEach((u, idx) => {
      let badgeClass = "badge--success";
      let badgeLabel = "Honest";

      if (u.status_tag === "imposter") {
        badgeClass = "badge--danger";
        badgeLabel = "Imposter";
      } else if (u.status_tag === "sleeper_dormant") {
        badgeClass = "badge--warning";
        badgeLabel = "Sleeper (Dormant)";
      } else if (u.status_tag === "sleeper_active") {
        badgeClass = "badge--danger";
        badgeLabel = "Sleeper (Active)";
      }

      // Progress bar percentage (reputation in [0.1, 0.9])
      const repPercent = Math.min(100, Math.max(0, ((u.reputation - 0.1) / 0.8) * 100));
      const barColor = u.reputation > 0.5 ? "var(--color-success)" : "var(--color-danger)";

      html += `
        <tr>
          <td style="color: var(--color-text-faint); font-weight: 600;">${idx + 1}</td>
          <td style="font-family: var(--font-mono); font-size: 0.75rem;">${u.user_id}</td>
          <td><span class="badge ${badgeClass}">${badgeLabel}</span></td>
          <td>
            <div class="trust-bar">
              <div class="trust-bar__bg">
                <div class="trust-bar__fill" style="width: ${repPercent}%; background-color: ${barColor};"></div>
              </div>
              <strong style="font-size: var(--text-xs);">${u.reputation.toFixed(3)}</strong>
            </div>
          </td>
        </tr>
      `;
    });
    topUsersTbody.innerHTML = html;
  }

  function handleTickResult(data) {
    if (!data.ticks || !data.ticks.length) return;

    data.ticks.forEach((r) => {
      chartLabels.push(`h${r.tick}`);
      actualPriceData.push(r.actual_price);
      predictedPriceData.push(r.predicted_price);
    });

    const latest = data.latest;
    if (latest) {
      counterTimeline.textContent = `Hour ${latest.tick + 1} / ${totalTicks}`;
      counterSubTimeline.textContent = `Day ${latest.day}, ${String(latest.hour_of_day).padStart(2, "0")}:00`;
      counterSubmissions.textContent = latest.submission_count;

      if (latest.validation_performed) {
        counterValidation.textContent = "VALIDATED";
        counterValidation.style.color = "var(--color-danger)";
      } else {
        counterValidation.textContent = "Accepted";
        counterValidation.style.color = "var(--color-success)";
      }

      counterCumulativeVal.textContent = `Cumulative validations: ${data.cumulative_validations}`;
      counterConfidence.textContent = `${(latest.confidence * 100).toFixed(1)}%`;
      counterTrustedRatio.textContent = `Trusted ratio: ${(latest.trusted_ratio * 100).toFixed(1)}%`;

      updatePhaseBadge(latest.tick);
      renderTopUsers(latest.top_20_users);
    }

    priceChart.update();

    if (data.is_complete) {
      stopPlaying();
      finishedBanner.style.display = "block";
      btnPlayPause.disabled = true;
      btnStep.disabled = true;
      btnFastForward.disabled = true;
    }
  }

  async function fetchNextTick(batch = 1) {
    try {
      const resp = await fetch(`/api/simulations/${runId}/tick?batch=${batch}`);
      if (!resp.ok) {
        stopPlaying();
        return;
      }
      const data = await resp.json();
      handleTickResult(data);
    } catch (err) {
      console.error("Error fetching tick:", err);
      stopPlaying();
    }
  }

  function startPlaying() {
    if (intervalTimer) clearInterval(intervalTimer);
    isPlaying = true;
    btnPlayPause.textContent = "⏸ Pause";
    btnPlayPause.className = "btn btn--primary";
    intervalTimer = setInterval(() => {
      fetchNextTick(1);
    }, speedMs);
  }

  function stopPlaying() {
    if (intervalTimer) clearInterval(intervalTimer);
    intervalTimer = null;
    isPlaying = false;
    btnPlayPause.textContent = "▶ Resume";
    btnPlayPause.className = "btn btn--secondary";
  }

  btnPlayPause.addEventListener("click", () => {
    if (isPlaying) {
      stopPlaying();
    } else {
      startPlaying();
    }
  });

  btnStep.addEventListener("click", () => {
    stopPlaying();
    fetchNextTick(1);
  });

  btnFastForward.addEventListener("click", async () => {
    stopPlaying();
    btnFastForward.disabled = true;
    btnFastForward.textContent = "⚡ Fast-Forwarding...";
    try {
      const resp = await fetch(`/api/simulations/${runId}/fast_forward`, {
        method: "POST",
      });
      if (resp.ok) {
        window.location.href = reportUrl;
      }
    } catch (err) {
      alert("Error fast-forwarding: " + err.message);
    }
  });

  speedSelect.addEventListener("change", (e) => {
    speedMs = parseInt(e.target.value) || 50;
    if (isPlaying) {
      startPlaying();
    }
  });

  startPlaying();
})();
