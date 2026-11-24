/* ============================================================
   新闻世界地图 · 交互逻辑
   ============================================================ */
(function () {
  'use strict';

  // ---------------------------------------------------------------- 配色
  var COLOR = {
    high:   '#ff5f56',
    medium: '#4aa3ff',
    low:    '#8b9ab5',
    custom: '#ffb547'
  };
  var LABEL_CN = {
    high: '城市级', medium: '国家/州级', low: '来源地推断', custom: '自定义'
  };

  // ---------------------------------------------------------------- 状态
  var state = {
    all: [],        // 全部新闻
    visible: [],    // 经过筛选的新闻
    custom: [],     // 用户自定义新闻点
    from: null,     // YYYY-MM-DD
    to: null,
    query: '',
    tab: 'all',
    sort: 'time',
    addMode: false,
    pendingCoord: null,
    activeId: null,
    generatedAt: '',     // 展示用：'2026-11-24 02:49:02 UTC'
    generatedAtRaw: ''   // 比较用：服务端原始值 '2026-11-24T02:49:02Z'
  };

  var map, countryLayer, markerLayer, focusLayer, markerById = {};
  var pendingFocus = null, focusAttempts = 0;
  var openItemId = null, restoring = false;
  var els = {};

  // ---------------------------------------------------------------- 详情卡
  // 详情卡用 Leaflet Popup 承载：
  //   悬停圆点 → 立刻显示（预览态，移开鼠标自动关闭）
  //   点击圆点 → 固定住（移开鼠标也不关，方便点「阅读原文」）
  var cardMarker = null;   // 当前显示详情卡的标记
  var cardPopup = null;    // 当前打开的详情弹窗
  var cardPinned = false;  // 卡片是否被点击固定
  var cardTimer = null;    // 移出后的延迟关闭定时器
  // 触屏设备没有 hover，仍走「点击打开」；用 (hover:hover) 判定，
  // 否则触屏上「点一下 → 卡片开了又立刻被延迟关闭」。
  var CAN_HOVER = !window.matchMedia || window.matchMedia('(hover: hover)').matches;

  // ---------------------------------------------------------------- 工具
  function $(id) { return document.getElementById(id); }
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function isoDate(d) { return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()); }
  function parseISO(s) {
    var p = String(s || '').split('-');
    return new Date(Date.UTC(+p[0], (+p[1] || 1) - 1, +p[2] || 1));
  }
  function dayKey(iso) { return (iso || '').slice(0, 10); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function fmtAbs(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) +
           ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ' UTC';
  }
  function fmtRel(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return '刚刚';
    if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
    if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
    if (s < 86400 * 30) return Math.floor(s / 86400) + ' 天前';
    return fmtAbs(iso).slice(0, 10);
  }
  function fmtDay(d) {
    var wk = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getUTCDay()];
    return (d.getUTCMonth() + 1) + '月' + d.getUTCDate() + '日 ' + wk;
  }

  // ---------------------------------------------------------------- 数据
  function loadData() {
    return new Promise(function (resolve) {
      var payload = window.__NEWS__;
      if (payload && payload.items) { resolve(payload); return; }
      fetch('data/news.json')
        .then(function (r) { return r.json(); })
        .then(resolve)
        .catch(function (e) {
          showStatus('无法加载数据：' + e.message
            + '（仓库不含新闻数据，请先运行 python3 -m collector.collect，再运行 python3 scripts/publish.py）', true);
          resolve({ items: [], count: 0, generated_at: '' });
        });
    });
  }

  /**
   * 按随快照一同发布的契约校验数据。
   *
   * 契约缺失（只拷了数据没拷契约）时静默跳过；校验不过也只提示、不阻断渲染——
   * 地图端是消费者，只负责报告，不越权拒绝。
   */
  function checkContract(payload) {
    var spec = window.__NWM_CONTRACT__;
    if (!spec || !window.NWMContract) return;
    var errors = window.NWMContract.validate(payload, spec);
    if (!errors || !errors.length) return;
    showStatus('数据与契约 ' + (spec.version || '') + ' 不一致（' + errors.length + ' 处）：'
      + errors.slice(0, 2).join('；') + (errors.length > 2 ? ' 等' : ''), true);
  }

  function loadCustom() {
    try {
      var raw = localStorage.getItem('nwm.custom.v1');
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  }
  function saveCustom() {
    try { localStorage.setItem('nwm.custom.v1', JSON.stringify(state.custom)); } catch (e) {}
  }

  // ---------------------------------------------------------------- 散开
  /**
   * 同一地点的多条新闻坐标完全相同（例如所有兜底到美国的新闻都落在华盛顿），
   * 叠在一起永远点不开。这里按黄金角螺旋给它们一个稳定的微小偏移，
   * 偏移量基于「全量数据」计算，因此筛选时不会跳动。
   */
  function spreadLocations(items) {
    var groups = {};
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (it.lat == null || it.lon == null) continue;
      var key = Math.round(it.lat * 100) + ':' + Math.round(it.lon * 100);
      (groups[key] || (groups[key] = [])).push(it);
    }
    for (var k in groups) {
      if (!Object.prototype.hasOwnProperty.call(groups, k)) continue;
      var g = groups[k];
      for (var j = 0; j < g.length; j++) {
        if (g.length === 1) { g[j]._dx = 0; g[j]._dy = 0; continue; }
        var ang = j * 2.39996323;          // 黄金角
        var rad = 0.30 * Math.sqrt(j);     // 半径按 sqrt 递增，分布更均匀
        g[j]._dx = rad * Math.cos(ang);
        g[j]._dy = rad * Math.sin(ang);
      }
    }
  }

  // ---------------------------------------------------------------- 筛选
  function applyFilter() {
    var fromTs = state.from ? parseISO(state.from).getTime() : -Infinity;
    var toTs = state.to ? parseISO(state.to).getTime() + 86400000 - 1 : Infinity;
    var q = state.query.trim().toLowerCase();

    var out = [];
    for (var i = 0; i < state.all.length; i++) {
      var it = state.all[i];
      var t = new Date(it.published_at).getTime();
      if (t < fromTs || t > toTs) continue;
      if (q) {
        var hay = (it.title + ' ' + (it.summary || '') + ' ' +
                   ((it.location && (it.location.name + ' ' + (it.location.zh || ''))) || '')).toLowerCase();
        if (hay.indexOf(q) === -1) continue;
      }
      out.push(it);
    }

    if (state.sort === 'conf') {
      out.sort(function (a, b) { return (b.confidence || 0) - (a.confidence || 0); });
    } else if (state.sort === 'source') {
      out.sort(function (a, b) {
        return a.source === b.source ? 0 : (a.source < b.source ? -1 : 1);
      });
    } else {
      out.sort(function (a, b) {
        return new Date(b.published_at).getTime() - new Date(a.published_at).getTime();
      });
    }

    state.visible = out;
  }

  // ---------------------------------------------------------------- 反经线切分
  /**
   * 修正跨 180° 经线的多边形（antimeridian wrap）。
   *
   * Natural Earth 110m 里俄罗斯、斐济等国的边界环直接跨越 ±180°，
   * 展开成平面地图后，填充会沿接缝横贯整幅地图——表现为一条贯穿全图的陆地带，
   * 看起来就像「俄罗斯那块错位了」。
   *
   * 做法：
   *   1. 把环的经度「展开」：相邻点跳变超过 180° 时加减 360，得到连续的环；
   *   2. 用 Sutherland–Hodgman 把环裁到 [-180,180] 的条带；
   *   3. 落在条带外的部分平移 ±360 后，作为独立多边形补到地图另一侧。
   *
   * 裁剪产生的所有缝合边都落在 lon=±180 上，正好是地图的左右边界，视觉上看不见。
   * 环绕极点的环（南极洲）解开后跨度 ≥360°，保持原样不动。
   */
  function unwrapRing(ring) {
    var out = [[ring[0][0], ring[0][1]]];
    for (var i = 1; i < ring.length; i++) {
      var lon = ring[i][0];
      var d = lon - out[i - 1][0];
      if (d > 180) lon -= 360;
      else if (d < -180) lon += 360;
      out.push([lon, ring[i][1]]);
    }
    return out;
  }

  function ringHasSeamJump(ring) {
    for (var i = 1; i < ring.length; i++) {
      if (Math.abs(ring[i][0] - ring[i - 1][0]) > 180) return true;
    }
    return false;
  }

  function intersectAtX(a, b, x) {
    var t = (x - a[0]) / (b[0] - a[0]);
    return [x, a[1] + t * (b[1] - a[1])];
  }

  /** 用一条竖直线裁剪环（Sutherland–Hodgman 半平面裁剪）。 */
  function clipRingAtX(ring, x, keepGreater) {
    var res = [], n = ring.length;
    if (n < 3) return res;
    for (var i = 0; i < n; i++) {
      var cur = ring[i], prev = ring[(i + n - 1) % n];
      var curIn = keepGreater ? cur[0] >= x : cur[0] <= x;
      var prevIn = keepGreater ? prev[0] >= x : prev[0] <= x;
      if (curIn) {
        if (!prevIn) res.push(intersectAtX(prev, cur, x));
        res.push(cur);
      } else if (prevIn) {
        res.push(intersectAtX(prev, cur, x));
      }
    }
    return res;
  }

  function closeRing(ring) {
    if (ring.length < 3) return ring;
    var f = ring[0], l = ring[ring.length - 1];
    if (f[0] !== l[0] || f[1] !== l[1]) ring.push([f[0], f[1]]);
    return ring;
  }

  /** 返回切分后的环数组；不需要切分时返回 null。 */
  function splitRing(ring) {
    if (!ringHasSeamJump(ring)) return null;
    var u = unwrapRing(ring);
    var umin = Infinity, umax = -Infinity;
    for (var i = 0; i < u.length; i++) {
      if (u[i][0] < umin) umin = u[i][0];
      if (u[i][0] > umax) umax = u[i][0];
    }
    if (umax - umin >= 360) return null;   // 环绕极点（如南极洲），保持原样
    var pieces = [];
    var kStart = Math.floor((umin + 180) / 360);
    var kEnd = Math.floor((umax + 180) / 360);
    for (var k = kStart; k <= kEnd; k++) {
      var lo = -180 + 360 * k, hi = 180 + 360 * k;
      var r = clipRingAtX(u, lo, true);
      if (r.length < 3) continue;
      r = clipRingAtX(r, hi, false);
      if (r.length < 3) continue;
      var shifted = [];
      for (var j = 0; j < r.length; j++) shifted.push([r[j][0] - 360 * k, r[j][1]]);
      pieces.push(closeRing(shifted));
    }
    return pieces.length ? pieces : null;
  }

  /** 一个多边形（外环 + 若干洞）切分后的多边形数组。 */
  function splitPolygon(poly) {
    var outer = splitRing(poly[0]);
    if (!outer) return null;
    var holes = [];
    for (var i = 1; i < poly.length; i++) holes.push(splitRing(poly[i]) || [poly[i]]);
    var out = [];
    var pairable = holes.length > 0;
    for (var h = 0; h < holes.length; h++) {
      if (holes[h].length !== outer.length) { pairable = false; break; }
    }
    if (pairable) {
      for (var o = 0; o < outer.length; o++) {
        var poly2 = [outer[o]];
        for (var q = 0; q < holes.length; q++) poly2.push(holes[q][o]);
        out.push(poly2);
      }
    } else {
      for (var o2 = 0; o2 < outer.length; o2++) out.push([outer[o2]]);
      for (var h2 = 0; h2 < holes.length; h2++) {
        for (var h3 = 0; h3 < holes[h2].length; h3++) out.push([holes[h2][h3]]);
      }
    }
    return out;
  }

  /** 对整个 GeoJSON 做反经线切分，返回新的 FeatureCollection。 */
  function splitAntimeridian(geojson) {
    var feats = geojson.features || [];
    var out = [];
    for (var i = 0; i < feats.length; i++) {
      var f = feats[i], g = f.geometry;
      if (!g || (g.type !== 'Polygon' && g.type !== 'MultiPolygon')) { out.push(f); continue; }
      var polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
      var newPolys = [], changed = false;
      for (var p = 0; p < polys.length; p++) {
        var sp = splitPolygon(polys[p]);
        if (sp) { newPolys = newPolys.concat(sp); changed = true; }
        else newPolys.push(polys[p]);
      }
      if (!changed) { out.push(f); continue; }
      var g2 = g.type === 'Polygon'
        ? { type: 'Polygon', coordinates: newPolys[0] }
        : { type: 'MultiPolygon', coordinates: newPolys };
      out.push({
        type: 'Feature',
        properties: f.properties,
        geometry: g2
      });
    }
    return { type: 'FeatureCollection', features: out };
  }

  // ---------------------------------------------------------------- 地图
  function initMap() {
    map = L.map('map', {
      center: [22, 12],
      zoom: 2,
      minZoom: 2,
      maxZoom: 9,
      zoomControl: true,
      attributionControl: true,
      worldCopyJump: false,
      maxBounds: [[-85, -230], [88, 230]],
      maxBoundsViscosity: 0.7
    });
    map.attributionControl.setPrefix('');
    // 缩放控件放右下（避开左上角的统计条），版权信息挪到左下
    map.zoomControl.setPosition('bottomright');
    map.attributionControl.setPosition('bottomleft');

    // 矢量世界地图（无瓦片，完全离线可渲染）
    var topo = window.__WORLD_TOPO__;
    if (topo && window.topojson) {
      var geo = topojson.feature(topo, topo.objects.countries);
      // 跨 180° 经线的国家（俄罗斯、斐济…）填充会横贯整幅地图，先做反经线切分
      geo = splitAntimeridian(geo);
      countryLayer = L.geoJSON(geo, {
        style: function () {
          return {
            color: cssVar('--coast'),
            weight: 0.7,
            fillColor: cssVar('--land'),
            fillOpacity: 1
          };
        },
        onEachFeature: function (feature, layer) {
          var n = (feature.properties && feature.properties.name) || '';
          layer.bindTooltip(n, { sticky: true, direction: 'top', className: 'cty-tip' });
          layer.on('mouseover', function () { layer.setStyle({ fillColor: cssVar('--land-hover') }); });
          layer.on('mouseout', function () { layer.setStyle({ fillColor: cssVar('--land') }); });
        }
      }).addTo(map);

      // 经纬网
      var grid = [];
      for (var lat = -60; lat <= 60; lat += 30) {
        grid.push([[lat, -180], [lat, 180]]);
      }
      for (var lon = -150; lon <= 150; lon += 30) {
        grid.push([[-85, lon], [85, lon]]);
      }
      L.polyline(grid, { color: cssVar('--coast'), weight: 0.4, opacity: 0.55, interactive: false }).addTo(map);
    }

    markerLayer = L.layerGroup().addTo(map);
    // 聚焦图层独立于标记层：聚合重绘时不会把正在看的弹窗一起销毁
    focusLayer = L.layerGroup().addTo(map);
    // 只在 zoomend 重绘：聚类用的是「绝对投影坐标」分桶，与平移无关，
    // 平移时重绘毫无必要，反而会把正在看的弹窗连同它的标记一起销毁。
    map.on('zoomend', function () { renderMarkers(); openPendingPopup(); });
    map.on('click', onMapClick);

    // 详情卡（Popup）的打开/关闭统一在这里接管：
    //   - 全图同一时刻只允许一个弹窗：新弹窗打开时把旧的关掉
    //   - 打开时把卡片夹回可视区，并让指针移进卡片时不关闭
    //   - 关闭时清掉「固定」状态
    map.on('popupopen', function (e) {
      var pop = e.popup;
      closeOtherPopups(pop);
      // 聚合清单与详情卡互斥，避免两个面板叠在一起
      closeHoverTip(0);
      cardPopup = pop;
      if (!pop._nwmBase) pop._nwmBase = L.point(pop.options.offset);
      clampPopup(pop);

      var el = pop.getElement();
      if (el && !el._nwmCardBound) {
        el._nwmCardBound = true;
        // 指针移进卡片时先别关，否则点不到「阅读原文」「在地图上定位」
        el.addEventListener('mouseenter', function () { clearTimeout(cardTimer); });
        el.addEventListener('mouseleave', function () {
          if (!cardPinned) closeCardLater(150);
        });
      }
      // 图片挂掉时 onerror 会把 img 藏掉，卡片高度随之变化，得重新夹一次；
      // 再留一个兜底延时，覆盖图片加载特别慢的情况。
      var img = el && el.querySelector('img.card-img');
      if (img && !img._nwmBound) {
        img._nwmBound = true;
        img.addEventListener('error', function () { clampPopup(pop); });
      }
      setTimeout(function () { clampPopup(pop); }, 220);
    });

    map.on('popupclose', function (e) {
      // Leaflet 关闭弹窗时默认还留着 200ms 的淡出动画，那段时间新旧两张卡
      // 会同时出现在画面上。这里把旧卡直接从 DOM 摘掉，保证任何时刻只有一张卡。
      var el = e.popup.getElement && e.popup.getElement();
      if (el && el.parentNode) el.parentNode.removeChild(el);
      if (cardPopup === e.popup) {
        cardPopup = null;
        cardPinned = false;
      }
    });
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#16233d';
  }

  // ---------------------------------------------------------------- 标记渲染（网格聚合）
  function renderMarkers() {
    var prevOpen = openItemId;
    markerLayer.clearLayers();
    markerById = {};

    var zoom = map.getZoom();
    var cell = zoom <= 3 ? 78 : zoom <= 5 ? 66 : 54;
    var buckets = {};

    for (var i = 0; i < state.visible.length; i++) {
      var it = state.visible[i];
      if (it.lat == null || it.lon == null) continue;
      var pt = map.project([it.lat + (it._dy || 0), it.lon + (it._dx || 0)], zoom);
      var key = Math.floor(pt.x / cell) + ':' + Math.floor(pt.y / cell);
      var b = buckets[key];
      if (!b) {
        b = buckets[key] = { items: [], lat: 0, lon: 0 };
      }
      b.items.push(it);
      b.lat += it.lat;
      b.lon += it.lon;
    }

    for (var key2 in buckets) {
      if (!Object.prototype.hasOwnProperty.call(buckets, key2)) continue;
      var bk = buckets[key2];
      var n = bk.items.length;
      var lat = bk.lat / n, lon = bk.lon / n;

      if (n === 1) {
        var one = bk.items[0];
        addMarker(one, one.lat + (one._dy || 0), one.lon + (one._dx || 0));
      } else {
        addCluster(bk.items, lat, lon, n);
      }
    }

    // 重绘会销毁旧标记，正在看的弹窗需要重新打开
    if (prevOpen && !restoring) {
      restoring = true;
      var pm = markerById[prevOpen];
      if (pm) {
        pm.openPopup();
      } else {
        var pit = findItem(prevOpen);
        if (pit) openStandalonePopup(pit);
      }
      restoring = false;
    }
  }

  function addMarker(it, lat, lon) {
    var key = it.confidence_label || 'low';
    var color = COLOR[key] || COLOR.low;
    var radius = key === 'high' ? 7 : key === 'medium' ? 5.5 : 4.5;
    var m = L.circleMarker([lat, lon], {
      radius: radius,
      className: 'news-marker',
      color: '#0a1220',
      weight: key === 'high' ? 1.6 : 1.1,
      fillColor: color,
      fillOpacity: 0.92
    });
    // autoPan:false —— 悬停开卡时不能把地图带着跳；
    // 越界改由 clampPopup 手动把卡片夹回可视区。
    m.bindPopup(popupHTML(it), { maxWidth: 340, minWidth: 300, autoPan: false });
    bindMarkerHover(m, it);
    m.on('click', function () { setActive(it.id, false); openItemId = it.id; cardPinned = true; });
    m.on('popupclose', function () {
      if (!restoring) openItemId = null;
      if (cardMarker === m) cardMarker = null;
    });
    m.addTo(markerLayer);
    markerById[it.id] = m;
  }

  function addCluster(items, lat, lon, n) {
    // 颜色取多数派，而不是最高置信度——
    // 否则一堆「来源地推断」的兜底新闻会被单个城市级条目染成红色。
    var tally = { high: 0, medium: 0, low: 0, custom: 0 };
    for (var i = 0; i < items.length; i++) {
      var k = items[i].confidence_label || 'low';
      if (tally[k] === undefined) tally[k] = 0;
      tally[k]++;
    }
    var best = 'low';
    var bestN = -1;
    ['custom', 'high', 'medium', 'low'].forEach(function (k) {
      if (tally[k] > bestN) { bestN = tally[k]; best = k; }
    });
    var size = Math.min(40, 15 + Math.sqrt(n) * 4.2);
    var color = COLOR[best] || COLOR.low;
    var icon = L.divIcon({
      className: '',
      html: '<div class="cluster-marker" style="width:' + size + 'px;height:' + size + 'px;' +
            'background:' + color + ';line-height:' + (size - 4) + 'px">' + n + '</div>',
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2]
    });
    var m = L.marker([lat, lon], { icon: icon, riseOnHover: true });
    m.on('click', function () {
      var z = map.getZoom();
      map.setView([lat, lon], z >= 8 ? z : z + 2, { animate: true });
    });
    bindClusterHover(m, clusterListHTML(items));
    m.addTo(markerLayer);
  }

  // ---------------------------------------------------------------- 聚合点悬停
  /**
   * 聚合圆点悬停时弹出该位置的新闻清单，点条目即可跳转到对应新闻详情。
   *
   * 实现要点：
   *   1. 用 Leaflet 的 Tooltip 而非 Popup——Tooltip 的 direction:'auto' 会自动
   *      落在圆点左侧或右侧，不会把圆点本身盖住；且 Tooltip 没有 autoPan，
   *      悬停时地图不会跟着跳。
   *   2. 打开沿用 Leaflet 自带的 mouseover，但要接管 mouseout：默认是移出即关，
   *      指针根本来不及移到面板上。改成延迟关闭。
   *   3. 面板本身再监听移入/移出——指针停在面板里时不关闭，
   *      这样「悬停 → 移到面板 → 点某条 → 跳转详情」的流程才走得通。
   */
  var hoverTipMarker = null;
  var hoverTipTimer = null;

  function closeHoverTip(delay) {
    clearTimeout(hoverTipTimer);
    hoverTipTimer = setTimeout(function () {
      if (hoverTipMarker) {
        hoverTipMarker.closeTooltip();
        hoverTipMarker = null;
      }
    }, delay == null ? 300 : delay);
  }

  function bindClusterHover(marker, html) {
    marker.bindTooltip(html, {
      interactive: true,
      direction: 'auto',
      opacity: 1,
      offset: [0, 0],
      className: 'cluster-tip'
    });

    // 接管关闭时机：撤掉 Leaflet 默认的「mouseout 立即关闭」
    marker.off('mouseout', marker.closeTooltip);

    marker.on('mouseover', function () {
      // 同一时刻只留一个聚合面板：指针快速划过下一个聚合点时，
      // 上一个面板的延迟关闭会被这里 clearTimeout 取消掉，导致它永远关不掉，
      // 所以这里先把上一个立刻关掉。
      if (hoverTipMarker && hoverTipMarker !== marker) {
        clearTimeout(hoverTipTimer);
        hoverTipMarker.closeTooltip();
        hoverTipMarker = null;
      }
      clearTimeout(hoverTipTimer);
      hoverTipMarker = marker;
    });

    marker.on('mouseout', function () {
      if (hoverTipMarker === marker) closeHoverTip(300);
    });

    // 面板打开后接管面板自身的交互
    marker.on('tooltipopen', function () {
      // 聚合清单与详情卡互斥：同一时刻只留一个面板
      if (cardPopup) cardPopup.close();

      var tip = marker.getTooltip();
      var el = tip && tip.getElement();
      if (!el) return;

      // Tooltip 默认把面板垂直居中对准锚点，靠近地图上下边缘时会被裁掉，
      // 这里按实际高度把面板推回可视范围内。
      var size = map.getSize();
      var p = map.latLngToContainerPoint(marker.getLatLng());
      var h = el.offsetHeight || 0;
      var top = p.y - h / 2;
      var dy = 0;
      if (top < 6) dy = 6 - top;
      else if (top + h > size.y - 6) dy = (size.y - 6) - (top + h);
      tip.options.offset = [0, dy];
      tip.setLatLng(tip.getLatLng());

      // 面板内部的滚轮不要缩放地图，点击也不要冒泡到地图
      if (window.L && L.DomEvent) {
        L.DomEvent.disableScrollPropagation(el);
        L.DomEvent.disableClickPropagation(el);
      }

      if (!el._nwmHoverBound) {
        el._nwmHoverBound = true;
        el.addEventListener('mouseenter', function () { clearTimeout(hoverTipTimer); });
        el.addEventListener('mouseleave', function () { closeHoverTip(120); });

        // 点条目 → 跳转看详情。
        // 在面板上就地处理并阻止冒泡，避免点击同时触发地图的 click
        // （那会在「添加新闻点」模式下误开表单）。
        el.addEventListener('click', function (e) {
          var row = e.target.closest && e.target.closest('.cl-row');
          if (!row) return;
          e.preventDefault();
          e.stopPropagation();
          var id = row.getAttribute('data-id');
          closeHoverTip(0);
          focusItem(id);
        });
      }
    });
  }

  function clusterListHTML(items) {
    // 全部列出，容器超出高度时内部滚动——这样「选择任意一条跳转」才真正可用
    var rows = items.map(function (it) {
      return '<div class="cl-row" data-id="' + esc(it.id) + '">' +
        '<i class="ni-dot ' + (it.confidence_label || 'low') + '"></i>' +
        '<span>' + esc(it.title) + '</span></div>';
    }).join('');
    return '<div class="cl-card">' +
      '<div class="cl-head">此位置共 ' + items.length + ' 条</div>' +
      '<div class="cl-list">' + rows + '</div>' +
      '</div>';
  }

  // ---------------------------------------------------------------- 详情卡片
  function popupHTML(it) {
    var loc = it.location || {};
    var locName = loc.zh || loc.name || '';
    var locEn = loc.name && loc.zh ? loc.name : '';
    var key = it.confidence_label || 'low';
    var places = (it.places || []).filter(function (p) {
      return !(loc.name && p.name === loc.name);
    }).slice(0, 4);

    var img = it.image
      ? '<img class="card-img" src="' + esc(it.image) + '" alt="" onerror="this.style.display=\'none\'">'
      : '';

    var links = '';
    if (it.url) {
      links += '<a class="btn btn-primary" href="' + esc(it.url) + '" target="_blank" rel="noopener">阅读原文</a>';
    }
    links += '<button class="btn btn-ghost" data-locate="' + esc(it.id) + '">在地图上定位</button>';

    var placeLine = '';
    if (places.length) {
      placeLine = '<div class="card-places">其他相关地点：' +
        places.map(function (p) { return '<span>' + esc(p.zh || p.name) + '</span>'; }).join('、') +
        '</div>';
    }

    return '<div class="card">' + img +
      '<div class="card-body">' +
        (locName ? '<div class="card-loc">' + esc(locName) +
          (locEn ? '<span class="sep">·</span>' + esc(locEn) : '') +
          (loc.country_zh ? '<span class="sep">·</span>' + esc(loc.country_zh) : '') + '</div>' : '') +
        '<h4 class="card-title">' +
          (it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + '</a>'
                  : esc(it.title)) +
        '</h4>' +
        (it.summary ? '<p class="card-sum">' + esc(it.summary) + '</p>' : '') +
        '<div class="card-meta">' +
          '<span>' + esc(it.source) + '</span><span>·</span>' +
          '<span>' + fmtRel(it.published_at) + '</span><span>·</span>' +
          '<span>' + fmtAbs(it.published_at) + '</span>' +
          '<span class="card-badge ' + key + '">' + (LABEL_CN[key] || key) + '</span>' +
        '</div>' +
        placeLine +
        '<div class="card-actions">' + links + '</div>' +
      '</div></div>';
  }

  // ---------------------------------------------------------------- 详情卡：悬停即看
  /**
   * 圆点悬停时直接显示详情卡。
   *
   * 要点：
   *   1. 预览态与固定态分开——悬停打开的是「预览」，移开鼠标 320ms 后自动关；
   *      点一下则变成「固定」，移开鼠标也留着，方便点「阅读原文」。
   *   2. 指针从圆点移到卡片上时不能立刻关，否则根本点不到卡片里的按钮，
   *      所以卡片本身也要监听 mouseenter / mouseleave。
   *   3. 标注模式（添加新闻点）下不弹卡片，免得干扰落点判断。
   */
  function bindMarkerHover(m, it) {
    if (!CAN_HOVER) return;

    m.on('mouseover', function () {
      if (state.addMode) return;
      clearTimeout(cardTimer);
      if (cardMarker === m) return;   // 已经是这张卡了
      cardMarker = m;
      cardPinned = false;            // 预览态：移开鼠标就关
      setActive(it.id, false);
      m.openPopup();
    });

    m.on('mouseout', function () {
      if (cardPinned) return;
      closeCardLater(320);
    });
  }

  function closeCardLater(delay) {
    clearTimeout(cardTimer);
    cardTimer = setTimeout(function () {
      if (cardPinned) return;
      // 注意：Popup 上没有 closePopup()（那是 Layer 的方法，Popup 继承过来后
      // 内部没有 _popup，调用会静默失效），必须用 close()。
      if (cardPopup) cardPopup.close();
    }, delay == null ? 320 : delay);
  }

  /**
   * 全图同一时刻只允许一个详情弹窗。
   *
   * 详情卡有两种来源：地图上的圆点（markerLayer）和侧栏定位到被聚合的新闻时
   * 临时画的独立标记（focusLayer）。Leaflet 只会自动关掉「自己那一个」，
   * 所以这里统一扫一遍地图图层，把除 keep 之外的弹窗都关掉。
   */
  function closeOtherPopups(keep) {
    var olds = [];
    map.eachLayer(function (l) {
      if (l !== keep && l instanceof L.Popup && map.hasLayer(l)) olds.push(l);
    });
    for (var i = 0; i < olds.length; i++) olds[i].close();
  }

  /**
   * 把详情卡放到合适的位置。
   *
   * 悬停开卡不能用 autoPan——那会把地图带着指针一起跳，用户根本没法悬停。
   * 改成自己算位置：
   *   1. 先把卡片复位到「贴着圆点正上方」的原始位置；
   *   2. 上方放得下就放上方；放不下就看下方放不放得下；
   *      两边都放不下才硬夹进可视区（卡片太高时 unavoidable）；
   *   3. 水平方向越界就平移。
   * Leaflet 的 popup 定位是「底边贴在锚点下方 offset.y 处」，
   * 所以 offset.y 为正表示向下移、offset.x 为正表示向右移。
   */
  /**
   * 只挪弹窗的位置，绝不重建卡片内容。
   *
   * Leaflet 的 Popup.update() 会把内容用 innerHTML 重新写一遍：
   * 卡片里的按钮因此被销毁重建，而重建期间容器是 visibility:hidden，
   * 按钮会「消失一帧」再回来——视觉上就是闪一下。
   * Leaflet 自己在缩放/复位时也只是调 _updatePosition()，所以这里照做即可。
   */
  function repositionPopup(pop) {
    if (!pop || !pop._map) return;
    pop._updatePosition();
  }

  function clampPopup(pop) {
    var el = pop && pop.getElement && pop.getElement();
    if (!el || !map || !pop.isOpen()) return;

    // 复位到原始位置（上一次可能被夹过）
    if (pop._nwmBase) {
      pop.options.offset = L.point(pop._nwmBase.x, pop._nwmBase.y);
      repositionPopup(pop);
    }

    var mRect = map.getContainer().getBoundingClientRect();
    var pRect = el.getBoundingClientRect();
    if (!pRect.width || !pRect.height) return;

    var PAD = 6;
    var dx = 0, dy = 0;

    // ---- 垂直：优先贴上方，放不下改贴下方 ----
    var src = pop._source;
    var anchorY = null;
    if (src && src.getLatLng) {
      anchorY = mRect.top + map.latLngToContainerPoint(src.getLatLng()).y;
    }
    if (anchorY !== null) {
      var aboveTop = pRect.bottom - pRect.height;   // 原始位置的上边缘
      var fitsAbove = aboveTop >= mRect.top + PAD;
      var fitsBelow = anchorY + 13 + pRect.height <= mRect.bottom - PAD;
      if (!fitsAbove && fitsBelow) {
        dy = (anchorY + 13) - aboveTop;             // 整张挪到圆点下方
      } else if (!fitsAbove) {
        dy = (mRect.top + PAD) - pRect.top;         // 两边都放不下，硬夹
      }
    } else if (pRect.top < mRect.top + PAD) {
      dy = (mRect.top + PAD) - pRect.top;
    } else if (pRect.bottom > mRect.bottom - PAD) {
      dy = (mRect.bottom - PAD) - pRect.bottom;
    }

    // ---- 水平：越界就平移 ----
    if (pRect.left < mRect.left + PAD) dx = (mRect.left + PAD) - pRect.left;
    else if (pRect.right > mRect.right - PAD) dx = (mRect.right - PAD) - pRect.right;

    if (!dx && !dy) {
      el.classList.remove('nwm-shifted');
      return;
    }
    var base = pop._nwmBase || L.point(0, 7);
    pop._nwmBase = base;
    pop.options.offset = L.point(base.x + dx, base.y + dy);
    repositionPopup(pop);
    // 卡片离开圆点后，小箭头就指错位置了，直接藏掉
    el.classList.add('nwm-shifted');
  }

  // ---------------------------------------------------------------- 侧栏
  function renderList() {
    var list = els.list;
    list.innerHTML = '';

    var items = state.visible;
    if (state.tab === 'unlocated') {
      items = items.filter(function (it) { return !it.located; });
    } else if (state.tab === 'high') {
      items = items.filter(function (it) { return it.confidence_label === 'high'; });
    }

    var unloc = state.visible.filter(function (it) { return !it.located; }).length;
    $('tab-unlocated-n').textContent = unloc;

    if (!items.length) {
      list.innerHTML = '<div class="empty">' +
        '<svg viewBox="0 0 24 24" width="34" height="34"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M16 16l5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>' +
        '<div>这个范围内没有新闻</div>' +
        '<div style="font-size:11.5px;margin-top:4px">试试放宽日期范围，或清空搜索词</div></div>';
      $('list-foot').textContent = '';
      return;
    }

    var groups = {};
    var order = [];
    for (var i = 0; i < items.length; i++) {
      var k = dayKey(items[i].published_at);
      if (!groups[k]) { groups[k] = []; order.push(k); }
      groups[k].push(items[i]);
    }
    order.sort(function (a, b) { return a < b ? 1 : -1; });

    for (var g = 0; g < order.length; g++) {
      var key = order[g];
      var arr = groups[key];
      var head = document.createElement('div');
      head.className = 'day-group';
      head.innerHTML = '<span>' + fmtDay(parseISO(key)) + '</span><span>' + arr.length + ' 条</span>';
      list.appendChild(head);

      for (var j = 0; j < arr.length; j++) {
        list.appendChild(newsItemEl(arr[j]));
      }
    }

    $('list-foot').innerHTML =
      '<span>显示 ' + items.length + ' / ' + state.all.length + ' 条</span>' +
      '<span id="foot-updated"></span>';
    var fu = $('foot-updated');
    if (fu && state.generatedAt) fu.textContent = '数据更新于 ' + state.generatedAt;
  }

  function newsItemEl(it) {
    var el = document.createElement('div');
    el.className = 'news-item';
    el.dataset.id = it.id;

    var key = it.confidence_label || 'low';
    var loc = it.location;
    var placeTxt = loc ? (loc.zh || loc.name) : '未定位';
    var thumb = '';
    if (it.image) {
      thumb = '<img class="ni-thumb" src="' + esc(it.image) + '" alt="" loading="lazy" onerror="this.remove()">';
    } else {
      var initial = esc((it.source || '?').slice(0, 1));
      thumb = '<div class="ni-thumb ph">' + initial + '</div>';
    }

    el.innerHTML =
      thumb +
      '<div class="ni-body">' +
        '<div class="ni-title">' + esc(it.title) + '</div>' +
        '<div class="ni-meta">' +
          '<i class="ni-dot ' + key + '"></i>' +
          '<span class="ni-place">' + esc(placeTxt) + '</span>' +
          '<span class="ni-sep">·</span>' +
          '<span>' + esc(it.source) + '</span>' +
          '<span class="ni-sep">·</span>' +
          '<span class="ni-time">' + fmtRel(it.published_at) + '</span>' +
        '</div>' +
      '</div>';

    el.addEventListener('click', function () { focusItem(it.id); });
    return el;
  }

  // ---------------------------------------------------------------- 每日柱状图
  function renderTimeline() {
    var svg = $('tl-svg');
    svg.innerHTML = '';

    var days = 30;
    var counts = {};
    var max = 1;
    var start = new Date(Date.now() - (days - 1) * 86400000);
    start = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate()));
    for (var i = 0; i < days; i++) {
      var k = isoDate(new Date(start.getTime() + i * 86400000));
      counts[k] = 0;
    }
    for (var j = 0; j < state.all.length; j++) {
      var dk = dayKey(state.all[j].published_at);
      if (counts[dk] !== undefined) {
        counts[dk]++;
        if (counts[dk] > max) max = counts[dk];
      }
    }

    var W = 600, H = 54, padB = 12;
    var bw = W / days;
    var inRange = function (k) {
      return (!state.from || k >= state.from) && (!state.to || k <= state.to);
    };

    for (var d = 0; d < days; d++) {
      var key = isoDate(new Date(start.getTime() + d * 86400000));
      var c = counts[key];
      var h = c ? Math.max(2.5, (H - padB) * (c / max)) : 0;
      var x = d * bw + 0.9;
      var w = bw - 1.8;
      var cls = 'tl-bar';
      if (!inRange(key)) cls += ' dim';
      if (state.from === key && state.to === key) cls += ' sel';

      var rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', x.toFixed(2));
      rect.setAttribute('y', (H - padB - h).toFixed(2));
      rect.setAttribute('width', w.toFixed(2));
      rect.setAttribute('height', h.toFixed(2));
      rect.setAttribute('rx', '1.2');
      rect.setAttribute('class', cls);
      rect.addEventListener('click', (function (kk) {
        return function () { setRange(kk, kk); };
      })(key));
      var title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = key + '：' + c + ' 条';
      rect.appendChild(title);
      svg.appendChild(rect);
    }

    var axis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    axis.setAttribute('x1', 0); axis.setAttribute('x2', W);
    axis.setAttribute('y1', H - padB + 0.5); axis.setAttribute('y2', H - padB + 0.5);
    axis.setAttribute('class', 'tl-axis');
    svg.appendChild(axis);

    $('tl-range').textContent = '峰值 ' + max + ' 条/天 · ' + isoDate(start) + ' 起';

    // 标签：首、末、以及范围首尾
    var marks = [[0, isoDate(start)], [days - 1, isoDate(new Date(start.getTime() + (days - 1) * 86400000))]];
    for (var m = 0; m < marks.length; m++) {
      var t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', (marks[m][0] === 0 ? 2 : W - 2));
      t.setAttribute('y', H - 2);
      t.setAttribute('text-anchor', marks[m][0] === 0 ? 'start' : 'end');
      t.setAttribute('class', 'tl-label');
      t.textContent = marks[m][1].slice(5);
      svg.appendChild(t);
    }
  }

  // ---------------------------------------------------------------- 统计
  function renderStats() {
    var countries = {};
    var sources = {};
    for (var i = 0; i < state.visible.length; i++) {
      var it = state.visible[i];
      if (it.location && it.location.cc) countries[it.location.cc] = 1;
      if (it.source) sources[it.source] = 1;
    }
    $('stat-count').textContent = state.visible.length;
    $('stat-countries').textContent = Object.keys(countries).length;
    $('stat-sources').textContent = Object.keys(sources).length;
  }

  // ---------------------------------------------------------------- 交互
  function setActive(id, scroll) {
    state.activeId = id;
    var nodes = document.querySelectorAll('.news-item');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].classList.toggle('active', nodes[i].dataset.id === id);
    }
    if (scroll) {
      var target = document.querySelector('.news-item[data-id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
      if (target && target.scrollIntoView) target.scrollIntoView({ block: 'nearest' });
    }
  }

  function focusItem(id) {
    var it = findItem(id);
    if (!it) return;
    setActive(id, true);
    if (it.lat == null) return;
    // 缩放会重建标记层（clearLayers + 重新添加），所以弹窗必须等重绘之后再开，
    // 否则刚打开的 popup 会随旧 marker 一起被销毁。
    pendingFocus = id;
    focusAttempts = 0;
    map.setView([it.lat, it.lon], Math.max(map.getZoom(), focusZoom(it)), { animate: true });
    setTimeout(openPendingPopup, 520);
  }

  /** 聚焦时的目标缩放：城市级看得细，国家/州级看全境，推断级看区域。 */
  function focusZoom(it) {
    var z = 6;
    if (it.confidence_label === 'high') z = 7;
    else if (it.confidence_label === 'medium') z = 6;
    else if (it.confidence_label === 'custom') z = 7;
    else z = 5;
    return z;
  }

  function openPendingPopup() {
    if (!pendingFocus) return;
    var it = findItem(pendingFocus);
    if (!it || it.lat == null) { pendingFocus = null; return; }

    // 该点可能被聚合遮住。放大一级试试；
    // 若仍被聚合（同一地点叠了太多条），就改用独立图层直接弹出这条的详情。
    var m = markerById[pendingFocus];
    if (m) {
      m.openPopup();
      cardPinned = true;   // 侧栏点进来的卡片是「固定」的，移开鼠标也留着
      pendingFocus = null;
      return;
    }
    if (focusAttempts < 3 && map.getZoom() < 9) {
      focusAttempts++;
      map.setView([it.lat, it.lon], map.getZoom() + 1, { animate: true });
      return;
    }
    openStandalonePopup(it);
    pendingFocus = null;
  }

  /** 在独立图层上放一个临时标记并打开详情——保证任何情况下都能看到这一条。 */
  function openStandalonePopup(it) {
    focusLayer.clearLayers();
    var lat = it.lat + (it._dy || 0), lon = it.lon + (it._dx || 0);
    var key = it.confidence_label || 'low';
    var m = L.circleMarker([lat, lon], {
      radius: 9,
      className: 'news-marker',
      color: '#fff',
      weight: 2.2,
      fillColor: COLOR[key] || COLOR.low,
      fillOpacity: 1,
      interactive: false
    }).addTo(focusLayer);
    m.bindPopup(popupHTML(it), { maxWidth: 340, minWidth: 300, autoPan: false });
    m.openPopup();
    cardPinned = true;
    openItemId = it.id;
  }

  function findItem(id) {
    for (var i = 0; i < state.visible.length; i++) if (state.visible[i].id === id) return state.visible[i];
    for (var j = 0; j < state.custom.length; j++) if (state.custom[j].id === id) return state.custom[j];
    return null;
  }

  function setRange(from, to) {
    state.from = from;
    state.to = to;
    els.from.value = from;
    els.to.value = to;
    var presets = document.querySelectorAll('.preset');
    for (var i = 0; i < presets.length; i++) presets[i].classList.remove('active');
    refresh();
  }

  function setPreset(days) {
    var today = new Date();
    var to = isoDate(new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())));
    if (days === 0) {
      state.from = null; state.to = null;
      els.from.value = ''; els.to.value = '';
    } else {
      var from = isoDate(new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()) - (days - 1) * 86400000));
      state.from = from; state.to = to;
      els.from.value = from; els.to.value = to;
    }
    var presets = document.querySelectorAll('.preset');
    for (var i = 0; i < presets.length; i++) {
      presets[i].classList.toggle('active', +presets[i].dataset.days === days);
    }
    refresh();
  }

  function refresh() {
    applyFilter();
    renderStats();
    renderMarkers();
    renderList();
    renderTimeline();
  }

  // ---------------------------------------------------------------- 添加模式
  function onMapClick(e) {
    if (!state.addMode) return;
    state.pendingCoord = e.latlng;
    $('modal-coord').textContent =
      '坐标：' + e.latlng.lat.toFixed(4) + ', ' + e.latlng.lng.toFixed(4);
    $('f-title').value = '';
    $('f-note').value = '';
    $('f-url').value = '';
    $('modal').hidden = false;
    setTimeout(function () { $('f-title').focus(); }, 30);
  }

  function saveCustomPoint() {
    var title = $('f-title').value.trim();
    if (!title) { $('f-title').focus(); return; }
    var c = state.pendingCoord;
    var rec = {
      id: 'custom-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7),
      title: title,
      summary: $('f-note').value.trim(),
      url: $('f-url').value.trim(),
      source: '我的标注',
      source_id: 'custom',
      published_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
      image: '',
      lat: c.lat, lon: c.lng,
      location: {
        kind: 'custom', name: '自定义位置', zh: '自定义位置',
        lat: c.lat, lon: c.lng, cc: '', country: '自定义', country_zh: '自定义',
        matched_alias: ''
      },
      places: [],
      confidence: 1, confidence_label: 'custom',
      located: true, fallback: false, isCustom: true
    };
    state.custom.push(rec);
    state.all.push(rec);
    saveCustom();
    $('modal').hidden = true;
    setAddMode(false);
    refresh();
    setTimeout(function () { focusItem(rec.id); }, 120);
  }

  function setAddMode(on) {
    state.addMode = on;
    $('add-hint').hidden = !on;
    $('btn-add').classList.toggle('on', on);
    map.getContainer().style.cursor = on ? 'crosshair' : '';
  }

  // ---------------------------------------------------------------- 主题
  function toggleTheme() {
    var root = document.documentElement;
    var light = root.classList.toggle('light');
    try { localStorage.setItem('nwm.theme', light ? 'light' : 'dark'); } catch (e) {}
    if (countryLayer) {
      countryLayer.setStyle({
        color: cssVar('--coast'), fillColor: cssVar('--land')
      });
    }
    renderMarkers();
  }

  // ---------------------------------------------------------------- 状态提示
  function showToast(msg) {
    var el = $('toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () { el.hidden = true; }, 4200);
  }

  /**
   * 定期检查服务端数据是否更新。
   * 后台采集完成后，页面会自动合并新数据并刷新，无需手动重载。
   * file:// 协议下无法 fetch，直接跳过。
   */
  function checkForUpdates() {
    if (location.protocol === 'file:') return;
    fetch('data/news.json?t=' + Date.now())
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        if (!payload || !payload.items) return;
        // 必须用服务端原始时间戳比较。展示用的格式化值（'... UTC'）与原始值
        // （'...Z'）永远不相等，拿它比较会导致每分钟都误判成「数据已更新」，
        // 从而白白重建一次标记层、打断正在查看的弹窗。
        if ((payload.generated_at || '') === state.generatedAtRaw) return;
        state.all = payload.items.concat(state.custom);
        spreadLocations(state.all);
        state.generatedAtRaw = payload.generated_at || '';
        state.generatedAt = state.generatedAtRaw.replace('T', ' ').replace('Z', ' UTC');
        refresh();
        var n = payload.items.length;
        showToast('数据已更新 · 当前 ' + n + ' 条 · ' + (payload.generated_at || '').slice(0, 16).replace('T', ' '));
      })
      .catch(function () { /* 忽略：离线或服务已停 */ });
  }

  function showStatus(msg, isErr) {
    var el = $('status');
    el.hidden = false;
    el.textContent = msg;
    el.className = 'map-overlay overlay-status' + (isErr ? ' err' : '');
    if (!isErr) setTimeout(function () { el.hidden = true; }, 2600);
  }

  // ---------------------------------------------------------------- 初始化
  function init() {
    els.list = $('list');
    els.from = $('date-from');
    els.to = $('date-to');

    try {
      if (localStorage.getItem('nwm.theme') === 'light') document.documentElement.classList.add('light');
    } catch (e) {}

    initMap();

    loadData().then(function (payload) {
      checkContract(payload);
      state.generatedAt = payload.generated_at
        ? payload.generated_at.replace('T', ' ').replace('Z', ' UTC')
        : '';
      state.generatedAtRaw = payload.generated_at || '';
      state.all = (payload.items || []).concat(loadCustom());
      spreadLocations(state.all);
      $('help-sources').textContent = ((payload.sources || [])
        .filter(function (s) { return s.ok; })
        .map(function (s) { return s.id; })
        .join('、')) || '内置 RSS 源';

      // 默认最近 7 天
      setPreset(7);
      els.from.addEventListener('change', function () {
        state.from = els.from.value || null;
        refresh();
      });
      els.to.addEventListener('change', function () {
        state.to = els.to.value || null;
        refresh();
      });

      // 数据为空时提示
      if (!state.all.length) {
        showStatus('暂无数据：仓库不附带新闻数据，请先运行 python3 -m collector.collect 抓取新闻，'
          + '再运行 python3 scripts/publish.py 发布快照', true);
      }
    });

    // 快捷区间
    var presets = document.querySelectorAll('.preset');
    for (var i = 0; i < presets.length; i++) {
      presets[i].addEventListener('click', function () { setPreset(+this.dataset.days); });
    }

    // 搜索
    $('q').addEventListener('input', function () {
      state.query = this.value;
      $('q-clear').hidden = !this.value;
      refresh();
    });
    $('q-clear').addEventListener('click', function () {
      $('q').value = ''; state.query = ''; this.hidden = true; refresh();
    });

    // 排序
    $('sort').addEventListener('change', function () {
      state.sort = this.value; refresh();
    });

    // 标签页
    var tabs = document.querySelectorAll('.tab');
    for (var t = 0; t < tabs.length; t++) {
      tabs[t].addEventListener('click', function () {
        var all = document.querySelectorAll('.tab');
        for (var k = 0; k < all.length; k++) all[k].classList.remove('active');
        this.classList.add('active');
        state.tab = this.dataset.tab;
        renderList();
      });
    }

    // 添加
    $('btn-add').addEventListener('click', function () { setAddMode(!state.addMode); });
    $('add-cancel').addEventListener('click', function () { setAddMode(false); });
    $('f-cancel').addEventListener('click', function () { $('modal').hidden = true; });
    $('f-save').addEventListener('click', saveCustomPoint);
    $('f-title').addEventListener('keydown', function (e) { if (e.key === 'Enter') saveCustomPoint(); });

    // 主题 / 说明
    $('btn-theme').addEventListener('click', toggleTheme);
    $('btn-help').addEventListener('click', function () { $('help').hidden = false; });
    $('help-close').addEventListener('click', function () { $('help').hidden = true; });

    // 全局：弹窗里的「在地图上定位」、聚合列表点击
    document.addEventListener('click', function (e) {
      var loc = e.target.closest && e.target.closest('[data-locate]');
      if (loc) {
        e.preventDefault();
        var it = findItem(loc.getAttribute('data-locate'));
        if (it && it.lat != null) {
          map.setView([it.lat, it.lon], Math.max(map.getZoom(), focusZoom(it)), { animate: true });
        }
        return;
      }
      var row = e.target.closest && e.target.closest('.cl-row');
      if (row) {
        var id = row.getAttribute('data-id');
        map.closePopup();
        focusItem(id);
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        $('modal').hidden = true;
        $('help').hidden = true;
        setAddMode(false);
      }
    });

    window.addEventListener('resize', function () { map.invalidateSize(); });

    // 每分钟检查一次服务端数据，后台采集完成后自动刷新
    setInterval(checkForUpdates, 60000);
    setTimeout(checkForUpdates, 4000);

    // 调试钩子：便于在控制台或自动化测试里检查内部状态
    window.__nwm = {
      state: state,
      map: function () { return map; },
      focusItem: focusItem,
      openPendingPopup: openPendingPopup,
      markerIds: function () { return Object.keys(markerById); },
      checkForUpdates: checkForUpdates
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
