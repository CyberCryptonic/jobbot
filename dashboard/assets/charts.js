/* jobbot chart layer — Chart.js 4 (vendored), themed to the validated dark
   palette. Rules baked in from the dataviz method:
   - series colors come from the fixed slots --s1..--s5, assigned in order,
     never cycled; donuts/all-pairs contexts use at most the first three
   - thin marks, rounded data ends, 2px surface gaps between fills
   - recessive hairline grid, muted axis ink, no vertical gridlines on bars
   - hover tooltips by default; legend only when there are 2+ series
   - direct value labels only on short categorical bar lists */

"use strict";

const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const PAL = {
  series: () => [css("--s1"), css("--s2"), css("--s3"), css("--s4"), css("--s5")],
  surface: () => css("--surface"),
  grid: () => "rgba(255,255,255,0.06)",
  muted: () => css("--muted"),
  ink2: () => css("--ink-2"),
  ink: () => css("--ink"),
};

function themeCharts() {
  const C = window.Chart;
  if (!C) return;
  C.defaults.font.family = getComputedStyle(document.body).fontFamily;
  C.defaults.font.size = 12;
  C.defaults.color = PAL.muted();
  C.defaults.borderColor = PAL.grid();
  C.defaults.animation.duration =
    matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 350;
  C.defaults.plugins.legend.display = false;      // legends are our own HTML row
  Object.assign(C.defaults.plugins.tooltip, {
    backgroundColor: "#262421",
    borderColor: "rgba(235,225,210,0.16)",
    borderWidth: 1,
    titleColor: PAL.ink(),
    bodyColor: PAL.ink2(),
    padding: 10,
    cornerRadius: 6,
    boxPadding: 4,
    titleFont: { weight: 600, size: 11.5 },
    bodyFont: { family: '"JetBrains Mono", monospace', size: 11.5 },
    displayColors: true,
    usePointStyle: true,
  });
}

/* value labels at the end of horizontal bars (short categorical lists only) */
const barValueLabels = {
  id: "barValueLabels",
  afterDatasetsDraw(chart, _, opts) {
    if (!opts || !opts.on) return;
    const { ctx } = chart;
    ctx.save();
    ctx.font = '600 10.5px "JetBrains Mono", monospace';
    ctx.fillStyle = PAL.ink2();
    ctx.textBaseline = "middle";
    chart.data.datasets.forEach((ds, di) => {
      const meta = chart.getDatasetMeta(di);
      if (meta.hidden) return;
      meta.data.forEach((bar, i) => {
        const v = ds.data[i];
        if (v == null || v === 0) return;
        const label = opts.fmt ? opts.fmt(v) : String(v);
        if (chart.options.indexAxis === "y") {
          const x = Math.min(bar.x + 6, chart.chartArea.right - ctx.measureText(label).width - 2);
          ctx.textAlign = "left";
          ctx.fillText(label, x, bar.y);
        } else {
          ctx.textAlign = "center";
          ctx.fillText(label, bar.x, bar.y - 9);
        }
      });
    });
    ctx.restore();
  },
};

function legendRow(el, entries) {
  el.innerHTML = entries.map(e =>
    `<span class="k"><span class="swatch" style="background:${e.color}"></span>${esc(e.label)}</span>`).join("");
}

/* vertical grouped bars, 1-2 series (validated pair s1+s2) */
function barsChart(canvas, labels, datasets, { stacked = false, fmtTip } = {}) {
  const s = PAL.series();
  return new Chart(canvas, {
    type: "bar",
    plugins: [barValueLabels],
    data: {
      labels,
      datasets: datasets.map((d, i) => ({
        label: d.label, data: d.data,
        backgroundColor: d.color || s[i],
        borderRadius: { topLeft: 4, topRight: 4 },
        borderSkipped: "bottom",
        maxBarThickness: 22,
        categoryPercentage: 0.72, barPercentage: 0.85,
        borderColor: PAL.surface(), borderWidth: stacked ? 1 : 0,
      })),
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { stacked, grid: { display: false }, border: { display: false },
             ticks: { maxRotation: 0, autoSkipPadding: 8 } },
        y: { stacked, beginAtZero: true, border: { display: false },
             grid: { color: PAL.grid() }, ticks: { precision: 0, maxTicksLimit: 5 } },
      },
      plugins: {
        barValueLabels: { on: false },
        tooltip: fmtTip ? { callbacks: { label: fmtTip } } : {},
      },
    },
  });
}

/* horizontal bars, one measure = one hue; count labels on (short lists) */
function hbarChart(canvas, labels, data, { color, fmt: fmtV, series2 } = {}) {
  const s = PAL.series();
  const datasets = [{
    label: "", data,
    backgroundColor: color || s[0],
    borderRadius: { topRight: 4, bottomRight: 4 },
    borderSkipped: "left",
    maxBarThickness: 16,
    categoryPercentage: series2 ? 0.78 : 0.62, barPercentage: 0.9,
  }];
  if (series2) datasets.push({
    label: series2.label, data: series2.data,
    backgroundColor: series2.color || s[1],
    borderRadius: { topRight: 4, bottomRight: 4 },
    borderSkipped: "left",
    maxBarThickness: 16, categoryPercentage: 0.78, barPercentage: 0.9,
  });
  if (series2) datasets[0].label = series2.firstLabel || "";
  return new Chart(canvas, {
    type: "bar",
    plugins: [barValueLabels],
    data: { labels, datasets },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { beginAtZero: true, grid: { color: PAL.grid() }, border: { display: false },
             ticks: { precision: 0, maxTicksLimit: 6 } },
        y: { grid: { display: false }, border: { display: false },
             ticks: { color: PAL.ink2(), autoSkip: false, font: { size: 11 } } },
      },
      plugins: { barValueLabels: { on: true, fmt: fmtV } },
    },
  });
}

/* line with crosshair-style hover; 2px stroke, hidden points until hover */
function lineChart(canvas, labels, datasets, { fill = false, fmtTip, money = false } = {}) {
  const s = PAL.series();
  return new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: datasets.map((d, i) => ({
        label: d.label, data: d.data,
        borderColor: d.color || s[i], borderWidth: 2,
        backgroundColor: (d.color || s[i]) + "22",
        fill, tension: 0.3,
        pointRadius: 0, pointHoverRadius: 4, pointHitRadius: 14,
        pointBackgroundColor: d.color || s[i],
      })),
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { display: false }, border: { display: false },
             ticks: { maxRotation: 0, autoSkipPadding: 12 } },
        y: { beginAtZero: true, border: { display: false },
             grid: { color: PAL.grid() },
             ticks: { maxTicksLimit: 5,
                      callback: v => money ? "$" + (+v).toFixed(2) : v } },
      },
      plugins: { tooltip: fmtTip ? { callbacks: { label: fmtTip } } : {} },
    },
  });
}

/* donut — all-pairs context: at most the first THREE slots (validated) */
function donutChart(canvas, labels, data, { colors } = {}) {
  const s = PAL.series().slice(0, 3);
  return new Chart(canvas, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: colors || s,
        borderColor: PAL.surface(), borderWidth: 2,   // 2px surface gap between fills
        hoverOffset: 4,
      }],
    },
    options: {
      maintainAspectRatio: false,
      cutout: "68%",
    },
  });
}

document.addEventListener("DOMContentLoaded", themeCharts);
