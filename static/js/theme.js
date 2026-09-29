(() => {
  let saved;
  try { saved = localStorage.getItem('yvi.theme'); } catch { /* Storage may be disabled. */ }
  const dark = window.matchMedia('(prefers-color-scheme: dark)');
  const apply = (theme) => {
    document.documentElement.dataset.theme = theme;
    const button = document.getElementById('theme-toggle');
    if (button) {
      button.textContent = theme === 'dark' ? '☀ Tema claro' : '☾ Tema escuro';
      button.setAttribute('aria-label', theme === 'dark' ? 'Ativar tema claro' : 'Ativar tema escuro');
    }
  };
  apply(saved === 'dark' || saved === 'light' ? saved : dark.matches ? 'dark' : 'light');
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme);
    document.getElementById('theme-toggle').addEventListener('click', () => {
      saved = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      apply(saved);
      try { localStorage.setItem('yvi.theme', saved); } catch { /* Keep in-memory preference. */ }
    });
  });
  dark.addEventListener('change', () => { if (!saved) apply(dark.matches ? 'dark' : 'light'); });
})();
