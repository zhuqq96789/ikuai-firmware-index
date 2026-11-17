const repo = 'https://github.com/zsz520/ikuai-firmware-index';
const currentCatalog = 'https://raw.githubusercontent.com/zsz520/ikuai-firmware-index/main/data/catalog.json';
const officialPage = 'https://www.ikuai8.com/component/download';
const patch = 'https://patch.ikuai8.com/';
const projects = ['LucienShui/ikuai-firmware', 'LOVECHEN/ikuai-release', 'shiniuniu/ikuai-firmware-public',
  'iKuaiPatch/firmware_archive', 'bikefly/ikuaifw'];
const safePart = /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/;
const pc = /^iKuai8_(x32|x64)_([34]\.\d+\.\d+)_((?:beta_)?(?:Enterprise_)?(?:beta_)?)Buil(?:d)?(\d{11,12})\.(bin|iso)$/i;
const device = /^(IK-[A-Za-z0-9-]+)_sysupgrade_([34]\.\d+\.\d+)_Build(\d{12})\.bin$/;
const editionNames = {free:'x86 免费版', enterprise:'x86 企业版', device:'官方设备'};
const count = new Intl.NumberFormat('zh-CN');
const modelOrder = new Intl.Collator('zh-CN', {numeric:true});

function mirrorUrl(reference, name) {
  if (!Array.isArray(reference) || !Number.isInteger(reference[0]) || !projects[reference[0]] || reference[0] === 0) return null;
  const [project, target, override, hash] = reference;
  if (typeof target !== 'string') return null;
  const sha256 = typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash) ? hash : '';
  const path = override || name;
  if (typeof path !== 'string') return null;
  if (target.startsWith('git:')) {
    const revision = target.slice(4);
    if (project < 3 || !/^[a-f0-9]{40}$/.test(revision) || !path.split('/').every(p => safePart.test(p))) return null;
    return {url:'https://raw.githubusercontent.com/' + projects[project] + '/' + revision + '/' + path, project:projects[project], sha256};
  }
  if (!safePart.test(target) || !safePart.test(path)) return null;
  return {url:'https://github.com/' + projects[project] + '/releases/download/' + target + '/' + path, project:projects[project], sha256};
}

function identity(filename) {
  if (typeof filename !== 'string') return null;
  const p = pc.exec(filename);
  if (p) return {filename, version:p[2], build:p[4], arch:p[1].toLowerCase(), format:p[5].toLowerCase(),
    edition:/enterprise_/i.test(p[3]) ? 'enterprise' : 'free', beta:/beta_/i.test(p[3]), model:''};
  const d = device.exec(filename);
  if (d) return {filename, version:d[2], build:d[3], folder:d[1], model:d[1].split('-').slice(2).join('-'),
    edition:'device', arch:'', format:'bin', beta:false};
  return null;
}

export function compareVersions(a,b) {
  const x = a.split('.').map(Number), y = b.split('.').map(Number);
  return y[0]-x[0] || y[1]-x[1] || y[2]-x[2];
}

export function decodeCatalog(payload) {
  if (payload?.schema !== 2 || !Array.isArray(payload.archive) || !Array.isArray(payload.official)) throw new Error('目录格式不兼容');
  const collected = new Map();
  function add(name) {
    const row = identity(name);
    if (!row) return null;
    const key = name.toLowerCase();
    if (!collected.has(key)) collected.set(key,{...row, official:false, mirrors:new Map()});
    return collected.get(key);
  }
  for (const [name, refs] of payload.archive.concat(payload.archive_extra || [])) {
    const entry = add(name);
    if (!entry || !Array.isArray(refs)) continue;
    for (const ref of refs) {
      const result = mirrorUrl(ref, name);
      if (result && (!entry.mirrors.has(result.url) || result.sha256)) entry.mirrors.set(result.url, result);
    }
  }
  for (const [name, model] of payload.official) {
    const entry = add(name);
    if (entry && model === (entry.model || (entry.edition === 'enterprise' ? 'X86ENT' : 'X86'))) entry.official = true;
  }
  const entries = Array.from(collected.values(), e => ({...e, mirrors:Array.from(e.mirrors.values()).sort((a,b)=>Number(Boolean(b.sha256))-Number(Boolean(a.sha256)))}));
  if (!entries.length) throw new Error('目录为空');
  entries.sort((a,b) => compareVersions(a.version,b.version) || b.build.localeCompare(a.build) ||
    Number(b.official)-Number(a.official) || Number(a.beta)-Number(b.beta) || modelOrder.compare(a.model,b.model) ||
    Number(b.arch === 'x64')-Number(a.arch === 'x64') || (a.format === b.format ? a.filename.localeCompare(b.filename) : a.format === 'bin' ? -1 : 1));
  return {entries, date:/^\d{4}-\d{2}-\d{2}$/.test(payload.date) ? payload.date : '—'};
}

