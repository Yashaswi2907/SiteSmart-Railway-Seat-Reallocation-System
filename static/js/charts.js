/* Chart.js defaults shared by every dashboard.
   Categorical order validated for lightness, chroma and colour-blind separation. */
(function () {
  "use strict";
  if (!window.Chart) return;
  const SS = (window.SS = window.SS || {});
  const CATEGORICAL = ["#1F5FBF", "#D97706", "#0D9488", "#7C5CC4", "#DB2777", "#65A30D"];
  const STATUS = { good: "#15803D", warning: "#B45309", critical: "#B91C1C", neutral: "#94A3B8", info: "#1F5FBF" };
  const INK = "#334155", MUTED = "#64748B", GRID = "#EEF2F7", SURFACE = "#FFFFFF";

  Chart.defaults.font.family = '"Inter", system-ui, sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = MUTED;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.pointStyle = "rectRounded";
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.legend.labels.color = INK;
  Chart.defaults.plugins.tooltip.backgroundColor = "#0A1B33";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.titleFont = { weight: "600" };
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation.duration = 450;

  const axes = (yTitle, { percent = false, stacked = false } = {}) => ({
    x: { stacked, grid: { display: false }, border: { color: GRID }, ticks: { color: MUTED, maxRotation: 0, autoSkipPadding: 12 } },
    y: { stacked, beginAtZero: true, grid: { color: GRID }, border: { display: false },
         ticks: { color: MUTED, precision: 0, callback: percent ? (v) => v + "%" : undefined },
         title: yTitle ? { display: true, text: yTitle, color: MUTED, font: { size: 11 } } : undefined,
         suggestedMax: percent ? 25 : undefined },
  });

  SS.charts = {
    CATEGORICAL, STATUS,
    bar(canvas, labels, datasets, { yTitle, percent, stacked, horizontal } = {}) {
      return new Chart(canvas, {
        type: "bar",
        data: {
          labels,
          datasets: datasets.map((d, i) => ({
            borderRadius: 4, borderSkipped: "start", borderWidth: 0, maxBarThickness: 28,
            categoryPercentage: 0.7, barPercentage: 0.85,
            backgroundColor: d.color || CATEGORICAL[i], ...d,
          })),
        },
        options: {
          indexAxis: horizontal ? "y" : "x",
          scales: horizontal ? (() => { const a = axes(yTitle, { percent, stacked }); return { x: { ...a.y, title: undefined }, y: { ...a.x } }; })() : axes(yTitle, { percent, stacked }),
          plugins: {
            legend: { display: datasets.length > 1, position: "top", align: "end" },
            tooltip: { callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ctx.formattedValue}${percent ? "%" : ""}` } },
          },
          interaction: { mode: "index", intersect: false },
        },
      });
    },
    doughnut(canvas, labels, values, colors) {
      const total = values.reduce((a, b) => a + b, 0);
      return new Chart(canvas, {
        type: "doughnut",
        data: { labels, datasets: [{ data: values, backgroundColor: colors || CATEGORICAL, borderColor: SURFACE, borderWidth: 2, hoverOffset: 4 }] },
        options: {
          cutout: "68%",
          plugins: {
            legend: { position: "right", labels: { generateLabels: (chart) => Chart.overrides.doughnut.plugins.legend.labels.generateLabels(chart).map((l, i) => ({ ...l, text: `${l.text}  ${values[i]}` })) } },
            tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.parsed} (${total ? Math.round(ctx.parsed / total * 100) : 0}%)` } },
          },
        },
      });
    },
    line(canvas, labels, datasets, { yTitle } = {}) {
      return new Chart(canvas, {
        type: "line",
        data: {
          labels,
          datasets: datasets.map((d, i) => ({
            borderWidth: 2, tension: 0.3, pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 12,
            pointBackgroundColor: d.color || CATEGORICAL[i], pointBorderColor: SURFACE, pointBorderWidth: 2,
            borderColor: d.color || CATEGORICAL[i], backgroundColor: (d.color || CATEGORICAL[i]) + "14", fill: d.fill ?? false, ...d,
          })),
        },
        options: {
          scales: axes(yTitle),
          interaction: { mode: "index", intersect: false },
          plugins: { legend: { display: datasets.length > 1, position: "top", align: "end" } },
        },
      });
    },
  };
})();
