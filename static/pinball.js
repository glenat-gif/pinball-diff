/* A small pinball table for the /play/ page. Two flippers, three pops, two slings, an orbit
   round the top, two ramps. Plain canvas, no libraries. Table units are 400 wide by 700 tall
   and the canvas scales to fit. Keys: left and right arrows, Z and /, or shift keys for the
   flippers, space or the down arrow to launch. Touch: tap the left or right half, tap the
   shooter lane to launch. */
(function () {
  "use strict";
  var canvas = document.getElementById("table"), ctx = canvas.getContext("2d");
  var W = 400, H = 700, R = 9;                       // table size, ball radius
  var G = 1500, DT = 1 / 240, SUB = 4;               // gravity, physics step, substeps per frame
  var ORANGE = "#ff7a1a", DIM = "#7a3a12", PAPER = "#f4efe4";

  // ---------- geometry ----------
  function seg(x1, y1, x2, y2, kind) { return { x1: x1, y1: y1, x2: x2, y2: y2, kind: kind || "wall" }; }
  var walls = [
    seg(20, 160, 20, 700),                                   // left wall, open at the bottom: the outlane drains
    seg(60, 520, 60, 610), seg(60, 610, 122, 650),           // left outlane divider and inlane guide
    seg(350, 200, 350, 540), seg(350, 540, 278, 650),        // shooter lane guide and right funnel
    seg(380, 160, 380, 660), seg(350, 660, 380, 660),        // shooter lane outer wall and floor
    seg(20, 160, 60, 120), seg(340, 120, 380, 160),          // corners up to the top arc
    seg(60, 120, 340, 120)                                   // a straight top (the arc is drawn as segments below)
  ];
  // the orbit: an arc across the top, as short segments
  (function () {
    var cx = 200, cy = 190, r = 182, n = 22, prev = null;
    for (var i = 0; i <= n; i++) {
      var a = Math.PI + (Math.PI * i / n), x = cx + r * Math.cos(a), y = cy + r * Math.sin(a);
      if (prev) walls.push(seg(prev[0], prev[1], x, y));
      prev = [x, y];
    }
    walls.splice(walls.length - n - 3, 3);                   // the arc replaces the corner and straight-top lines
  })();
  var slings = [
    [[90, 470], [125, 580], [90, 580]],
    [[300, 470], [265, 580], [300, 580]]
  ];
  slings.forEach(function (t) {
    for (var i = 0; i < 3; i++) { var a = t[i], b = t[(i + 1) % 3]; walls.push(seg(a[0], a[1], b[0], b[1], "sling")); }
  });
  var pops = [{ x: 150, y: 270, r: 17 }, { x: 240, y: 240, r: 17 }, { x: 205, y: 340, r: 17 }];
  pops.forEach(function (p) { p.hit = 0; });
  // ramps: enter the mouth travelling upwards, ride the path, exit on an inlane
  var ramps = [
    { mouth: { x: 110, y: 420, r: 16 }, path: [[110, 420], [95, 300], [120, 170], [200, 150], [280, 170], [300, 260], [300, 400], [320, 560]], exit: [-160, 260], score: 1000, name: "LEFT RAMP" },
    { mouth: { x: 290, y: 440, r: 16 }, path: [[290, 440], [305, 320], [290, 200], [200, 180], [110, 200], [90, 300], [90, 420], [70, 560]], exit: [160, 260], score: 1000, name: "RIGHT RAMP" }
  ];
  var orbit = { x: 200, y: 32, r: 26, score: 500, name: "ORBIT" };   // crossing the top of the arc

  var flippers = [
    { px: 128, py: 652, len: 66, rest: 0.52, up: -0.55, dir: 1, a: 0.52, w: 0, key: false },
    { px: 272, py: 652, len: 66, rest: Math.PI - 0.52, up: Math.PI + 0.55, dir: -1, a: Math.PI - 0.52, w: 0, key: false }
  ];

  // ---------- state ----------
  var ball, balls, score, best, state, msg, msgUntil, ride, combo;
  try { best = +localStorage.getItem("ptw-best") || 0; } catch (e) { best = 0; }
  function newBall() { ball = { x: 365, y: 620, vx: 0, vy: 0, inLane: true }; ride = null; }
  function start() { balls = 3; score = 0; combo = 0; state = "play"; newBall(); say("PULL THE PLUNGER", 3); }
  function say(t, secs) { msg = t; msgUntil = performance.now() + secs * 1000; }
  state = "attract"; balls = 0; score = 0; say("PRESS SPACE OR TAP TO PLAY", 9999);

  // ---------- physics ----------
  function hitSeg(s, bounce) {
    var dx = s.x2 - s.x1, dy = s.y2 - s.y1, L2 = dx * dx + dy * dy;
    var t = Math.max(0, Math.min(1, ((ball.x - s.x1) * dx + (ball.y - s.y1) * dy) / L2));
    var cx = s.x1 + t * dx, cy = s.y1 + t * dy, ex = ball.x - cx, ey = ball.y - cy, d = Math.sqrt(ex * ex + ey * ey);
    if (d >= R || d === 0) return false;
    var nx = ex / d, ny = ey / d;
    ball.x = cx + nx * R; ball.y = cy + ny * R;
    var vn = ball.vx * nx + ball.vy * ny;
    if (vn < 0) { ball.vx -= (1 + bounce) * vn * nx; ball.vy -= (1 + bounce) * vn * ny; }
    return true;
  }
  function hitFlipper(f) {
    var tx = f.px + f.len * Math.cos(f.a), ty = f.py + f.len * Math.sin(f.a);
    var s = seg(f.px, f.py, tx, ty), dx = s.x2 - s.x1, dy = s.y2 - s.y1, L2 = dx * dx + dy * dy;
    var t = Math.max(0, Math.min(1, ((ball.x - s.x1) * dx + (ball.y - s.y1) * dy) / L2));
    var cx = s.x1 + t * dx, cy = s.y1 + t * dy, ex = ball.x - cx, ey = ball.y - cy, d = Math.sqrt(ex * ex + ey * ey);
    var thick = R + 7;
    if (d >= thick || d === 0) return;
    var nx = ex / d, ny = ey / d;
    ball.x = cx + nx * thick; ball.y = cy + ny * thick;
    // the flipper's own speed at the contact point, perpendicular to the flipper
    var arm = t * f.len, fvx = -Math.sin(f.a) * f.w * arm, fvy = Math.cos(f.a) * f.w * arm;
    var rvx = ball.vx - fvx, rvy = ball.vy - fvy, vn = rvx * nx + rvy * ny;
    if (vn < 0) { ball.vx = rvx - 1.6 * vn * nx + fvx; ball.vy = rvy - 1.6 * vn * ny + fvy; }
  }
  function step() {
    // flippers
    flippers.forEach(function (f) {
      var target = f.key ? f.up : f.rest, prev = f.a, speed = 26;
      if (f.a < target) f.a = Math.min(target, f.a + speed * DT); else f.a = Math.max(target, f.a - speed * DT);
      f.w = (f.a - prev) / DT;
    });
    if (state !== "play") return;
    if (ride) {                                              // on a ramp: follow the path
      ride.t += DT * 1.6;
      var p = ride.ramp.path, i = Math.min(p.length - 2, Math.floor(ride.t * (p.length - 1))), u = ride.t * (p.length - 1) - i;
      ball.x = p[i][0] + (p[i + 1][0] - p[i][0]) * u; ball.y = p[i][1] + (p[i + 1][1] - p[i][1]) * u;
      if (ride.t >= 1) { ball.vx = ride.ramp.exit[0]; ball.vy = ride.ramp.exit[1]; ride = null; }
      return;
    }
    ball.vy += G * DT;
    var sp = Math.sqrt(ball.vx * ball.vx + ball.vy * ball.vy), MAX = 1500;
    if (sp > MAX) { ball.vx *= MAX / sp; ball.vy *= MAX / sp; }
    ball.x += ball.vx * DT; ball.y += ball.vy * DT;
    walls.forEach(function (s) {
      if (hitSeg(s, s.kind === "sling" ? 0.2 : 0.45) && s.kind === "sling") {
        var mx = (s.x1 + s.x2) / 2, my = (s.y1 + s.y2) / 2, cx = ball.x - mx, cy = ball.y - my, d = Math.hypot(cx, cy) || 1;
        ball.vx = cx / d * 520; ball.vy = cy / d * 520 - 120; score += 10;
      }
    });
    flippers.forEach(hitFlipper);
    pops.forEach(function (p) {
      var dx = ball.x - p.x, dy = ball.y - p.y, d = Math.hypot(dx, dy);
      if (d < p.r + R) { ball.x = p.x + dx / d * (p.r + R); ball.y = p.y + dy / d * (p.r + R); ball.vx = dx / d * 620; ball.vy = dy / d * 620; score += 100; p.hit = 1; combo = 0; }
    });
    if (!ride) ramps.forEach(function (r) {
      if (ball.vy < -80 && Math.hypot(ball.x - r.mouth.x, ball.y - r.mouth.y) < r.mouth.r) {
        ride = { ramp: r, t: 0 }; combo = Math.min(combo + 1, 3); var pts = r.score * combo; score += pts; say(r.name + (combo > 1 ? "  x" + combo : "") + "  " + pts, 1.6);
      }
    });
    if (Math.hypot(ball.x - orbit.x, ball.y - orbit.y) < orbit.r && !orbit.cool) { score += orbit.score; orbit.cool = 60; say("ORBIT  500", 1.2); }
    if (orbit.cool) orbit.cool--;
    if (ball.x > 350 && ball.y > 400 && ball.vy > 0) ball.inLane = true; else if (ball.x < 345) ball.inLane = false;
    if (ball.y > H + R) {                                    // drained
      balls--;
      if (balls > 0) { newBall(); say("BALL " + (4 - balls) + "  PLUNGER", 2.5); }
      else { state = "over"; if (score > best) { best = score; try { localStorage.setItem("ptw-best", best); } catch (e) {} say("GAME OVER  NEW BEST " + best, 9999); } else say("GAME OVER  " + score, 9999); }
    }
  }
  function launch() {
    if (state !== "play") { start(); return; }
    if (ball.inLane && ball.y > 560 && Math.abs(ball.vy) < 50) { ball.vy = -(1650 + Math.random() * 150); ball.vx = 0; }
  }

  // ---------- drawing ----------
  var scale = 1;
  function fit() {
    var box = canvas.parentElement.getBoundingClientRect(), w = Math.min(box.width, (window.innerHeight - 40) * W / H);
    scale = w / W; canvas.width = Math.round(W * scale * devicePixelRatio); canvas.height = Math.round(H * scale * devicePixelRatio);
    canvas.style.width = Math.round(W * scale) + "px"; canvas.style.height = Math.round(H * scale) + "px";
  }
  window.addEventListener("resize", fit); fit();
  function dots(txt, x, y, size, align) {
    ctx.font = "900 " + size + "px Doto, monospace"; ctx.textAlign = align || "left"; ctx.fillStyle = ORANGE;
    ctx.shadowColor = "rgba(255,122,26,.7)"; ctx.shadowBlur = 10; ctx.fillText(txt, x, y); ctx.shadowBlur = 0;
  }
  function draw() {
    ctx.setTransform(scale * devicePixelRatio, 0, 0, scale * devicePixelRatio, 0, 0);
    ctx.fillStyle = "#0d0604"; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "rgba(255,122,26,.08)";
    for (var y = 4; y < H; y += 8) for (var x = 4; x < W; x += 8) ctx.fillRect(x, y, 1.2, 1.2);
    // ramps
    ramps.forEach(function (r) {
      ctx.strokeStyle = DIM; ctx.lineWidth = 14; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.beginPath();
      r.path.forEach(function (p, i) { i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); }); ctx.stroke();
      ctx.strokeStyle = ORANGE; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(r.mouth.x, r.mouth.y, r.mouth.r, 0, 7); ctx.stroke();
    });
    // walls
    ctx.strokeStyle = ORANGE; ctx.lineWidth = 3; ctx.lineCap = "round";
    walls.forEach(function (s) { ctx.beginPath(); ctx.moveTo(s.x1, s.y1); ctx.lineTo(s.x2, s.y2); ctx.stroke(); });
    slings.forEach(function (t) { ctx.fillStyle = "rgba(255,122,26,.18)"; ctx.beginPath(); ctx.moveTo(t[0][0], t[0][1]); ctx.lineTo(t[1][0], t[1][1]); ctx.lineTo(t[2][0], t[2][1]); ctx.fill(); });
    // pops
    pops.forEach(function (p) {
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7); ctx.fillStyle = p.hit > 0.5 ? ORANGE : "rgba(255,122,26,.25)"; ctx.fill();
      ctx.strokeStyle = ORANGE; ctx.lineWidth = 3; ctx.stroke(); p.hit = Math.max(0, p.hit - 0.08);
    });
    // flippers
    flippers.forEach(function (f) {
      ctx.strokeStyle = PAPER; ctx.lineWidth = 14; ctx.lineCap = "round"; ctx.beginPath();
      ctx.moveTo(f.px, f.py); ctx.lineTo(f.px + f.len * Math.cos(f.a), f.py + f.len * Math.sin(f.a)); ctx.stroke();
    });
    // ball
    if (state !== "attract") {
      var g = ctx.createRadialGradient(ball.x - 3, ball.y - 3, 1, ball.x, ball.y, R);
      g.addColorStop(0, "#fff"); g.addColorStop(0.5, "#cfd3d8"); g.addColorStop(1, "#5a5f66");
      ctx.beginPath(); ctx.arc(ball.x, ball.y, R, 0, 7); ctx.fillStyle = g; ctx.fill();
    }
    // the display
    dots(String(score).padStart(6, "0"), 30, 52, 34);
    dots("BALL " + Math.max(0, 4 - balls) + "   BEST " + best, 30, 76, 13);
    if (performance.now() < msgUntil) dots(msg, 200, 100, 14, "center");
  }
  function frame() { for (var i = 0; i < SUB; i++) step(); draw(); requestAnimationFrame(frame); }
  requestAnimationFrame(frame);

  // ---------- controls ----------
  var LEFT = { ArrowLeft: 1, KeyZ: 1, ShiftLeft: 1 }, RIGHT = { ArrowRight: 1, Slash: 1, ShiftRight: 1 };
  document.addEventListener("keydown", function (ev) {
    if (LEFT[ev.code]) { flippers[0].key = true; ev.preventDefault(); }
    if (RIGHT[ev.code]) { flippers[1].key = true; ev.preventDefault(); }
    if (ev.code === "Space" || ev.code === "ArrowDown" || ev.code === "Enter") { launch(); ev.preventDefault(); }
  });
  document.addEventListener("keyup", function (ev) {
    if (LEFT[ev.code]) flippers[0].key = false;
    if (RIGHT[ev.code]) flippers[1].key = false;
  });
  function touchAt(ev, down) {
    for (var i = 0; i < ev.changedTouches.length; i++) {
      var t = ev.changedTouches[i], box = canvas.getBoundingClientRect(), x = (t.clientX - box.left) / scale, y = (t.clientY - box.top) / scale;
      if (down && (x > 345 && y > 400 || state !== "play")) { launch(); continue; }
      flippers[x < W / 2 ? 0 : 1].key = down;
    }
    ev.preventDefault();
  }
  canvas.addEventListener("touchstart", function (ev) { touchAt(ev, true); }, { passive: false });
  canvas.addEventListener("touchend", function (ev) { touchAt(ev, false); }, { passive: false });
  canvas.addEventListener("touchcancel", function (ev) { touchAt(ev, false); }, { passive: false });
  canvas.addEventListener("mousedown", function (ev) {
    var box = canvas.getBoundingClientRect(), x = (ev.clientX - box.left) / scale, y = (ev.clientY - box.top) / scale;
    if (x > 345 && y > 400 || state !== "play") launch(); else flippers[x < W / 2 ? 0 : 1].key = true;
  });
  document.addEventListener("mouseup", function () { flippers[0].key = flippers[1].key = false; });
})();