export function linksFor(e) {
  let url = '';
  if (e.edition === 'free') url = patch + '3.x/' + (e.format === 'iso' ? 'iso/' : 'patch/') + e.filename;
  else if (e.edition === 'enterprise' && e.version.startsWith('3.') && e.format === 'bin') url = patch + 'ent/' + e.filename;
  else if (e.edition === 'device' && e.version.startsWith('3.')) url = patch + 'firmware/' + e.folder + '/' + e.filename;
  if (url) return {url, copy:url, label:'下载固件', icon:'down', source:e.official ? '爱快官方' : '爱快历史地址', mirror:e.mirrors[0]};
  if (e.mirrors.length) return {url:e.mirrors[0].url, copy:e.mirrors[0].url, label:'镜像下载', icon:'down', source:'公开镜像 · ' + e.mirrors[0].project};
  return {url:officialPage, copy:e.filename, label:'前往爱快官网', icon:'arrow', source:'该文件没有公开直链，请从爱快官网获取。', gate:true};
}

export function filterEntries(entries,state) {
  const tokens = state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return entries.filter(e => e.edition === state.edition && (!state.major || e.version[0] === state.major) &&
    (!state.model || e.model === state.model) && (!state.arch || e.arch === state.arch) &&
    (!state.format || e.format === state.format) && (!state.version || e.version === state.version) &&
    tokens.every(q => (e.filename+' '+e.build+' '+e.model).toLowerCase().includes(q)));
}

