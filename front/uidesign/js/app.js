/* chan.py 前端设计稿 — 轻量交互脚本（静态稿演示用） */
(function () {
  'use strict';

  /* 开关 Switch */
  document.addEventListener('click', function (e) {
    var sw = e.target.closest('.switch');
    if (sw) sw.classList.toggle('is-on');
  });

  /* 复选框 */
  document.addEventListener('click', function (e) {
    var cb = e.target.closest('.checkbox');
    if (cb) cb.classList.toggle('is-checked');
  });

  /* Select 下拉 */
  document.addEventListener('click', function (e) {
    var trigger = e.target.closest('.select__trigger');
    if (trigger) {
      var select = trigger.closest('.select');
      var wasOpen = select.classList.contains('is-open');
      closeAllSelects();
      if (!wasOpen) select.classList.add('is-open');
      return;
    }
    var opt = e.target.closest('.select__option');
    if (opt) {
      var sel = opt.closest('.select');
      if (sel.classList.contains('select--multi')) return; // 多选交给下方处理器
      sel.querySelectorAll('.select__option').forEach(function (o) {
        o.classList.remove('is-selected');
      });
      opt.classList.add('is-selected');
      var label = sel.querySelector('.select__value');
      if (label) label.textContent = opt.getAttribute('data-label') || opt.textContent.trim();
      sel.classList.remove('is-open');
      return;
    }
    closeAllSelects();
  });

  function closeAllSelects() {
    document.querySelectorAll('.select.is-open').forEach(function (s) {
      s.classList.remove('is-open');
    });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAllSelects();
  });

  /* 多选下拉（指标菜单）：勾选但不关闭 */
  document.addEventListener('click', function (e) {
    var opt = e.target.closest('.select--multi .select__option');
    if (opt) {
      e.stopPropagation();
      var dot = opt.querySelector('.check-dot');
      if (dot) dot.classList.toggle('is-on');
    }
  });

  /* Drawer */
  document.addEventListener('click', function (e) {
    var open = e.target.closest('[data-open-drawer]');
    if (open) {
      var id = open.getAttribute('data-open-drawer');
      var d = document.querySelector(id);
      if (d) { d.classList.add('is-open'); d.querySelector('.overlay') && d.querySelector('.overlay').classList.add('is-open'); showOverlay(); }
      return;
    }
    var close = e.target.closest('[data-close-drawer], .overlay');
    if (close) { closeAllDrawers(); }
  });

  function showOverlay() { document.querySelectorAll('.overlay').forEach(function (o) { o.classList.add('is-open'); }); }
  function closeAllDrawers() {
    document.querySelectorAll('.drawer.is-open').forEach(function (d) { d.classList.remove('is-open'); });
    document.querySelectorAll('.overlay').forEach(function (o) { o.classList.remove('is-open'); });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAllDrawers();
  });

  /* Tabs（通用 .tabs + .tab，切换 [data-tab] 面板） */
  document.addEventListener('click', function (e) {
    var tab = e.target.closest('.tab');
    if (!tab) return;
    var tabs = tab.closest('.tabs');
    var key = tab.getAttribute('data-tab');
    tabs.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('is-active'); });
    tab.classList.add('is-active');
    var scope = tabs.getAttribute('data-scope');
    var root = scope ? document.querySelector(scope) : tabs.parentElement;
    root.querySelectorAll('[data-pane]').forEach(function (p) {
      p.classList.toggle('hidden', p.getAttribute('data-pane') !== key);
    });
  });

  /* 分段切换 .seg */
  document.addEventListener('click', function (e) {
    var item = e.target.closest('.seg__item');
    if (!item) return;
    var seg = item.closest('.seg');
    seg.querySelectorAll('.seg__item').forEach(function (i) { i.classList.remove('is-active'); });
    item.classList.add('is-active');
  });

  /* 顶部导航菜单选中态 */
  document.addEventListener('click', function (e) {
    var mi = e.target.closest('.menu-item');
    if (!mi) return;
    mi.closest('.topnav__menu').querySelectorAll('.menu-item').forEach(function (m) {
      m.classList.remove('is-active');
    });
    mi.classList.add('is-active');
  });

  /* Dialog 弹窗 */
  document.addEventListener('click', function (e) {
    var open = e.target.closest('[data-open-dialog]');
    if (open) {
      var d = document.querySelector(open.getAttribute('data-open-dialog'));
      if (d) d.classList.add('is-open');
      return;
    }
    var close = e.target.closest('[data-close-dialog]');
    if (close) {
      var dlg = close.closest('.dialog');
      if (dlg) dlg.classList.remove('is-open');
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') document.querySelectorAll('.dialog.is-open').forEach(function (d) { d.classList.remove('is-open'); });
  });
})();
