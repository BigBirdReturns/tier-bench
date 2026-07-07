/* SCG public-practice derivative of the AXM-WORLD root glyph.
   Root: 16×16 cream/moss runtime dandelion. Derivative: 16×18 bone/olive practice mark.
   Do not redraw. See SCG_MARK_CONSTITUTION.md.
   Never close the silhouette. Never center it. Never tidy the drift. */
(function (global) {
  const NS = 'http://www.w3.org/2000/svg';
  const COL = { W: '#ECE7D8', o: '#7C7F57' };

  /* 16 wide × 18 tall. W = bone, o = olive, . = void */
  const MAP = [
    '....W.....W.....',
    '................',
    '..W....W.....WW.',
    '.W..WW.WW..W..W.',
    '..WWWWWWWW..W...',
    '.WWWWWWWWWW.....',
    '..WWWWWWWWW.....',
    '..WWWWWWWW......',
    '...WWWWWW.o.....',
    '.....WWW........',
    '......o.......W.',
    '......o.........',
    '...o..o..o......',
    '..o...o..o......',
    '......o.........',
    '.....oo.........',
    '.....oo.........',
    '...oooooo.......',
  ];

  function mark(cell, opts) {
    opts = opts || {};
    const colors = Object.assign({}, COL, opts.colors);
    const w = MAP[0].length, h = MAP.length;
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    svg.setAttribute('width', w * cell);
    svg.setAttribute('height', h * cell);
    svg.setAttribute('shape-rendering', 'crispEdges');
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const c = MAP[y][x];
      if (c === '.') continue;
      const r = document.createElementNS(NS, 'rect');
      r.setAttribute('x', x); r.setAttribute('y', y);
      r.setAttribute('width', 1); r.setAttribute('height', 1);
      r.setAttribute('fill', colors[c]);
      svg.appendChild(r);
    }
    return svg;
  }

  /* construction view: bitmap + visible grid lines */
  function gridView(cell) {
    const w = MAP[0].length, h = MAP.length;
    const svg = mark(cell);
    for (let x = 0; x <= w; x++) {
      const l = document.createElementNS(NS, 'line');
      l.setAttribute('x1', x); l.setAttribute('y1', 0);
      l.setAttribute('x2', x); l.setAttribute('y2', h);
      l.setAttribute('stroke', '#2a2d26'); l.setAttribute('stroke-width', 0.045);
      svg.appendChild(l);
    }
    for (let y = 0; y <= h; y++) {
      const l = document.createElementNS(NS, 'line');
      l.setAttribute('x1', 0); l.setAttribute('y1', y);
      l.setAttribute('x2', w); l.setAttribute('y2', y);
      l.setAttribute('stroke', '#2a2d26'); l.setAttribute('stroke-width', 0.045);
      svg.appendChild(l);
    }
    return svg;
  }

  function mount(idOrEl, cell, opts) {
    const host = typeof idOrEl === 'string' ? document.getElementById(idOrEl) : idOrEl;
    if (!host) return null;
    const svg = (opts && opts.grid) ? gridView(cell) : mark(cell, opts);
    host.appendChild(svg);
    return svg;
  }

  global.SCGPX = { MAP, COL, mark, gridView, mount };
})(window);