function init() {
  const $ = id => document.getElementById(id);
  const controlIds = ['edition','model','major','arch','format','version','query'];
  const controls = Object.fromEntries(controlIds.map(id => [id,$(id)]));
  let entries = [], selected = '', page = 1, local = false, loading = false;
  const pageSize = 12;
  const icon = (name) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
    const use = document.createElementNS(svg.namespaceURI,'use');
    use.setAttribute('href','#icon-'+name);
    svg.setAttribute('aria-hidden','true');
    svg.append(use);
    return svg;
  };
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function saveUrl() {
    const url = new URL(location.href);
    for (const id of controlIds) {
      const current = controls[id].value;
      if (current && !(id === 'edition' && current === 'free')) url.searchParams.set(id,current);
      else url.searchParams.delete(id);
    }
    history.replaceState(null,'',url);
  }
  const state = () => Object.fromEntries(controlIds.map(id => [id,controls[id].value]));
  function optionList(node, first, values, wanted='') {
    node.replaceChildren(new Option(first,''));
    for (const value of values) node.add(new Option(value,value));
    node.value = values.includes(wanted) ? wanted : '';
  }
  function syncControls(wantedVersion=controls.version.value) {
    const isDevice = controls.edition.value === 'device';
    controls.model.disabled = !isDevice;
    $('model-field').hidden = !isDevice;
    controls.arch.disabled = isDevice;
    $('arch-field').hidden = isDevice;
    if (isDevice) controls.arch.value = '';
    else controls.model.value = '';
    // Devices have no ISO packages; a selected ISO filter should not follow the user into this tab.
    controls.format.options[2].disabled = isDevice;
    if (isDevice && controls.format.value === 'iso') controls.format.value = '';
    const choices = [...new Set(filterEntries(entries,{...state(),version:'',query:''}).map(e=>e.version))];
    optionList(controls.version,'全部版本',choices,wantedVersion);
  }

  async function copy(value, button) {
    const label = button.lastChild;
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
      else {
        const field = el('textarea');
        field.value = value;
        field.style.position = 'fixed';
        field.style.opacity = '0';
        document.body.append(field);
        field.select();
        const ok = document.execCommand('copy');
        field.remove();
        if (!ok) throw new Error('clipboard');
      }
      label.textContent = '已复制';
    } catch {
      label.textContent = '无法复制';
    }
    setTimeout(() => { label.textContent = label.dataset.label; },1800);
  }

  function showSelected(row) {
    const holder = $('selected');
    holder.replaceChildren();
    holder.hidden = !row;
    if (!row) return;
    const link = linksFor(row);
    const about = el('div');
    about.append(el('div','selected-kicker','已选固件'),el('h3','',row.version+' · '+(row.model || editionNames[row.edition])),
      el('p','filename',row.filename),el('p','detail-note',link.source));
    const buttons = el('div','actions');
    const download = el('a','button primary');
    download.href = link.url;
    download.target = '_blank';
    download.rel = 'noopener noreferrer';
    download.append(icon(link.icon),document.createTextNode(link.label));
    const copyLabel = el('span','',link.gate ? '复制文件名' : '复制链接');
    copyLabel.dataset.label = copyLabel.textContent;
    const clip = el('button','button secondary');
    clip.type = 'button';
    clip.append(icon('copy'),copyLabel);
    clip.addEventListener('click',()=>copy(link.copy,clip));
    buttons.append(download,clip);
    holder.append(about,buttons);
    if (link.mirror) {
      const extra = el('a','backup','备用镜像 ↗');
      extra.href = link.mirror.url;
      extra.target = '_blank';
      extra.rel = 'noopener noreferrer';
      holder.append(extra);
    }
  }

  function draw() {
    const filtered = filterEntries(entries,state());
    const pages = Math.max(1,Math.ceil(filtered.length/pageSize));
    page = Math.min(Math.max(1,page),pages);
    const start = (page-1)*pageSize;
    const visible = filtered.slice(start,start+pageSize);
    const choice = visible.find(e=>e.filename===selected) || visible[0];
    selected = choice?.filename || '';
    const head = $('summary');
    head.textContent = '共 '+count.format(filtered.length)+' 个文件'+(local ? ' · 网页快照' : '');
    showSelected(choice);
    const holder = $('items');
    holder.replaceChildren();
    $('pagination').hidden = pages <= 1;
    $('page-number').textContent = page+' / '+pages;
    $('prev').disabled = page <= 1;
    $('next').disabled = page >= pages;
    if (!visible.length) {
      holder.append(el('p','empty','没有匹配的固件，试试更换筛选条件。'));
      return;
    }
    function toggle(row) {
      selected=row.filename;
      showSelected(row);
      for (const btn of holder.querySelectorAll('button.row')) btn.setAttribute('aria-pressed',String(btn.dataset.file===selected));
    }
    for (const row of visible) {
      const button = el('button','row');
      button.type = 'button';
      button.dataset.file = row.filename;
      button.setAttribute('aria-pressed',String(row.filename===selected));
      button.addEventListener('click', () => toggle(row));
      const details = el('span');
      const title = el('span','row-title');
      title.append(el('span','',row.version),el('span','build','Build'+row.build));
      details.append(title,el('span','filename',row.filename));
      const tags = el('span','tags');
      tags.append(el('span','tag',row.format.toUpperCase()),el('span','tag',row.arch || row.model));
      if (row.beta) tags.append(el('span','tag beta','测试版'));
      button.append(details,tags);
      holder.append(button);
    }
  }

  function change(resetSelection=true) {
    if (!entries.length) return;
    syncControls();
    if (resetSelection) page=1;
    saveUrl();
    draw();
  }
  for (const key of controlIds) controls[key].addEventListener(key==='query' ? 'input' : 'change',()=>change());
  $('prev').addEventListener('click',()=>{page--;draw();});
  $('next').addEventListener('click',()=>{page++;draw();});
  $('reset').addEventListener('click',()=>{
    for (const key of controlIds) controls[key].value = key==='edition' ? 'free' : '';
    change();
  });

  async function fetchCatalog(url) {
    const controller = new AbortController();
    const timer = setTimeout(()=>controller.abort(),5500);
    try {
      const response = await fetch(url,{cache:'no-store',signal:controller.signal});
      if (!response.ok) throw new Error('索引暂不可用');
      return decodeCatalog(await response.json());
    } finally {clearTimeout(timer);}
  }

  async function load() {
    if (loading) return;
    loading = true;
    $('summary').textContent = '正在读取索引…';
    $('items').replaceChildren();
    try {
      let data;
      try { data=await fetchCatalog(currentCatalog);local=false; }
      catch { data=await fetchCatalog('./data/catalog.json');local=true; }
      entries=data.entries;
      const models=[...new Set(entries.map(e=>e.model).filter(Boolean))].sort(modelOrder.compare);
      optionList(controls.model,'全部型号',models);
      const q=new URLSearchParams(location.search);
      for (const key of controlIds) {
        const v=q.get(key);
        if (!v || key==='version') continue;
        if (key==='query' || [...controls[key].options].some(o=>o.value===v)) controls[key].value=v;
      }
      $('total').textContent=count.format(entries.length);
      $('models').textContent=count.format(models.length);
      $('date').textContent=data.date;
      syncControls(q.get('version'));
      draw();
    } catch {
      $('summary').textContent='索引暂不可用';
      const panel=el('div','empty','暂时无法读取固件索引。');
      panel.append(el('br'));
      const retry=el('button','button secondary','重新加载');
      retry.type='button';
      retry.addEventListener('click',load);
      panel.append(retry);
      $('items').replaceChildren(panel);
    } finally { loading=false; }
  }
  load();
}

if (typeof document !== 'undefined') init();
