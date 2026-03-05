/**
 * TaskFlow — main.js
 * Global UI behaviors: sidebar, alerts, toast, filters, status update
 */

/* ══════════════════════════════════════════════════════════
   SIDEBAR MOBILE — toggle + overlay + close on resize
══════════════════════════════════════════════════════════ */

(function initSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  const toggle  = document.getElementById('sidebarToggle');

  if (!sidebar || !toggle) return;

  function openSidebar() {
    sidebar.classList.add('open');
    overlay.classList.add('active');
    toggle.querySelector('i').className = 'fas fa-times';
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    sidebar.classList.remove('open');
    overlay.classList.remove('active');
    toggle.querySelector('i').className = 'fas fa-bars';
    document.body.style.overflow = '';
  }

  toggle.addEventListener('click', () => {
    sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
  });

  overlay.addEventListener('click', closeSidebar);

  // Fechar ao navegar (mobile)
  sidebar.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', () => {
      if (window.innerWidth <= 900) closeSidebar();
    });
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 900) closeSidebar();
  });
})();


/* ══════════════════════════════════════════════════════════
   ALERTS — auto-dismiss flash messages
══════════════════════════════════════════════════════════ */

(function initAlerts() {
  const DISMISS_AFTER = 4500;
  const FADE_DURATION = 500;

  function dismissAlert(el) {
    el.style.transition = `opacity ${FADE_DURATION}ms ease`;
    el.style.opacity = '0';
    setTimeout(() => el.remove(), FADE_DURATION);
  }

  document.querySelectorAll('.alert-close').forEach(btn => {
    btn.addEventListener('click', () => dismissAlert(btn.closest('.alert')));
  });

  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(dismissAlert);
  }, DISMISS_AFTER);
})();


/* ══════════════════════════════════════════════════════════
   TOAST — notificação leve no canto da tela
══════════════════════════════════════════════════════════ */

window.showToast = function (message, type, duration) {
  type     = type     || 'default';
  duration = duration || 2800;

  document.querySelectorAll('.toast').forEach(function(t) { t.remove(); });

  var colors = { success: 'var(--green)', error: 'var(--red)', default: 'var(--accent2)' };
  var color  = colors[type] || colors['default'];

  var el = document.createElement('div');
  el.className = 'toast';
  el.innerHTML = '<span style="color:' + color + ';margin-right:8px">&#9679;</span>' + message;
  document.body.appendChild(el);

  setTimeout(function() {
    el.style.transition = 'opacity .4s ease, transform .4s ease';
    el.style.opacity    = '0';
    el.style.transform  = 'translateY(8px)';
    setTimeout(function() { el.remove(); }, 400);
  }, duration);
};


/* ══════════════════════════════════════════════════════════
   PASSWORD TOGGLE
══════════════════════════════════════════════════════════ */

window.togglePassword = function (inputId, iconId) {
  var input = document.getElementById(inputId);
  var icon  = document.getElementById(iconId);
  if (!input) return;
  var isHidden = input.type === 'password';
  input.type = isHidden ? 'text' : 'password';
  if (icon) icon.className = isHidden ? 'fas fa-eye-slash' : 'fas fa-eye';
};


/* ══════════════════════════════════════════════════════════
   TABLE FILTER — busca live + filtro por status
══════════════════════════════════════════════════════════ */

(function initTableFilter() {
  var searchInput = document.getElementById('searchInput');
  var filterBtns  = document.querySelectorAll('.filter-btn[data-filter]');
  var tableBody   = document.querySelector('#filterableTable tbody');

  if (!tableBody) return;

  var currentFilter = 'all';

  function applyFilters() {
    var query = searchInput ? searchInput.value.toLowerCase() : '';
    Array.from(tableBody.rows).forEach(function(row) {
      var matchFilter = currentFilter === 'all' || row.dataset.status === currentFilter;
      var matchSearch = row.textContent.toLowerCase().indexOf(query) > -1;
      row.style.display = (matchFilter && matchSearch) ? '' : 'none';
    });
  }

  if (searchInput) searchInput.addEventListener('input', applyFilters);

  filterBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      filterBtns.forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      currentFilter = btn.dataset.filter;
      applyFilters();
    });
  });
})();


