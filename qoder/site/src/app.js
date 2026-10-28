// 滚动渐显
const revealEls = document.querySelectorAll('.reveal');
if ('IntersectionObserver' in window) {
  const io = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add('in');
        io.unobserve(entry.target);
      }
    }
  }, { rootMargin: '0px 0px -10% 0px', threshold: 0.08 });
  revealEls.forEach((el) => io.observe(el));
} else {
  revealEls.forEach((el) => el.classList.add('in'));
}

// 复制代码
document.querySelectorAll('.code-block .copy').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const code = btn.closest('.code-block')?.querySelector('code');
    if (!code) return;
    const text = code.innerText;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    const old = btn.textContent;
    btn.textContent = '已复制';
    setTimeout(() => { btn.textContent = old; }, 1400);
  });
});

// 截图灯箱
const lightbox = document.getElementById('lightbox');
const lightboxImg = lightbox?.querySelector('img');
const closeBtn = lightbox?.querySelector('.lightbox-close');

function openLightbox(src, alt) {
  if (!lightbox || !lightboxImg) return;
  lightboxImg.src = src;
  lightboxImg.alt = alt || '';
  lightbox.hidden = false;
  document.body.style.overflow = 'hidden';
}
function closeLightbox() {
  if (!lightbox) return;
  lightbox.hidden = true;
  document.body.style.overflow = '';
}

document.querySelectorAll('.gallery figure, .hero-shot').forEach((fig) => {
  fig.addEventListener('click', () => {
    const img = fig.querySelector('img');
    if (img) openLightbox(img.getAttribute('src'), img.getAttribute('alt'));
  });
});
closeBtn?.addEventListener('click', closeLightbox);
lightbox?.addEventListener('click', (e) => {
  if (e.target === lightbox) closeLightbox();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeLightbox();
});
