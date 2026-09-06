/* Public marketing site behaviour: renders only published exam metadata that
   the public API exposes. No question content or answers are fetched here. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function getJSON(url) {
    return fetch(url, { cache: 'no-store', credentials: 'same-origin' }).then(function (response) {
      if (!response.ok) throw new Error('Request failed: ' + response.status);
      return response.json();
    });
  }

  function stateMessage(title, detail) {
    return '<div class="state-message"><h3>' + esc(title) + '</h3><p>' + esc(detail) + '</p></div>';
  }

  function skeletons(count) {
    var html = '';
    for (var i = 0; i < count; i += 1) html += '<div class="skeleton" aria-hidden="true"></div>';
    return html;
  }

  function duration(exam) {
    return exam.duration_minutes ? exam.duration_minutes + ' min' : 'Untimed';
  }

  function examCard(exam) {
    var badges = (exam.badges || []).slice(0, 3).map(function (badge) {
      return '<span class="chip' + (badge === 'Practice' ? ' solid' : '') + '">' + esc(badge) + '</span>';
    }).join('');
    return '<article class="exam-card">' +
      '<div class="chip-row">' + badges + '</div>' +
      '<div><p class="kicker">' + esc(exam.subject || exam.exam_type || 'Examination') + '</p>' +
      '<h3><a href="/exams/' + encodeURIComponent(exam.id) + '">' + esc(exam.name) + '</a></h3></div>' +
      (exam.description ? '<p>' + esc(exam.description).slice(0, 180) + '</p>' : '') +
      '<dl>' +
        '<div><dt>Questions</dt><dd>' + esc(exam.question_count || 0) + '</dd></div>' +
        '<div><dt>Duration</dt><dd>' + esc(duration(exam)) + '</dd></div>' +
        '<div><dt>Total marks</dt><dd>' + esc(exam.total_marks || '—') + '</dd></div>' +
        '<div><dt>Mode</dt><dd>' + esc(exam.mode === 'PROCTORED' ? 'Proctored' : 'Practice') + '</dd></div>' +
      '</dl>' +
      '<div class="chip-row"><a class="btn small primary" href="/exams/' + encodeURIComponent(exam.id) + '">View details</a>' +
      '<a class="btn small" href="/app">Sign in to attempt</a></div>' +
      '</article>';
  }

  function renderExams(container, exams, emptyTitle, emptyDetail) {
    if (!exams || !exams.length) {
      container.innerHTML = stateMessage(emptyTitle, emptyDetail);
      return;
    }
    container.innerHTML = exams.map(examCard).join('');
  }

  function applyBrand(config) {
    if (!config) return;
    if (config.brand_name) {
      document.title = config.brand_name + ' · Practice smarter. Master every exam.';
      [].forEach.call(document.querySelectorAll('[data-brand-name]'), function (node) {
        node.textContent = config.brand_name;
      });
    }
    if (config.support_email) {
      var item = $('footer-support');
      var link = $('footer-support-link');
      if (item && link) {
        link.href = 'mailto:' + config.support_email;
        link.textContent = config.support_email;
        item.hidden = false;
      }
    }
  }

  function showAuthState(user) {
    var signedIn = !!(user && user.email);
    [].forEach.call(document.querySelectorAll('[data-auth]'), function (node) {
      node.hidden = node.dataset.auth === (signedIn ? 'signed-out' : 'signed-in');
    });
    var account = $('nav-account');
    if (signedIn && account) account.textContent = user.display_name || user.email;
  }

  function loadHome() {
    var grid = $('trending-grid');
    grid.innerHTML = '<div class="skeleton-grid">' + skeletons(3) + '</div>';
    return getJSON('/api/public/home').then(function (data) {
      applyBrand(data);
      $('trending-title').textContent = data.trending_label;
      $('trending-subtitle').textContent = data.trending_is_ranked
        ? 'Ranked by the number of attempts recorded on this platform.'
        : 'Published examinations available on this platform right now.';
      renderExams(grid, data.trending_exams, 'Practice exams are being prepared',
        'No examinations have been published yet. Sign in to your account to be notified when they go live.');

      var stats = data.stats || {};
      if (stats.published_exams || stats.question_bank_size) {
        $('stat-exams').textContent = stats.published_exams || 0;
        $('stat-subjects').textContent = stats.subjects || 0;
        $('stat-questions').textContent = stats.question_bank_size || 0;
        $('hero-stats').hidden = false;
      }

      var categories = $('category-row');
      if (!data.categories || !data.categories.length) {
        categories.innerHTML = '<p style="color:var(--text-muted)">Categories appear here once exams are published.</p>';
      } else {
        categories.innerHTML = data.categories.map(function (category) {
          return '<a href="/explore?' + encodeURIComponent(category.kind) + '=' + encodeURIComponent(category.value) + '">' +
            esc(category.value) + ' <b>' + esc(category.count) + '</b></a>';
        }).join('');
      }
    }).catch(function () {
      grid.innerHTML = stateMessage('Exam catalogue unavailable', 'We could not load published exams right now. Please try again shortly.');
    });
  }

  function loadExplore() {
    var grid = $('explore-grid');
    var search = $('explore-search');
    var select = $('explore-category');
    var params = new URLSearchParams(location.search);
    var filters = { subject: params.get('subject') || '', level: params.get('level') || '', exam_type: params.get('exam_type') || '' };
    search.value = params.get('q') || '';

    function activeCategory() {
      return filters.subject ? 'subject:' + filters.subject
        : filters.level ? 'level:' + filters.level
        : filters.exam_type ? 'exam_type:' + filters.exam_type : '';
    }

    function fetchExams() {
      grid.innerHTML = '<div class="skeleton-grid">' + skeletons(6) + '</div>';
      var query = new URLSearchParams();
      if (search.value.trim()) query.set('q', search.value.trim());
      Object.keys(filters).forEach(function (key) { if (filters[key]) query.set(key, filters[key]); });
      return getJSON('/api/public/exams?' + query.toString()).then(function (data) {
        if (select.options.length <= 1 && data.categories) {
          data.categories.forEach(function (category) {
            var option = document.createElement('option');
            option.value = category.kind + ':' + category.value;
            option.textContent = category.value + ' (' + category.count + ')';
            select.appendChild(option);
          });
          select.value = activeCategory();
        }
        renderExams(grid, data.exams, 'No matching exams',
          'No published exam matches these filters yet. Try a different search or category.');
      }).catch(function () {
        grid.innerHTML = stateMessage('Exam catalogue unavailable', 'We could not load published exams right now. Please try again shortly.');
      });
    }

    var timer;
    search.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(fetchExams, 250);
    });
    select.addEventListener('change', function () {
      filters = { subject: '', level: '', exam_type: '' };
      if (select.value) {
        var parts = select.value.split(':');
        filters[parts[0]] = parts.slice(1).join(':');
      }
      fetchExams();
    });
    return fetchExams();
  }

  function loadDetail(examId) {
    var body = $('detail-body');
    body.innerHTML = '<div class="skeleton-grid">' + skeletons(2) + '</div>';
    return getJSON('/api/public/exams/' + encodeURIComponent(examId)).then(function (exam) {
      document.title = exam.name + ' · Question Bank';
      body.innerHTML = '<div class="detail-head">' +
        '<div><div class="chip-row">' + (exam.badges || []).map(function (badge) {
          return '<span class="chip solid">' + esc(badge) + '</span>';
        }).join('') + '</div>' +
        '<h1 style="margin:14px 0 0">' + esc(exam.name) + '</h1>' +
        (exam.description ? '<p style="color:var(--text-secondary);font-size:17px">' + esc(exam.description) + '</p>' : '') +
        '<p style="color:var(--text-muted)">Questions, options and answers are only available inside a started attempt.</p></div>' +
        '<aside class="detail-card">' +
        '<dl>' +
          '<div><dt>Questions</dt><dd>' + esc(exam.question_count || 0) + '</dd></div>' +
          '<div><dt>Duration</dt><dd>' + esc(duration(exam)) + '</dd></div>' +
          '<div><dt>Total marks</dt><dd>' + esc(exam.total_marks || '—') + '</dd></div>' +
          '<div><dt>Attempts allowed</dt><dd>' + esc(exam.max_attempts || '—') + '</dd></div>' +
          '<div><dt>Mode</dt><dd>' + esc(exam.mode === 'PROCTORED' ? 'Proctored' : 'Practice') + '</dd></div>' +
          '<div><dt>Status</dt><dd>' + esc(exam.status) + '</dd></div>' +
        '</dl>' +
        '<a class="btn primary" href="/app">Sign in to attempt</a>' +
        (exam.mode === 'PROCTORED' ? '<p style="margin:0;color:var(--text-muted);font-size:14px">This is a proctored examination. You will need the access code issued by your invigilator.</p>' : '') +
        '</aside></div>';
    }).catch(function () {
      body.innerHTML = stateMessage('Exam not available', 'This exam is not published, or the link is no longer valid.');
    });
  }

  function route() {
    var detailMatch = location.pathname.match(/^\/exams\/(\d+)\/?$/);
    var explore = /^\/explore\/?$/.test(location.pathname);
    $('home-view').hidden = explore || !!detailMatch;
    $('explore-view').hidden = !explore;
    $('detail-view').hidden = !detailMatch;
    if (detailMatch) return loadDetail(detailMatch[1]);
    if (explore) return loadExplore();
    return loadHome();
  }

  var toggle = $('nav-toggle');
  if (toggle) {
    toggle.addEventListener('click', function () {
      var open = $('site-nav').classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(open));
    });
  }
  $('footer-year').textContent = String(new Date().getFullYear());

  getJSON('/api/public/config').then(applyBrand).catch(function () {});
  getJSON('/api/auth/me').then(showAuthState).catch(function () { showAuthState(null); });
  route();
})();
