/* A small pinball table for the /play/ page: Matter.js for the physics, drawn by hand as
   two-tone pixel art in the display's orange, the way a dot-matrix screen would show it.
   Forgiving by design: no outlanes, a narrow flipper gap, a ball saver on every ball, and two
   ramps that drop the ball back onto a flipper, so a good game is one long loop.
   Keys: left and right arrows, Z and /, or the shift keys; space to launch.
   Touch: tap the left or right half of the table; tap the lane to launch. */
(function () {
  "use strict";
  var M = window.Matter;
  var canvas = document.getElementById("table"), ctx = canvas.getContext("2d");
  if (!M) { canvas.insertAdjacentHTML("afterend", '<p class="muted">The table could not load its physics library.</p>'); return; }
  var Engine = M.Engine, Bodies = M.Bodies, Body = M.Body, Composite = M.Composite, Events = M.Events;
  var W = 400, H = 700, R = 8, PX = 2;                       // table units; one pixel of art is PX units
  var engine = Engine.create({ positionIterations: 10, velocityIterations: 8 });
  engine.gravity.y = 1; engine.gravity.scale = 0.0011;
  var world = engine.world;
  var INK = "#ff7a1a", DIM = "#8a3f10", BG = "#0d0604";

  // ---------- rails: polylines become thin static rectangles ----------
  var rails = [];
  function rail(points) {
    rails.push(points);
    for (var i = 0; i < points.length - 1; i++) {
      var a = points[i], b = points[i + 1], dx = b[0] - a[0], dy = b[1] - a[1];
      Composite.add(world, Bodies.rectangle((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, Math.hypot(dx, dy), 8,
        { isStatic: true, angle: Math.atan2(dy, dx), restitution: 0.35, friction: 0.02 }));
      if (i < points.length - 2) Composite.add(world, Bodies.circle(b[0], b[1], 4, { isStatic: true, restitution: 0.35 }));
    }
  }
  var arc = []; for (var i = 0; i <= 28; i++) { var t = Math.PI + Math.PI * i / 28; arc.push([200 + 184 * Math.cos(t), 190 + 184 * Math.sin(t)]); }
  rail(arc);                                                       // the orbit round the top
  rail([[16, 190], [16, 540], [66, 604], [146, 650]]); rail([[150, 658], [162, 698]]);    // left wall and inlane into the hinge; the drain below
  rail([[352, 190], [352, 540], [334, 604], [254, 650]]); rail([[250, 658], [238, 698]]); // lane guide and inlane into the hinge; the drain below
  rail([[384, 190], [384, 676], [352, 676], [352, 640]]);                         // shooter lane
  [[148, 653], [252, 653]].forEach(function (c) { Composite.add(world, Bodies.circle(c[0], c[1], 7, { isStatic: true, restitution: 0.2 })); });  // flipper bases

  var slings = [[[88, 478], [128, 584], [88, 584]], [[312, 478], [272, 584], [312, 584]]];   // clear of the walls, so nothing wedges
  var slingBodies = slings.map(function (t) {
    var cx = (t[0][0] + t[1][0] + t[2][0]) / 3, cy = (t[0][1] + t[1][1] + t[2][1]) / 3;
    var b = Bodies.fromVertices(cx, cy, [t.map(function (p) { return { x: p[0], y: p[1] }; })], { isStatic: true, restitution: 0.2, label: "sling" });
    b.centre = { x: cx, y: cy }; b.flash = 0; Composite.add(world, b); return b;
  });
  var pops = [[150, 285], [246, 252], [200, 352]].map(function (p) {
    var b = Bodies.circle(p[0], p[1], 19, { isStatic: true, restitution: 0.2, label: "pop" }); b.flash = 0; Composite.add(world, b); return b;
  });
  // each ramp is a hairpin: up its own side, round at the top, back down to the inlane beside it
  var ramps = [
    { name: "LEFT LOOP", mouth: { x: 118, y: 440, r: 24 }, path: [[118, 440], [118, 330], [122, 230], [112, 180], [88, 166], [66, 190], [58, 260], [56, 400], [58, 520], [74, 566]], exit: { x: 3, y: 4 } },
    { name: "RIGHT LOOP", mouth: { x: 282, y: 458, r: 24 }, path: [[282, 458], [282, 340], [278, 240], [288, 190], [312, 176], [334, 200], [342, 270], [344, 400], [342, 520], [328, 566]], exit: { x: -3, y: 4 } }
  ];
  var orbitZone = { x: 200, y: 36, r: 30 };

  // flippers: bodies the game places each tick; the engine resolves the ball against them
  function flipper(px, py, dir) {
    var len = 54, body = Bodies.rectangle(px, py, len, 12, { chamfer: { radius: 5 }, density: 1, restitution: 0.1, friction: 0.05, label: "flipper", collisionFilter: { group: -1 } });
    Composite.add(world, body);
    var f = { body: body, px: px, py: py, len: len, dir: dir, rest: dir > 0 ? 0.5 : Math.PI - 0.5, up: dir > 0 ? -0.62 : Math.PI + 0.62, a: 0, key: false, rising: false };
    place(f, f.rest, 0); return f;
  }
  function place(f, a, w) {
    Body.setPosition(f.body, { x: f.px + f.len / 2 * Math.cos(a), y: f.py + f.len / 2 * Math.sin(a) });
    Body.setAngle(f.body, a); Body.setAngularVelocity(f.body, w); Body.setVelocity(f.body, { x: 0, y: 0 }); f.a = a;
  }
  var flippers = [flipper(148, 653, 1), flipper(252, 653, -1)];

  // ---------- the ball and the game ----------
  var ball = Bodies.circle(368, 630, R, { restitution: 0.3, friction: 0.01, frictionAir: 0.0012, density: 0.004, label: "ball" });
  Composite.add(world, ball);
  var state = "attract", score = 0, best = 0, ballsLeft = 0, ride = null, combo = 0, lastRamp = null, saver = 0, msg = "", msgUntil = 0, orbitCool = 0;
  try { best = +localStorage.getItem("ptw-best") || 0; } catch (e) {}
  function say(t, secs) { msg = t; msgUntil = performance.now() + secs * 1000; }
  function toLane() { Body.setPosition(ball, { x: 368, y: 630 }); Body.setVelocity(ball, { x: 0, y: 0 }); Body.setAngularVelocity(ball, 0); ride = null; ball.collisionFilter.mask = -1; }
  function newBall() { toLane(); saver = 20 * 60; }
  function start() { score = 0; ballsLeft = 3; combo = 0; lastRamp = null; state = "play"; newBall(); say("HOLD SPACE OR THE LANE, LET GO TO LAUNCH", 3); }
  var pull = 0, pulling = false;
  function inLane() { return ball.position.x > 352 && ball.position.y > 560 && Math.abs(ball.velocity.y) < 1; }
  function pullStart() { if (state !== "play") { start(); return; } if (inLane()) pulling = true; }
  function pullEnd() {
    if (!pulling) return;
    pulling = false;
    if (inLane()) Body.setVelocity(ball, { x: 0, y: -(10 + 12.5 * pull) });     // a full pull clears the orbit, a tap does not
    pull = 0;
  }
  function launch() { pullStart(); pull = 1; pullEnd(); }                       // a straight launch, for the test hook
  say("PRESS SPACE OR TAP TO PLAY", 1e9);

  Events.on(engine, "collisionStart", function (ev) {
    ev.pairs.forEach(function (pr) {
      var other = pr.bodyA === ball ? pr.bodyB : pr.bodyB === ball ? pr.bodyA : null;
      if (!other || state !== "play") return;
      if (other.label === "pop") {
        var dx = ball.position.x - other.position.x, dy = ball.position.y - other.position.y, d = Math.hypot(dx, dy) || 1;
        Body.setVelocity(ball, { x: dx / d * 11, y: dy / d * 11 }); other.flash = 1; score += 100;
      } else if (other.label === "sling") {
        var sx = ball.position.x - other.centre.x, sy = ball.position.y - other.centre.y, sd = Math.hypot(sx, sy) || 1;
        Body.setVelocity(ball, { x: sx / sd * 9, y: sy / sd * 9 - 2 }); other.flash = 1; score += 10;
      }
    });
  });

  var SUB = 3;                                                     // physics substeps per frame
  function swing() {
    flippers.forEach(function (f) {
      var target = f.key ? f.up : f.rest, rate = 0.11, a = f.a;     // about six frames hinge to tip
      if (a < target) a = Math.min(target, a + rate); else a = Math.max(target, a - rate);
      f.rising = f.key && a !== f.a; place(f, a, (a - f.a) * SUB);
    });
  }
  function kick() {
    // a rising flipper always sends the ball off its face, however the engine resolved the contact
    flippers.forEach(function (f) {
      if (!f.rising) return;
      var dx = ball.position.x - f.px, dy = ball.position.y - f.py, along = dx * Math.cos(f.a) + dy * Math.sin(f.a);
      var up = f.dir > 0 ? { x: Math.sin(f.a), y: -Math.cos(f.a) } : { x: -Math.sin(f.a), y: Math.cos(f.a) };
      var h = dx * up.x + dy * up.y;                                 // height of the ball above the face
      if (along < 3 || along > f.len + R || h < -2 || h > R + 12) return;
      var speed = Math.min(22, 7 + along * 0.28);
      Body.setVelocity(ball, { x: up.x * speed + ball.velocity.x * 0.2, y: up.y * speed });
    });
  }
  function tick() {
    if (pulling) pull = Math.min(1, pull + 1 / 36); else pull = Math.max(0, pull - 0.2);
    if (state !== "play") { for (var k = 0; k < SUB; k++) { swing(); Engine.update(engine, 1000 / 60 / SUB); } return; }
    if (ride) {
      ride.t += 1 / 50;
      var p = ride.ramp.path, n = p.length - 1, i = Math.min(n - 1, Math.floor(ride.t * n)), u = ride.t * n - i;
      Body.setPosition(ball, { x: p[i][0] + (p[i + 1][0] - p[i][0]) * u, y: p[i][1] + (p[i + 1][1] - p[i][1]) * u });
      Body.setVelocity(ball, { x: 0, y: 0 });
      if (ride.t >= 1) { ball.collisionFilter.mask = -1; Body.setVelocity(ball, ride.ramp.exit); ride = null; }
      for (var j = 0; j < SUB; j++) { swing(); Engine.update(engine, 1000 / 60 / SUB); } return;
    }
    for (var k = 0; k < SUB; k++) {
      swing(); kick();
      var v = ball.velocity, sp = Math.hypot(v.x, v.y);
      if (sp > 24) Body.setVelocity(ball, { x: v.x / sp * 24, y: v.y / sp * 24 });
      Engine.update(engine, 1000 / 60 / SUB);
    }
    ramps.forEach(function (r) {
      if (!ride && ball.velocity.y < -1 && Math.hypot(ball.position.x - r.mouth.x, ball.position.y - r.mouth.y) < r.mouth.r + R) {
        ride = { ramp: r, t: 0 }; ball.collisionFilter.mask = 0;
        combo = lastRamp && lastRamp !== r ? Math.min(combo + 1, 3) : 1; lastRamp = r;
        var pts = 1000 * combo; score += pts; say(r.name + (combo > 1 ? "  COMBO X" + combo : "") + "  " + pts, 1.6);
      }
    });
    if (orbitCool) orbitCool--;
    else if (Math.hypot(ball.position.x - orbitZone.x, ball.position.y - orbitZone.y) < orbitZone.r) { score += 500; orbitCool = 90; say("ORBIT  500", 1.2); }
    if (saver) saver--;
    if (ball.position.y > H + 20) {
      if (saver) { newBall(); say("BALL SAVED", 1.8); return; }
      ballsLeft--;
      if (ballsLeft > 0) { newBall(); say("BALL " + (4 - ballsLeft), 2); }
      else {
        state = "over";
        if (score > best) { best = score; try { localStorage.setItem("ptw-best", best); } catch (e) {} say("GAME OVER   NEW BEST " + score, 1e9); }
        else say("GAME OVER   " + score, 1e9);
      }
    }
  }

  // ---------- drawing: the playfield at 200 by 350 pixels, blown up with no smoothing ----------
  var art = document.createElement("canvas"); art.width = W / PX; art.height = H / PX;
  var a = art.getContext("2d");
  var scale = 1;
  function fit() {
    var box = canvas.parentElement.getBoundingClientRect(), w = Math.min(box.width, (window.innerHeight - 40) * W / H);
    scale = w / W; canvas.width = Math.round(W * scale * devicePixelRatio); canvas.height = Math.round(H * scale * devicePixelRatio);
    canvas.style.width = Math.round(W * scale) + "px"; canvas.style.height = Math.round(H * scale) + "px";
  }
  window.addEventListener("resize", fit); fit();
  function path(points, close) { a.beginPath(); points.forEach(function (p, i) { i ? a.lineTo(p[0] / PX, p[1] / PX) : a.moveTo(p[0] / PX, p[1] / PX); }); if (close) a.closePath(); }
  function curve(points) {
    a.beginPath(); a.moveTo(points[0][0] / PX, points[0][1] / PX);
    for (var i = 1; i < points.length - 1; i++) { a.quadraticCurveTo(points[i][0] / PX, points[i][1] / PX, (points[i][0] + points[i + 1][0]) / 2 / PX, (points[i][1] + points[i + 1][1]) / 2 / PX); }
    var l = points[points.length - 1]; a.lineTo(l[0] / PX, l[1] / PX);
  }
  function disc(x, y, r, fill, stroke) { a.beginPath(); a.arc(x / PX, y / PX, r / PX, 0, 7); if (fill) { a.fillStyle = fill; a.fill(); } if (stroke) { a.strokeStyle = stroke; a.lineWidth = 1; a.stroke(); } }
  function drawArt() {
    a.fillStyle = BG; a.fillRect(0, 0, art.width, art.height);
    a.fillStyle = "rgba(255,122,26,0.10)";                     // the faint dot grid of a display
    for (var y = 1; y < art.height; y += 3) for (var x = 1; x < art.width; x += 3) a.fillRect(x, y, 1, 1);
    a.lineCap = "butt"; a.lineJoin = "miter";
    ramps.forEach(function (r) {                               // ramps as twin lines, like a wireframe tube
      curve(r.path); a.strokeStyle = DIM; a.lineWidth = 7; a.stroke();
      curve(r.path); a.strokeStyle = BG; a.lineWidth = 5; a.stroke();
      curve(r.path); a.strokeStyle = DIM; a.lineWidth = 1; a.stroke();
      var lit = performance.now() % 900 < 450, mx = r.mouth.x / PX, my = r.mouth.y / PX;
      a.strokeStyle = DIM; a.lineWidth = 1; a.beginPath();                                 // the mouth flares open
      a.moveTo(mx - 3, my - 14); a.lineTo(mx - 11, my + 8); a.moveTo(mx + 3, my - 14); a.lineTo(mx + 11, my + 8); a.stroke();
      a.strokeStyle = lit ? INK : DIM; a.lineWidth = 2; a.beginPath(); a.moveTo(mx - 5, my + 4); a.lineTo(mx, my - 2); a.lineTo(mx + 5, my + 4); a.stroke();   // a chevron
    });
    rails.forEach(function (pts) { path(pts); a.strokeStyle = INK; a.lineWidth = 2; a.stroke(); });
    slings.forEach(function (t, i) { var b = slingBodies[i]; path(t, true); a.fillStyle = b.flash > 0.5 ? INK : DIM; a.fill(); a.strokeStyle = INK; a.lineWidth = 1; a.stroke(); b.flash = Math.max(0, b.flash - 0.1); });
    pops.forEach(function (p) {
      var x = p.position.x, y = p.position.y;
      disc(x, y, 19, p.flash > 0.5 ? INK : BG, INK); disc(x, y, 11, p.flash > 0.5 ? BG : DIM, INK); disc(x, y, 4, INK);
      p.flash = Math.max(0, p.flash - 0.08);
    });
    flippers.forEach(function (f) {
      var tx = f.px + f.len * Math.cos(f.a), ty = f.py + f.len * Math.sin(f.a);
      a.lineCap = "round"; a.beginPath(); a.moveTo(f.px / PX, f.py / PX); a.lineTo(tx / PX, ty / PX); a.strokeStyle = INK; a.lineWidth = 6; a.stroke();
      a.beginPath(); a.moveTo(f.px / PX, f.py / PX); a.lineTo(tx / PX, ty / PX); a.strokeStyle = BG; a.lineWidth = 3; a.stroke();
      a.beginPath(); a.moveTo(f.px / PX, f.py / PX); a.lineTo(tx / PX, ty / PX); a.strokeStyle = INK; a.lineWidth = 1; a.stroke();
      a.lineCap = "butt"; disc(f.px, f.py, 7, BG, INK); disc(f.px, f.py, 2.5, INK);
    });
    var head = 652 + pull * 22, hx = 368 / PX;                       // the plunger below the ball
    a.strokeStyle = DIM; a.lineWidth = 1; a.beginPath();
    for (var k = 0; k < 6; k++) { var yy = (head + 6 + k * 4) / PX; a.moveTo(hx - 4, yy); a.lineTo(hx + 4, yy + 1); }
    a.stroke();
    a.fillStyle = INK; a.fillRect(hx - 5, head / PX, 10, 3); a.fillRect(hx - 1, head / PX + 3, 2, 10);
    if (state !== "attract") { disc(ball.position.x, ball.position.y, R, INK); disc(ball.position.x - 2, ball.position.y - 2, 2.5, "#ffd9b5"); }
  }
  function dots(txt, x, y, size, colour) {
    ctx.font = "900 " + size + "px Doto, monospace"; ctx.textAlign = "center"; ctx.fillStyle = colour || INK;
    ctx.shadowColor = "rgba(255,122,26,.6)"; ctx.shadowBlur = 8; ctx.fillText(txt, x, y); ctx.shadowBlur = 0;
  }
  function draw() {
    drawArt();
    ctx.setTransform(scale * devicePixelRatio, 0, 0, scale * devicePixelRatio, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(art, 0, 0, W, H);
    dots(String(score).padStart(6, "0"), 200, 62, 36);
    dots(state === "play" ? "BALL " + (4 - ballsLeft) + " OF 3" + (saver ? "   SAVER ON" : "") + "   BEST " + best : "BEST " + best, 200, 86, 13, DIM);
    if (performance.now() < msgUntil) dots(msg, 200, 110, 14);
  }
  function frame() { tick(); draw(); requestAnimationFrame(frame); }
  requestAnimationFrame(frame);

  // ---------- controls ----------
  var LEFT = { ArrowLeft: 1, KeyZ: 1, ShiftLeft: 1 }, RIGHT = { ArrowRight: 1, Slash: 1, ShiftRight: 1 };
  document.addEventListener("keydown", function (ev) {
    if (LEFT[ev.code]) { flippers[0].key = true; ev.preventDefault(); }
    if (RIGHT[ev.code]) { flippers[1].key = true; ev.preventDefault(); }
    if (ev.code === "Space" || ev.code === "ArrowDown" || ev.code === "Enter") { if (!ev.repeat) pullStart(); ev.preventDefault(); }
  });
  document.addEventListener("keyup", function (ev) {
    if (LEFT[ev.code]) flippers[0].key = false; if (RIGHT[ev.code]) flippers[1].key = false;
    if (ev.code === "Space" || ev.code === "ArrowDown" || ev.code === "Enter") pullEnd();
  });
  function at(cx, cy) { var box = canvas.getBoundingClientRect(); return { x: (cx - box.left) / scale, y: (cy - box.top) / scale }; }
  function touch(ev, down) {
    for (var i = 0; i < ev.changedTouches.length; i++) {
      var t = ev.changedTouches[i], p = at(t.clientX, t.clientY);
      if (state !== "play" || (p.x > 340 && p.y > 400)) { if (down) pullStart(); else pullEnd(); continue; }
      flippers[p.x < W / 2 ? 0 : 1].key = down;
    }
    ev.preventDefault();
  }
  canvas.addEventListener("touchstart", function (ev) { touch(ev, true); }, { passive: false });
  canvas.addEventListener("touchend", function (ev) { touch(ev, false); }, { passive: false });
  canvas.addEventListener("touchcancel", function (ev) { touch(ev, false); }, { passive: false });
  canvas.addEventListener("mousedown", function (ev) { var p = at(ev.clientX, ev.clientY); if (state !== "play" || (p.x > 340 && p.y > 400)) pullStart(); else flippers[p.x < W / 2 ? 0 : 1].key = true; });
  document.addEventListener("mouseup", function () { flippers[0].key = flippers[1].key = false; pullEnd(); });

  // a hook so the table can be driven in a headless test
  window.PTW = { get: function () { return { state: state, score: score, balls: ballsLeft, x: ball.position.x, y: ball.position.y, vy: ball.velocity.y, saver: saver, ride: !!ride, pull: pull }; }, launch: launch, pullStart: pullStart, pullEnd: pullEnd, flip: function (i, on) { flippers[i].key = on; },
                put: function (x, y, vx, vy) { Body.setPosition(ball, { x: x, y: y }); Body.setVelocity(ball, { x: vx, y: vy }); } };
})();
