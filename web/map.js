/* ═══════════════════════════════════════════════════════════════════
   Reverse Image Location — map readout

   Three tiers, tried in order, because a location claim has to stay
   legible when the network, the CDN or the token says no:

     1  interactive Mapbox GL JS, uncertainty circle drawn on top
     2  a flat Static Images API frame, when GL JS never arrived
     3  a one-line notice, when there is no MAPBOX_TOKEN at all

   Tier 3 stays quiet on purpose: app.js already falls back to its own
   schematic globe, which owes nothing to a vendor.

   Nothing here is imported or bundled — the module hangs itself off
   window.RIL and injects the GL bundle lazily, once per page. Colour and
   radius come from the tokens in styles.css, so both themes follow for
   free. Text is written with textContent only.
   ═══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  /* Mapbox GL JS is loaded from Mapbox's own CDN. Both URLs are built from
   * GL_VERSION, so the version is written down in exactly one place.
   *
   * It is deliberately not vendored into this repository, unlike Motion. Motion
   * is MIT and may be redistributed; GL JS is licensed under the Mapbox Terms
   * of Service, so committing its 1.5 MB bundle to a public repo would be
   * redistributing their SDK — and would put 1.5 MB into every clone. Serving
   * it from api.mapbox.com is both what the terms contemplate and what every
   * comparable project does. Nothing is lost in practice: the map needs Mapbox
   * tiles and a token to draw anything at all, so this panel could never work
   * with api.mapbox.com unreachable regardless of where the script came from. */
  const GL_VERSION = "3.9.0";
  const GL_CSS = `https://api.mapbox.com/mapbox-gl-js/v${GL_VERSION}/mapbox-gl.css`;
  const GL_JS = `https://api.mapbox.com/mapbox-gl-js/v${GL_VERSION}/mapbox-gl.js`;

  /* A deadline on that fetch, not a performance budget. Measured cold-cache in
   * a real browser, the script lands in 116 ms and the map is interactive at
   * 422 ms — an ordinary connection is nowhere near this number. It is here for
   * connections far worse than that one, and for the case where the request is
   * never refused and never answered either (captive portal, filtering proxy),
   * which has no error event to listen for. Missing it is a deliberate outcome
   * rather than a failure: the reader drops to the static-image tier, which
   * still shows the location, and is told on screen that it does not pan. */
  const GL_TIMEOUT_MS = 20000;

  const DEG = Math.PI / 180;
  const EARTH_RADIUS_KM = 6371;
  const RING_VERTICES = 96;
  const DEFAULT_RADIUS_KM = 25;
  const FIT_PADDING = 36;
  const FIT_MAX_ZOOM = 13;

  const SRC = "ril-uncertainty";
  const LYR_FILL = "ril-uncertainty-fill";
  const LYR_EDGE = "ril-uncertainty-edge";

  // Only reached when --fix resolves to something that is not a plain hex:
  // the Static Images API takes a bare hex triplet and nothing else.
  const FALLBACK_FIX_HEX = "e5487f";

  // ── Small helpers ────────────────────────────────────────────────────

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null && text !== "") node.textContent = String(text);
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function toNumber(value, fallback) {
    const parsed = typeof value === "number" ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function clamp(value, low, high) {
    return Math.min(Math.max(value, low), high);
  }

  // ── Theme ────────────────────────────────────────────────────────────

  /* The attribute app.js writes wins; without it we are on the OS default.
   * Same resolution order as toggleTheme() so the two can never disagree. */
  function currentTheme() {
    return (
      document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")
    );
  }

  function styleForTheme(theme) {
    return theme === "light"
      ? "mapbox://styles/mapbox/light-v11"
      : "mapbox://styles/mapbox/dark-v11";
  }

  /* The accent is a CSS variable, and GL paint properties are not, so it has
   * to be read at paint time rather than baked in at load time. */
  function readAccent() {
    try {
      const raw = getComputedStyle(document.documentElement).getPropertyValue("--fix").trim();
      return raw || `#${FALLBACK_FIX_HEX}`;
    } catch {
      return `#${FALLBACK_FIX_HEX}`;
    }
  }

  function accentHex() {
    const raw = readAccent().replace(/^#/, "");
    return /^(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(raw) ? raw : FALLBACK_FIX_HEX;
  }

  // ── Geometry ─────────────────────────────────────────────────────────

  /* Spherical destination formula, walked once per vertex. Turf would pull a
   * geodesy library in for this alone; the closed form is six lines. The ring
   * is left unwrapped around the centre longitude — normalising into
   * [-180, 180] would tear any circle straddling the antimeridian. */
  function circleRing(lat, lon, radiusKm, vertices) {
    // Exactly at a pole cos(lat) collapses to ~1e-16 and both atan2 arguments
    // vanish, leaving the ring's longitudes numerically arbitrary. Backing off
    // a ten-thousandth of a degree costs ~11 m and keeps the maths well posed.
    lat = clamp(lat, -89.9999, 89.9999);
    const lat1 = lat * DEG;
    const lon1 = lon * DEG;
    const angular = radiusKm / EARTH_RADIUS_KM;
    const sinLat1 = Math.sin(lat1);
    const cosLat1 = Math.cos(lat1);
    const sinD = Math.sin(angular);
    const cosD = Math.cos(angular);
    const ring = [];

    for (let i = 0; i <= vertices; i += 1) {
      const bearing = (i / vertices) * 2 * Math.PI;
      const lat2 = Math.asin(sinLat1 * cosD + cosLat1 * sinD * Math.cos(bearing));
      const lon2 =
        lon1 +
        Math.atan2(Math.sin(bearing) * sinD * cosLat1, cosD - sinLat1 * Math.sin(lat2));
      ring.push([lon2 / DEG, lat2 / DEG]);
    }
    return ring; // last vertex repeats the first: GeoJSON wants a closed ring
  }

  function ringBounds(ring) {
    let west = Infinity;
    let south = Infinity;
    let east = -Infinity;
    let north = -Infinity;
    for (const [x, y] of ring) {
      if (x < west) west = x;
      if (x > east) east = x;
      if (y < south) south = y;
      if (y > north) north = y;
    }
    return [[west, south], [east, north]];
  }

  // ── Lazy GL loader ───────────────────────────────────────────────────

  /* Memoised on window.RIL so a page with several readouts injects one copy.
   * The promise rejects on error or after GL_TIMEOUT_MS — a hung CDN must not
   * leave the reader staring at an empty box forever, it must drop a tier. */
  function loadMapboxGl() {
    if (window.RIL.__mapboxGl) return window.RIL.__mapboxGl;

    const pending = new Promise((resolve, reject) => {
      if (window.mapboxgl) {
        resolve(window.mapboxgl);
        return;
      }

      // The stylesheet carries the canvas and control layout. Its load is not
      // awaited: a missing stylesheet is ugly, a missing script is fatal.
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = GL_CSS;
      document.head.append(link);

      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (error || !window.mapboxgl) reject(error || new Error("mapbox-gl unavailable"));
        else resolve(window.mapboxgl);
      };

      const timer = setTimeout(() => finish(new Error("mapbox-gl timed out")), GL_TIMEOUT_MS);

      const script = document.createElement("script");
      script.src = GL_JS;
      script.async = true;
      script.addEventListener("load", () => finish(null));
      script.addEventListener("error", () => finish(new Error("mapbox-gl blocked")));
      document.head.append(script);
    });

    // A rejection must not be cached: the usual cause is the deadline above
    // expiring on a slow connection, and caching it would pin every later map
    // to the static tier for the life of the page. Forget the failure and let
    // the next call re-check window.mapboxgl, which by then may well be there.
    window.RIL.__mapboxGl = pending;
    pending.catch((error) => {
      if (window.RIL.__mapboxGl === pending) window.RIL.__mapboxGl = null;
      // Falling back is otherwise invisible: the static tier draws something
      // that looks like a map, so "why can't I drag it" has no answer without
      // this line.
      console.warn(
        "[RIL] Mapbox GL did not load from %s (%s) — falling back to a static " +
          "image, which cannot be panned or zoomed.",
        GL_JS,
        (error && error.message) || "unknown"
      );
    });

    return pending;
  }

  // ── Public API ───────────────────────────────────────────────────────

  window.RIL = window.RIL || {};

  /* Zoom bands rather than a formula: the radius is itself a coarse estimate,
   * and a continuous curve would imply a precision the model never claimed. */
  window.RIL.zoomForRadius = function zoomForRadius(radiusKm) {
    const km = toNumber(radiusKm, DEFAULT_RADIUS_KM);
    if (!(km > 0)) return 12;
    if (km <= 2) return 12;
    if (km <= 10) return 10.5;
    if (km <= 50) return 8.5;
    if (km <= 200) return 6.5;
    if (km <= 800) return 4.5;
    return 3;
  };

  window.RIL.createMap = function createMap(options) {
    const config = options || {};
    const lat = clamp(toNumber(config.lat, 0), -90, 90);
    const lon = toNumber(config.lon, 0);
    const radiusKm = Math.max(0.1, toNumber(config.radiusKm, DEFAULT_RADIUS_KM));
    const token = typeof config.token === "string" ? config.token.trim() : "";
    const zoom = window.RIL.zoomForRadius(radiusKm);

    const container = el("div", "map");
    const canvas = el("div", "map__canvas");
    const foot = el("div", "map__foot");
    foot.append(
      el("span", "map__stat", `${lat.toFixed(4)}, ${lon.toFixed(4)}`),
      el("span", "map__stat", `± ${Math.round(radiusKm)} KM`)
    );
    if (config.label) foot.append(el("span", "map__stat map__stat--name", String(config.label)));
    container.append(canvas, foot);

    // Teardown is wired before any tier runs, so app.js can clear the readout
    // mid-load without leaving a half-built map attached to the document.
    let teardown = null;
    let disposed = false;
    container.__rilDestroy = () => {
      disposed = true;
      const run = teardown;
      teardown = null;
      try {
        if (run) run();
      } catch {
        /* already gone */
      }
    };

    /* Two different dead ends land here, and telling them apart matters: one is
     * a missing setting the reader can fix, the other is a blocked network. */
    function tierNone(reason) {
      clear(canvas);
      const message =
        reason === "blocked"
          ? "地图服务连不上，可能是网络或令牌受限。坐标见下方。"
          : "还没有 Mapbox 令牌：设置 → 地图 里粘贴一个免费的 pk. 令牌即可启用交互地图。";
      canvas.append(el("p", "map__none", message));
    }

    function tierStatic() {
      clear(canvas);
      const image = el("img", "map__static");
      const centre = `${lon.toFixed(5)},${lat.toFixed(5)}`;
      // No circle primitive exists on the Static API, so the pin plus the zoom
      // band is the honest maximum: the ± label under it carries the radius.
      image.src =
        `https://api.mapbox.com/styles/v1/mapbox/${currentTheme() === "light" ? "light-v11" : "dark-v11"}` +
        `/static/pin-l+${accentHex()}(${centre})/${centre},${zoom},0/640x420@2x` +
        `?access_token=${encodeURIComponent(token)}`;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => tierNone("blocked"), { once: true });
      canvas.append(image);
      addStaticAttribution();

      // Say it on screen too. A flat picture where an interactive map is
      // expected reads as a broken map, not as a fallback.
      if (!foot.querySelector(".map__degraded")) {
        foot.prepend(el("span", "map__stat map__degraded", "静态图 · 不可缩放拖动"));
      }
    }

    /* The static frame has no attribution control, and although the API bakes
     * the credit into the image, it is small and easy to miss. Mapbox requires
     * it either way, so state it in text too — once. */
    function addStaticAttribution() {
      if (foot.querySelector(".map__attrib")) return;
      const credit = el("span", "map__attrib");
      const mapbox = el("a", null, "© Mapbox");
      mapbox.href = "https://www.mapbox.com/about/maps/";
      const osm = el("a", null, "© OpenStreetMap");
      osm.href = "https://www.openstreetmap.org/about/";
      for (const link of [mapbox, osm]) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      credit.append(mapbox, document.createTextNode(" "), osm);
      foot.append(credit);
    }

    function tierInteractive(gl) {
      const ring = circleRing(lat, lon, radiusKm, RING_VERTICES);
      const feature = {
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [ring] },
      };

      gl.accessToken = token;
      const map = new gl.Map({
        container: canvas,
        style: styleForTheme(currentTheme()),
        center: [lon, lat],
        zoom,
        attributionControl: true,
        // Zooming has to work on the first gesture. cooperativeGestures would
        // require ctrl+wheel, which protects the page's scroll but reads as a
        // broken map — and inspecting where a photo was taken is the whole
        // point of this panel. The map does swallow the wheel while the cursor
        // is over it; fullscreen below is the escape hatch for real inspection.
        cooperativeGestures: false,
        // Rotation and pitch add nothing to reading a location off a map and
        // make it easy to end up somewhere disorienting with no obvious way
        // back. Zoom and pan, nothing else.
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
      });

      // Registered before anything else can throw. A WebGL context now exists,
      // and if the rest of this function fails the map still has to be
      // reclaimable — otherwise the context leaks with nothing holding it.
      teardown = () => map.remove();

      // Every gesture this panel wants, turned on by name rather than left to
      // the library's defaults. Defaults are the right value today, but "the
      // map does not drag" is a bug report with no stack trace and no console
      // error, so the setting that governs it should be visible in this file.
      map.dragPan.enable();
      map.scrollZoom.enable();
      map.doubleClickZoom.enable();
      map.boxZoom.enable();
      map.keyboard.enable();
      map.touchZoomRotate.enable();
      map.touchZoomRotate.disableRotation();

      // Handle for debugging and for the browser tests: the instance is
      // otherwise unreachable once createMap returns the container.
      container.__rilMap = map;

      map.addControl(new gl.NavigationControl({ showCompass: false }), "top-right");
      if (typeof gl.FullscreenControl === "function") {
        map.addControl(new gl.FullscreenControl({ container: container }), "top-right");
      }
      map.addControl(new gl.ScaleControl({ unit: "metric" }), "bottom-left");

      /* setStyle wipes every source and layer, so the circle is re-added on
       * each style load rather than only on the first one. */
      function paintCircle() {
        if (!map.getSource(SRC)) map.addSource(SRC, { type: "geojson", data: feature });
        const accent = readAccent();
        if (!map.getLayer(LYR_FILL)) {
          map.addLayer({
            id: LYR_FILL,
            type: "fill",
            source: SRC,
            paint: { "fill-color": accent, "fill-opacity": 0.12 },
          });
        }
        if (!map.getLayer(LYR_EDGE)) {
          map.addLayer({
            id: LYR_EDGE,
            type: "line",
            source: SRC,
            paint: {
              "line-color": accent,
              "line-width": 1.25,
              "line-dasharray": [2, 2],
            },
          });
        }
      }

      const pin = el("div", "map__pin");
      pin.append(el("span", "map__pin-dot"), el("span", "map__pin-ring"));

      // Mapbox dispatches this outside our promise chain, so a throw in here
      // would surface as an uncaught exception rather than a dropped tier.
      map.on("load", () => {
        try {
          paintCircle();
          new gl.Marker({ element: pin }).setLngLat([lon, lat]).addTo(map);
          // Frame the whole uncertainty circle, never the centre alone: a tight
          // zoom onto a ±200 km guess would read as a street address.
          map.fitBounds(ringBounds(ring), {
            padding: FIT_PADDING,
            maxZoom: FIT_MAX_ZOOM,
            duration: 0,
          });
        } catch {
          /* the basemap is still readable without the overlay */
        }
      });

      let applied = currentTheme();
      const retheme = () => {
        const next = currentTheme();
        if (next === applied) return;
        applied = next;
        try {
          map.setStyle(styleForTheme(next));
          // Fires later, on Mapbox's own dispatch — guard it separately.
          map.once("style.load", () => {
            try {
              paintCircle();
            } catch {
              /* the overlay is lost, the basemap is not */
            }
          });
        } catch {
          /* keep the stale basemap rather than blanking the readout */
        }
      };

      const observer = new MutationObserver(retheme);
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });
      // The observer only sees explicit toggles; an OS-level switch while the
      // attribute is absent arrives here instead.
      const media = matchMedia("(prefers-color-scheme: light)");
      if (typeof media.addEventListener === "function") media.addEventListener("change", retheme);

      teardown = () => {
        observer.disconnect();
        if (typeof media.removeEventListener === "function") {
          media.removeEventListener("change", retheme);
        }
        map.remove();
      };

      // Cleared while GL was still downloading — build nothing, keep nothing.
      if (disposed) container.__rilDestroy();
    }

    if (!token) {
      // Falsy token means no request of any kind leaves the page.
      tierNone();
      return container;
    }

    loadMapboxGl()
      .then((gl) => {
        if (disposed) return;
        try {
          tierInteractive(gl);
        } catch (error) {
          // A GL map may already exist and hold a WebGL context. Reclaim it
          // before dropping a tier, or it leaks with nothing referencing it.
          if (teardown) {
            try {
              teardown();
            } catch {
              /* already gone */
            }
            teardown = null;
          }
          throw error;
        }
      })
      .catch(() => {
        if (disposed) return;
        try {
          tierStatic();
        } catch {
          tierNone("blocked");
        }
      });

    return container;
  };
})();
