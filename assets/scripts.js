/* ============================================
   REJESHA JOURNAL — HERO SCRIPTS
   Typewriter Effect + Star Field Canvas
   ============================================ */

(function () {
  'use strict';

  /* ── Typewriter ──────────────────────────── */
  const PHRASES = [
    'Real stories. Real lives.',
    'Immigration. Identity.',
    'Life Ya Majuu.',
    'You belong here.',
    'Career. Culture. Community.',
    'Rooted. Rising. Together.',
    'Your journey matters.',
    'From 254, with love.',
    'Home is where you carry it.',
    'Building futures, both sides of the ocean.'
  ];

  const TYPING_SPEED  = 80;   // ms per character
  const ERASE_SPEED   = 40;   // ms per character (erasing)
  const HOLD_MS       = 2200; // pause at full phrase
  const GAP_MS        = 450;  // pause before next phrase

  function initTypewriter() {
    const el = document.getElementById('rj-typewriter-text');
    if (!el) return;

    let phraseIdx  = 0;
    let charIdx    = 0;
    let isErasing  = false;

    function tick() {
      const phrase = PHRASES[phraseIdx];

      if (!isErasing) {
        charIdx++;
        el.textContent = phrase.slice(0, charIdx);

        if (charIdx === phrase.length) {
          isErasing = true;
          return setTimeout(tick, HOLD_MS);
        }
        return setTimeout(tick, TYPING_SPEED);
      } else {
        charIdx--;
        el.textContent = phrase.slice(0, charIdx);

        if (charIdx === 0) {
          isErasing  = false;
          phraseIdx  = (phraseIdx + 1) % PHRASES.length;
          return setTimeout(tick, GAP_MS);
        }
        return setTimeout(tick, ERASE_SPEED);
      }
    }

    setTimeout(tick, 1400);
  }

  /* ── Star Field Canvas ───────────────────── */
  function initStars() {
    const canvas = document.getElementById('rj-stars');
    if (!canvas) return;

    const ctx    = canvas.getContext('2d');
    const hero   = canvas.parentElement;
    let   stars  = [];
    let   raf;

    function resize() {
      canvas.width  = hero.offsetWidth;
      canvas.height = hero.offsetHeight;
      buildStars();
    }

    function buildStars() {
      const count = Math.floor((canvas.width * canvas.height) / 5500);
      stars = Array.from({ length: count }, () => ({
        x     : Math.random() * canvas.width,
        y     : Math.random() * canvas.height,
        r     : Math.random() * 1.4 + 0.2,
        alpha : Math.random() * 0.55 + 0.15,
        phase : Math.random() * Math.PI * 2,
        speed : Math.random() * 0.012 + 0.004,
        amber : Math.random() < 0.35   // ~35 % amber, rest white
      }));
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      stars.forEach(s => {
        s.phase += s.speed;
        const a = s.alpha * (0.65 + 0.35 * Math.sin(s.phase));
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = s.amber
          ? `rgba(245, 166, 35, ${a})`
          : `rgba(210, 230, 255, ${a * 0.7})`;
        ctx.fill();
      });
      raf = requestAnimationFrame(draw);
    }

    resize();
    window.addEventListener('resize', resize);
    draw();

    // Cleanup hook (optional)
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); };
  }

  /* ── Init on DOM Ready ───────────────────── */
  function init() {
    initTypewriter();
    initStars();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
