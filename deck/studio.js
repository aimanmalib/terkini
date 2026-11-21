/* studio.js — penskala pentas 1920×1080 + navigasi (anak panah, Space, leret). window.presentation.goToSlide(n) untuk eksport. */
(() => {
  const stage = document.getElementById('stage');
  const slides = [...document.querySelectorAll('.slide')];
  const dots = document.createElement('div');
  dots.className = 'deck-controls'; dots.setAttribute('aria-hidden', 'true');
  document.body.appendChild(dots);
  let i = 0;
  slides.forEach(() => dots.appendChild(document.createElement('i')));
  function fit() {
    const s = Math.min(innerWidth / 1920, innerHeight / 1080);
    stage.style.transform = `translate(${(innerWidth - 1920 * s) / 2}px,${(innerHeight - 1080 * s) / 2}px) scale(${s})`;
  }
  function go(n) {
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach((el, k) => el.classList.toggle('active', k === i));
    [...dots.children].forEach((d, k) => d.classList.toggle('on', k === i));
  }
  window.presentation = { goToSlide: go };
  addEventListener('resize', fit);
  addEventListener('keydown', e => {
    if (['ArrowRight', 'PageDown', ' '].includes(e.key)) go(i + 1);
    if (['ArrowLeft', 'PageUp'].includes(e.key)) go(i - 1);
  });
  let x0 = null;
  addEventListener('touchstart', e => { x0 = e.touches[0].clientX; }, { passive: true });
  addEventListener('touchend', e => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 40) go(i + (dx < 0 ? 1 : -1));
    x0 = null;
  });
  fit(); go(0);
})();