/* ══════════════════════════════════════════════════════════
   TASK STATUS UPDATE
   - Atualiza card, badge, título riscado
   - Atualiza contadores de stats e barra de progresso
   - Feedback visual imediato (disable + spinner no select)
══════════════════════════════════════════════════════════ */

window.updateTaskStatus = function (taskId, newStatus, selectEl) {
  // Feedback imediato: bloqueia o select
  if (selectEl) {
    selectEl.disabled = true;
    selectEl.style.opacity = '0.5';
  }

  fetch('/tasks/' + taskId + '/update-status', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ status: newStatus }),
  })
  .then(function(res) {
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
  })
  .then(function(data) {
    if (!data.success) throw new Error('Resposta inválida');

    var card = document.getElementById('task-card-' + taskId);
    if (card) {
      // 1. Classe is-done no card
      if (newStatus === 'done') {
        card.classList.add('is-done');
      } else {
        card.classList.remove('is-done');
      }

      // 2. Título riscado
      var title = card.querySelector('.task-card-title');
      if (title) {
        if (newStatus === 'done') {
          title.classList.add('striked');
        } else {
          title.classList.remove('striked');
        }
      }

      // 3. Badge de status (atualiza classe e texto)
      var badge = card.querySelector('.task-status-badge');
      if (badge) {
        badge.classList.remove('badge-pending', 'badge-in_progress', 'badge-done');
        badge.classList.add('badge-' + newStatus);
        var labels = { pending: 'Pendente', in_progress: 'Em Andamento', done: 'Concluída' };
        badge.textContent = labels[newStatus] || newStatus;
      }
    }

    // 4. Garante que o select fica no valor correto
    if (selectEl) selectEl.value = newStatus;

    // 5. Recalcula contadores e barra de progresso
    _refreshStatCounters();

    // 6. Toast
    var msgs = { pending: '⏳ Marcada como pendente', in_progress: '🔄 Em andamento', done: '✅ Tarefa concluída!' };
    showToast(msgs[newStatus] || 'Status atualizado', newStatus === 'done' ? 'success' : 'default');
  })
  .catch(function(err) {
    console.error('[TaskFlow] updateTaskStatus:', err);
    showToast('⚠️ Erro ao atualizar. Tente novamente.', 'error');
  })
  .finally(function() {
    if (selectEl) {
      selectEl.disabled = false;
      selectEl.style.opacity = '';
    }
  });
};

/* Recalcula contadores percorrendo os selects dos cards */
function _refreshStatCounters() {
  var cards = document.querySelectorAll('.task-card[id^="task-card-"]');
  if (!cards.length) return;

  var pending = 0, inProgress = 0, done = 0;

  cards.forEach(function(card) {
    var sel = card.querySelector('.status-select');
    if (!sel) return;
    if (sel.value === 'pending')     pending++;
    else if (sel.value === 'in_progress') inProgress++;
    else if (sel.value === 'done')   done++;
  });

  var total = cards.length;
  var pct   = total > 0 ? Math.round((done / total) * 100) : 0;

  _setStatValue('[data-stat="total"]',       total);
  _setStatValue('[data-stat="pending"]',     pending);
  _setStatValue('[data-stat="in_progress"]', inProgress);
  _setStatValue('[data-stat="done"]',        done);

  // Barra de progresso
  var bar      = document.querySelector('.progress-fill');
  var pctLabel = document.querySelector('[data-stat="progress-pct"]');
  if (bar)      bar.style.width = pct + '%';
  if (pctLabel) pctLabel.textContent = pct + '%';
}

function _setStatValue(selector, value) {
  var el = document.querySelector(selector + ' .stat-value');
  if (el) el.textContent = value;
}


/* ══════════════════════════════════════════════════════════
   CONFIRM DELETE
══════════════════════════════════════════════════════════ */

document.querySelectorAll('form[data-confirm]').forEach(function(form) {
  form.addEventListener('submit', function(e) {
    var msg = form.dataset.confirm || 'Tem certeza que deseja excluir?';
    if (!confirm(msg)) e.preventDefault();
  });
});


/* ══════════════════════════════════════════════════════════
   PROGRESS BARS — anima na entrada
══════════════════════════════════════════════════════════ */

(function animateProgress() {
  requestAnimationFrame(function() {
    requestAnimationFrame(function() {
      document.querySelectorAll('.progress-fill[data-width]').forEach(function(bar) {
        bar.style.width = bar.dataset.width + '%';
      });
    });
  });
})();