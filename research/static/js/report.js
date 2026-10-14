// Report Page Charting Controller (Claude Design System)
(function () {
  const runId = window.REPORT_RUN_ID;
  const attackStartTick = window.ATTACK_START_TICK;
  const dailyValRates = window.DAILY_VAL_RATES || [];

  // Plugin to shade the attack window on the full history chart
  const attackWindowShadingPlugin = {
    id: "attackWindowShading",
    beforeDraw(chart) {
      if (attackStartTick == null) return;
      const {
        ctx,
        chartArea,
        scales: { x },
      } = chart;
      if (!chartArea) return;

      const xStart = x.getPixelForValue(attackStartTick);
      const xEnd = chartArea.right;

      if (xStart >= chartArea.left && xStart <= chartArea.right) {
        ctx.save();
        // Soft warm terracotta shading
        ctx.fillStyle = "rgba(198, 97, 63, 0.08)";
        ctx.fillRect(xStart, chartArea.top, xEnd - xStart, chartArea.bottom - chartArea.top);

        // Dashed border indicator
        ctx.strokeStyle = "rgba(198, 97, 63, 0.55)";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(xStart, chartArea.top);
        ctx.lineTo(xStart, chartArea.bottom);
        ctx.stroke();

        // Label
        ctx.fillStyle = "#c6613f";
        ctx.font = "bold 11px -apple-system, system-ui, sans-serif";
        ctx.fillText("⚡ Attack Phase Active", xStart + 8, chartArea.top + 18);
        ctx.restore();
      }
    },
  };

  async function loadFullHistory() {
    try {
      const resp = await fetch(`/api/simulations/${runId}/history`);
      if (!resp.ok) return;
      const data = await resp.json();
      const history = data.history || [];

      const labels = history.map((r) => r.tick);
      const actualPrices = history.map((r) => r.actual_price);
      const predictedPrices = history.map((r) => r.predicted_price);

      const ctxFull = document.getElementById("fullPriceChart").getContext("2d");
      new Chart(ctxFull, {
        type: "line",
        data: {
          labels: labels,
          datasets: [
            {
              label: "Known Actual Price",
              data: actualPrices,
              borderColor: "#141413",
              borderWidth: 1.8,
              pointRadius: 0,
              tension: 0.1,
            },
            {
              label: "Crowd Predicted Price",
              data: predictedPrices,
              borderColor: "#c6613f",
              borderWidth: 2.2,
              pointRadius: 0,
              tension: 0.1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            mode: "index",
            intersect: false,
          },
          scales: {
            x: {
              grid: { color: "rgba(230, 228, 218, 0.7)" },
              ticks: { color: "#73726c", maxTicksLimit: 14, font: { size: 11 } },
              title: { display: true, text: "Hourly Tick Index (Attack phase shaded)", color: "#73726c", font: { size: 12 } },
            },
            y: {
              grid: { color: "rgba(230, 228, 218, 0.7)" },
              ticks: { color: "#73726c", callback: (v) => "$" + v, font: { size: 11 } },
              title: { display: true, text: "Price ($ USD)", color: "#73726c", font: { size: 12 } },
            },
          },
          plugins: {
            legend: {
              labels: { color: "#141413", font: { size: 12, weight: "500" }, boxWidth: 14 },
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
        plugins: [attackWindowShadingPlugin],
      });
    } catch (err) {
      console.error("Failed to load full history:", err);
    }
  }

  function renderDailyValidationChart() {
    const ctxVal = document.getElementById("validationRateChart").getContext("2d");
    const labels = dailyValRates.map((d) => `Day ${d.day} ${d.in_attack ? "(Attack)" : "(Seed)"}`);
    const rates = dailyValRates.map((d) => (d.validation_rate * 100).toFixed(1));
    const backgroundColors = dailyValRates.map((d) =>
      d.in_attack ? "rgba(198, 97, 63, 0.75)" : "rgba(47, 125, 79, 0.65)"
    );

    new Chart(ctxVal, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Daily Validation Frequency (%)",
            data: rates,
            backgroundColor: backgroundColors,
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: "#73726c", maxRotation: 45, minRotation: 45, font: { size: 10 } },
          },
          y: {
            grid: { color: "rgba(230, 228, 218, 0.7)" },
            ticks: { color: "#73726c", callback: (v) => v + "%", font: { size: 11 } },
            beginAtZero: true,
            max: 100,
            title: { display: true, text: "Validation Frequency (%)", color: "#73726c", font: { size: 12 } },
          },
        },
        plugins: {
          legend: { labels: { color: "#141413", font: { size: 12 } } },
          tooltip: {
            backgroundColor: "#ffffff",
            titleColor: "#141413",
            bodyColor: "#3d3d3a",
            borderColor: "#d6d3c6",
            borderWidth: 1,
            padding: 10,
            callbacks: {
              label: (ctx) => ` Validation Rate: ${ctx.parsed.y}%`,
            },
          },
        },
      },
    });
  }

  loadFullHistory();
  renderDailyValidationChart();
})();
