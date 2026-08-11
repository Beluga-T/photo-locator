/* Reverse Image Location — schematic globe readout.
 *
 * Draws a wireframe globe in orthographic projection, turned so the reported
 * fix sits dead centre facing the viewer. It deliberately carries no coastlines
 * or continent outlines: the app infers a place from pixels alone, and drawing
 * invented geography around that inference would dress a probability up as a
 * survey. A graticule is enough to read hemisphere, latitude band and the tilt
 * of the meridians at a glance, and it cannot be wrong.
 *
 * Colour, stroke width and motion all live in extras.css keyed off the class
 * names emitted here, so both themes and reduced-motion follow the page.
 */
(() => {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const DEG = Math.PI / 180;
  const EARTH_RADIUS_KM = 6371;

  const DEFAULT_SIZE = 156;
  const DEFAULT_RADIUS_KM = 25;
  const GRATICULE_STEP = 15; // degrees between parallels, and between meridians
  const SAMPLE_STEP = 2; // degrees between samples taken along one line
  const MIN_HALO_PX = 5;
  const MAX_HALO_FRACTION = 0.4; // of the disc radius
  const TERMINATOR_STEPS = 12; // bisections used to land a cut on the limb

  // ── Small helpers ────────────────────────────────────────────────────

  function node(name, attributes) {
    const element = document.createElementNS(NS, name);
    Object.keys(attributes).forEach((key) => {
      element.setAttribute(key, attributes[key]);
    });
    return element;
  }

  function toNumber(value, fallback) {
    const parsed = typeof value === "number" ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function clamp(value, low, high) {
    return Math.min(Math.max(value, low), high);
  }

  // Two decimals is well under a device pixel at these sizes and keeps the
  // emitted `d` attributes short enough to stay readable in devtools.
  function round(value) {
    return Math.round(value * 100) / 100;
  }

  function pathFromPoints(points) {
    const commands = points.map(
      (point, index) => (index === 0 ? "M" : "L") + round(point.x) + " " + round(point.y)
    );
    return commands.join(" ");
  }

  // ── Projection ───────────────────────────────────────────────────────

  /* Build an orthographic projector for one viewpoint. The viewpoint's trig is
   * hoisted into the closure because every line samples it hundreds of times. */
  function makeProjector(lat0, lon0, radius, centre) {
    const sinLat0 = Math.sin(lat0);
    const cosLat0 = Math.cos(lat0);

    return function project(lat, lon) {
      const dLon = lon - lon0;
      const sinLat = Math.sin(lat);
      const cosLat = Math.cos(lat);
      const cosDLon = Math.cos(dLon);
      const cosC = sinLat0 * sinLat + cosLat0 * cosLat * cosDLon;

      return {
        x: centre + radius * cosLat * Math.sin(dLon),
        // Screen y grows downward, so the northward component is subtracted.
        y: centre - radius * (cosLat0 * sinLat - sinLat0 * cosLat * cosDLon),
        // cos_c is the cosine of the angle from the viewpoint, so the near
        // hemisphere is exactly where it stays non-negative. Screen position
        // cannot stand in for this test: an antipode plots on top of the fix.
        front: cosC >= 0,
      };
    };
  }

  /* Find the parameter where a line crosses the terminator and return that
   * point. Bisection rather than interpolation so the joint lands on the limb
   * itself; otherwise the front and back halves visibly overlap or gap. */
  function terminator(pointAt, project, tNear, tFar) {
    let low = tNear;
    let high = tFar;
    const lowIsFront = project.apply(null, pointAt(low)).front;

    for (let i = 0; i < TERMINATOR_STEPS; i += 1) {
      const middle = (low + high) / 2;
      if (project.apply(null, pointAt(middle)).front === lowIsFront) low = middle;
      else high = middle;
    }
    return project.apply(null, pointAt((low + high) / 2));
  }

  /* Walk a parametrised line in equal steps and return it as runs of points
   * that share a visibility, so each run can be drawn with its own class. */
  function sampleLine(pointAt, project, steps) {
    const runs = [];
    let current = null;
    let previousT = 0;

    for (let i = 0; i <= steps; i += 1) {
      const t = i / steps;
      const point = project.apply(null, pointAt(t));

      if (!current) {
        current = { front: point.front, points: [point] };
      } else if (point.front === current.front) {
        current.points.push(point);
      } else {
        const edge = terminator(pointAt, project, previousT, t);
        current.points.push(edge);
        runs.push(current);
        current = { front: point.front, points: [edge, point] };
      }
      previousT = t;
    }

    if (current && current.points.length > 1) runs.push(current);
    return runs;
  }

  // ── Line generators ──────────────────────────────────────────────────

  function parallelAt(latDeg) {
    const lat = latDeg * DEG;
    return (t) => [lat, (t * 360 - 180) * DEG];
  }

  function meridianAt(lonDeg) {
    const lon = lonDeg * DEG;
    return (t) => [(t * 180 - 90) * DEG, lon];
  }

  // ── Public API ───────────────────────────────────────────────────────

  window.RIL = window.RIL || {};

  window.RIL.createGlobe = function createGlobe(options) {
    const config = options || {};

    // A NaN latitude would collapse the whole graticule, so an unusable fix
    // falls back to the Gulf of Guinea null island rather than an empty disc.
    const lat0 = clamp(toNumber(config.lat, 0), -90, 90) * DEG;
    const lon0 = toNumber(config.lon, 0) * DEG;
    const radiusKm = Math.max(0, toNumber(config.radiusKm, DEFAULT_RADIUS_KM));

    let size = toNumber(config.size, DEFAULT_SIZE);
    if (!(size > 0)) size = DEFAULT_SIZE;

    const centre = size / 2;
    // Inset by a hairline so the limb stroke is not clipped by an ancestor
    // that happens to hide its overflow.
    const radius = centre - 1;
    const project = makeProjector(lat0, lon0, radius, centre);

    const back = []; // far-side runs, laid down first so front lines sit on top
    const front = [];

    function addLine(pointAt, steps, frontClass) {
      sampleLine(pointAt, project, steps).forEach((run) => {
        (run.front ? front : back).push(
          node("path", {
            class: run.front ? frontClass : "globe__grid globe__grid--back",
            d: pathFromPoints(run.points),
          })
        );
      });
    }

    const parallelSteps = 360 / SAMPLE_STEP;
    const meridianSteps = 180 / SAMPLE_STEP;

    for (let lat = -90 + GRATICULE_STEP; lat <= 90 - GRATICULE_STEP; lat += GRATICULE_STEP) {
      if (lat !== 0) addLine(parallelAt(lat), parallelSteps, "globe__grid");
    }
    for (let lon = -180; lon < 180; lon += GRATICULE_STEP) {
      addLine(meridianAt(lon), meridianSteps, "globe__grid");
    }
    // Added last so the emphasised equator overprints the plain graticule.
    addLine(parallelAt(0), parallelSteps, "globe__equator");

    // The uncertainty ring is a small circle centred on the viewpoint, so its
    // orthographic image is a circle of R·sin(angular radius). At city scale
    // that is a fraction of a pixel, hence the floor: the ring reports the
    // order of magnitude of the claim, it is not a scale drawing of it.
    const haloRadius = clamp(
      radius * Math.sin(radiusKm / EARTH_RADIUS_KM),
      MIN_HALO_PX,
      radius * MAX_HALO_FRACTION
    );
    const markRadius = Math.max(1.5, size * 0.019);
    const tickReach = markRadius * 3.2;

    const svg = node("svg", {
      class: "globe",
      viewBox: "0 0 " + size + " " + size,
      width: size,
      height: size,
      overflow: "visible",
      "aria-hidden": "true",
    });

    svg.append(
      ...back,
      ...front,
      node("circle", { class: "globe__limb", cx: centre, cy: centre, r: round(radius) }),
      node("circle", { class: "globe__halo", cx: centre, cy: centre, r: round(haloRadius) }),
      node("circle", { class: "globe__pulse", cx: centre, cy: centre, r: round(haloRadius) }),
      node("line", {
        class: "globe__tick",
        x1: round(centre - tickReach),
        y1: centre,
        x2: round(centre + tickReach),
        y2: centre,
      }),
      node("line", {
        class: "globe__tick",
        x1: centre,
        y1: round(centre - tickReach),
        x2: centre,
        y2: round(centre + tickReach),
      }),
      node("circle", { class: "globe__mark", cx: centre, cy: centre, r: round(markRadius) })
    );

    return svg;
  };
})();
