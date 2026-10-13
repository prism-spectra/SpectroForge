(function () {
  function initFrames() {
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    document.querySelectorAll('.screenshot-frame').forEach(function (frame) {
      var lightImg = frame.querySelector('.sf-light');
      var darkImg  = frame.querySelector('.sf-dark');
      var btn      = frame.querySelector('.screenshot-toggle');
      if (!lightImg || !darkImg || !btn) return;

      // Set initial state from OS preference
      var showDark = prefersDark;

      function apply() {
        if (showDark) {
          darkImg.classList.remove('sf-hidden');
          lightImg.classList.add('sf-hidden');
          btn.querySelector('.sf-icon').textContent = '☀';
          btn.querySelector('.sf-label').textContent = 'Light';
        } else {
          lightImg.classList.remove('sf-hidden');
          darkImg.classList.add('sf-hidden');
          btn.querySelector('.sf-icon').textContent = '🌙';
          btn.querySelector('.sf-label').textContent = 'Dark';
        }
      }

      btn.addEventListener('click', function () {
        showDark = !showDark;
        apply();
      });

      apply();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFrames);
  } else {
    initFrames();
  }
})();
