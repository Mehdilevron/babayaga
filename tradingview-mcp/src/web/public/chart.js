(() => {
  const container = document.getElementById("chart-container");
  const symbolLabel = document.getElementById("symbol-label");
  const timeframeLabel = document.getElementById("timeframe-label");
  const statusLabel = document.getElementById("status-label");

  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#0f1117" }, textColor: "#d1d4dc" },
    grid: { vertLines: { color: "#1f2330" }, horzLines: { color: "#1f2330" } },
    timeScale: { timeVisible: true, secondsVisible: false },
    autoSize: true,
  });

  const series = chart.addCandlestickSeries({
    upColor: "#26a69a",
    downColor: "#ef5350",
    borderVisible: false,
    wickUpColor: "#26a69a",
    wickDownColor: "#ef5350",
  });

  // id -> { def, priceLine?: PriceLine, overlayEl?: HTMLElement }
  const shapes = new Map();

  function namedColorToRgb(color) {
    const probe = document.createElement("div");
    probe.style.color = color;
    document.body.appendChild(probe);
    const computed = getComputedStyle(probe).color; // "rgb(r, g, b)"
    document.body.removeChild(probe);
    const match = computed.match(/\d+/g) || [0, 0, 0];
    return { r: Number(match[0]), g: Number(match[1]), b: Number(match[2]) };
  }

  function toRgba(color, alpha) {
    const { r, g, b } = namedColorToRgb(color);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function renderShape(def) {
    if (def.type === "line") {
      const priceLine = series.createPriceLine({
        price: def.price,
        color: def.color,
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: def.label ?? "",
      });
      shapes.set(def.id, { def, priceLine });
      return;
    }

    const overlayEl = document.createElement("div");
    overlayEl.className = "shape-overlay";
    overlayEl.style.border = `1px solid ${def.color}`;
    overlayEl.style.background = toRgba(def.color, 0.15);
    if (def.label) {
      const labelEl = document.createElement("div");
      labelEl.className = "shape-label";
      labelEl.style.color = def.color;
      labelEl.textContent = def.label;
      overlayEl.appendChild(labelEl);
    }
    container.appendChild(overlayEl);
    shapes.set(def.id, { def, overlayEl });
    repositionRectangle(def.id);
  }

  function removeShape(id) {
    const entry = shapes.get(id);
    if (!entry) return;
    if (entry.priceLine) series.removePriceLine(entry.priceLine);
    if (entry.overlayEl) entry.overlayEl.remove();
    shapes.delete(id);
  }

  function clearAllShapes() {
    for (const id of Array.from(shapes.keys())) removeShape(id);
  }

  function repositionRectangle(id) {
    const entry = shapes.get(id);
    if (!entry || entry.def.type !== "rectangle") return;
    const def = entry.def;
    const top = series.priceToCoordinate(def.priceHigh);
    const bottom = series.priceToCoordinate(def.priceLow);
    if (top == null || bottom == null) {
      entry.overlayEl.style.display = "none";
      return;
    }
    const timeScale = chart.timeScale();
    const containerWidth = container.clientWidth;
    let left = def.fromTime != null ? timeScale.timeToCoordinate(def.fromTime) : 0;
    let right = def.toTime != null ? timeScale.timeToCoordinate(def.toTime) : containerWidth;
    if (left == null) left = 0;
    if (right == null) right = containerWidth;

    entry.overlayEl.style.display = "block";
    entry.overlayEl.style.left = `${Math.min(left, right)}px`;
    entry.overlayEl.style.width = `${Math.abs(right - left)}px`;
    entry.overlayEl.style.top = `${Math.min(top, bottom)}px`;
    entry.overlayEl.style.height = `${Math.abs(bottom - top)}px`;
  }

  function repositionAllRectangles() {
    for (const id of shapes.keys()) repositionRectangle(id);
  }

  chart.timeScale().subscribeVisibleTimeRangeChange(repositionAllRectangles);
  window.addEventListener("resize", () => requestAnimationFrame(repositionAllRectangles));

  function applySnapshot(msg) {
    series.setData(
      msg.candles.map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    clearAllShapes();
    for (const def of msg.shapes) renderShape(def);
    symbolLabel.textContent = msg.symbol;
    timeframeLabel.textContent = msg.timeframe;
    requestAnimationFrame(repositionAllRectangles);
  }

  function connect() {
    const ws = new WebSocket(`ws://${location.host}`);
    ws.onopen = () => {
      statusLabel.textContent = "live";
    };
    ws.onclose = () => {
      statusLabel.textContent = "disconnected, retrying...";
      setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "snapshot":
          applySnapshot(msg);
          break;
        case "shape:add":
          removeShape(msg.shape.id);
          renderShape(msg.shape);
          break;
        case "shape:remove":
          removeShape(msg.id);
          break;
        case "shapes:clear":
          clearAllShapes();
          break;
      }
    };
  }

  connect();
})();
