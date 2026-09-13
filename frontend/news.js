import {ApiClient,ApiError} from './api.js';

const api=new ApiClient({baseUrl:globalThis.NFL_EDGE_API_BASE||''});
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const newsState={latest:null,error:null,loading:false};
const $=id=>document.getElementById(id);

function style(){
  if(document.getElementById('news-v1-style'))return;
  const node=document.createElement('style');
  node.id='news-v1-style';
  node.textContent=`
  .board-quick-links{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;margin:0 0 10px}
  .board-quick-link{position:relative;min-height:76px;padding:11px 12px;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface);color:var(--ink);text-align:left;box-shadow:var(--shadow);overflow:hidden}
  .board-quick-link strong{display:block;font-size:.9rem;line-height:1.15}.board-quick-link span{display:block;margin-top:4px;color:var(--ink-3);font-size:.69rem;line-height:1.3}
  .board-quick-link .quick-icon{display:block;margin:0 0 5px;font-size:1.05rem;line-height:1}.board-quick-link .quick-badge{position:absolute;right:8px;top:8px;margin:0;padding:3px 6px;border-radius:999px;background:var(--action-soft);color:var(--action-bet);font-size:.58rem;font-weight:900;letter-spacing:.05em}
  .board-quick-link.news-link{border-color:color-mix(in srgb,var(--edge-blue) 40%,var(--line));background:linear-gradient(135deg,color-mix(in srgb,var(--edge-blue) 8%,var(--surface)),var(--surface))}
  .board-quick-link:focus-visible{outline:3px solid color-mix(in srgb,var(--edge-blue) 35%,transparent);outline-offset:2px}
  .news-view{padding-bottom:32px}.news-shell{display:grid;gap:12px}.news-back{justify-self:start}.news-hero{padding:14px 2px 5px}.news-hero-kicker{margin:0 0 4px;color:var(--edge-blue);font-size:.68rem;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.news-hero h1{margin:0;font-size:1.5rem;line-height:1.1}.news-dek{margin:7px 0 0;color:var(--ink-2);font-size:.88rem;line-height:1.45}.news-meta{margin:7px 0 0;color:var(--ink-3);font-size:.7rem}
  .news-section{padding:13px;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface);box-shadow:var(--shadow)}.news-section-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}.news-section-icon{font-size:1.05rem}.news-section h2{margin:0;font-size:1.03rem}.news-item+.news-item{margin-top:14px;padding-top:13px;border-top:1px solid var(--line)}.news-item h3{margin:0 0 6px;font-size:.98rem;line-height:1.3}.news-item p{margin:6px 0;color:var(--ink-2);font-size:.84rem;line-height:1.52}.news-item ul{margin:7px 0;padding-left:20px;color:var(--ink-2);font-size:.82rem;line-height:1.48}.news-takeaway{margin-top:9px!important;padding:9px 10px;border-left:4px solid var(--edge-blue);border-radius:8px;background:var(--surface-2);color:var(--ink)!important;font-weight:720}.news-sources{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}.news-source{display:inline-flex;align-items:center;min-height:30px;padding:5px 8px;border:1px solid var(--line);border-radius:999px;color:var(--edge-blue);font-size:.68rem;font-weight:800;text-decoration:none;background:var(--surface-2)}
  .news-empty{padding:22px 16px;border:1px dashed var(--line);border-radius:var(--r-lg);background:var(--surface);text-align:center}.news-empty strong,.news-empty span{display:block}.news-empty span{margin-top:5px;color:var(--ink-3);font-size:.8rem}
  [data-theme="extreme"] .board-quick-link,[data-theme="extreme"] .news-section,[data-theme="extreme"] .news-empty{background:#000;box-shadow:none}
  @media(max-width:350px){.board-quick-links{gap:6px}.board-quick-link{padding:10px;min-height:72px}.board-quick-link strong{font-size:.84rem}.board-quick-link span{font-size:.64rem}}
  `;
  document.head.append(node);
}

function readableTime(value){
  if(!value)return'';
  const date=new Date(value);
  if(Number.isNaN(date.getTime()))return'';
  return date.toLocaleString([], {weekday:'short',hour:'numeric',minute:'2-digit'});
}

function safeUrl(value){
  const url=String(value||'');
  return /^https?:\/\//i.test(url)?url:'';
}

function sourceMarkup(sources){
  if(!Array.isArray(sources)||!sources.length)return'';
  const links=sources.map(source=>{
    const url=safeUrl(source?.url);
    if(!url)return'';
    return `<a class="news-source" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source?.label||source?.publisher||'Source')} ↗</a>`;
  }).filter(Boolean).join('');
  return links?`<div class="news-sources" aria-label="Sources">${links}</div>`:'';
}

function itemMarkup(item){
  const paragraphs=Array.isArray(item?.paragraphs)?item.paragraphs:(item?.body?[item.body]:[]);
  const bullets=Array.isArray(item?.bullets)&&item.bullets.length?`<ul>${item.bullets.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'';
  return `<article class="news-item">${item?.headline?`<h3>${esc(item.headline)}</h3>`:''}${paragraphs.map(p=>`<p>${esc(p)}</p>`).join('')}${bullets}${item?.takeaway?`<p class="news-takeaway">${esc(item.takeaway)}</p>`:''}${sourceMarkup(item?.sources)}</article>`;
}

function renderNews(){
  const host=$('news-content');
  if(!host)return;
  if(newsState.loading&&!newsState.latest){host.innerHTML='<div class="loading-card">Loading the latest NFL EDGE brief…</div>';return}
  if(!newsState.latest){
    host.innerHTML=`<section class="news-empty"><strong>Daily News is not available yet.</strong><span>${esc(newsState.error||'The betting board is still available normally.')}</span></section>`;
    return;
  }
  const news=newsState.latest;
  const sections=Array.isArray(news.sections)?news.sections:[];
  host.innerHTML=`<div class="news-shell"><button class="text-btn news-back" type="button" data-news-back>← Board</button><header class="news-hero"><p class="news-hero-kicker">${esc(news.edition||'NFL EDGE Daily News')}</p><h1>${esc(news.title||'NFL EDGE Daily News')}</h1>${news.dek?`<p class="news-dek">${esc(news.dek)}</p>`:''}<p class="news-meta">Updated ${esc(readableTime(news.published_at_utc)||news.published_at_utc||'recently')}</p></header>${sections.map(section=>`<section class="news-section" data-news-section="${esc(section?.id||'')}"><div class="news-section-head">${section?.icon?`<span class="news-section-icon" aria-hidden="true">${esc(section.icon)}</span>`:''}<h2>${esc(section?.title||'Update')}</h2></div>${(Array.isArray(section?.items)?section.items:[]).map(itemMarkup).join('')}</section>`).join('')}</div>`;
  host.querySelector('[data-news-back]')?.addEventListener('click',closeNews);
}

function tileStatus(){
  if(newsState.latest)return `Updated ${readableTime(newsState.latest.published_at_utc)||'today'}`;
  if(newsState.loading)return'Checking latest brief…';
  return newsState.error?'Brief temporarily unavailable':'Daily football & market brief';
}

function makeQuickLinks(){
  const userStrip=$('user-strip');
  if(!userStrip)return;
  $('education-entry')?.remove();
  let row=$('board-quick-links');
  if(!row){
    row=document.createElement('section');
    row.id='board-quick-links';
    row.className='board-quick-links';
    row.setAttribute('aria-label','News and help');
    userStrip.before(row);
  }
  row.innerHTML=`<button id="news-entry" class="board-quick-link news-link" type="button"><span class="quick-icon" aria-hidden="true">📰</span><strong>Daily News</strong><span id="news-entry-status">${esc(tileStatus())}</span>${newsState.latest?'<span class="quick-badge">LATEST</span>':''}</button><button class="board-quick-link learn-link" type="button" data-education-open="quick-start"><span class="quick-icon" aria-hidden="true">🎓</span><strong>Learn NFL EDGE</strong><span>Tutorial, glossary & betting basics</span></button>`;
  $('news-entry')?.addEventListener('click',openNews);
}

function newsView(){
  let view=$('view-news');
  if(view)return view;
  view=document.createElement('main');
  view.id='view-news';
  view.className='view news-view';
  view.hidden=true;
  view.innerHTML='<section id="news-content"><div class="loading-card">Loading the latest NFL EDGE brief…</div></section>';
  $('main-content')?.append(view);
  return view;
}

function openNews(){
  const view=newsView();
  document.querySelectorAll('.view').forEach(node=>node.hidden=true);
  view.hidden=false;
  document.querySelectorAll('[data-nav]').forEach(button=>button.classList.remove('is-active'));
  $('back-btn').hidden=false;
  renderNews();
  loadNews(true);
  window.scrollTo({top:0,behavior:'auto'});
}

function closeNews(){
  const view=$('view-news');
  if(view)view.hidden=true;
  const board=$('view-board');
  if(board)board.hidden=false;
  document.querySelectorAll('[data-nav]').forEach(button=>button.classList.toggle('is-active',button.dataset.nav==='board'));
  $('back-btn').hidden=true;
  window.scrollTo({top:0,behavior:'auto'});
}

async function loadNews(renderAfter=false){
  if(newsState.loading)return;
  newsState.loading=true;
  makeQuickLinks();
  try{
    newsState.latest=await api.newsLatest();
    newsState.error=null;
  }catch(error){
    newsState.latest=null;
    if(error instanceof ApiError&&error.status===404)newsState.error='Today’s brief has not been published yet.';
    else newsState.error='News could not be loaded. The betting board is unaffected.';
  }finally{
    newsState.loading=false;
    makeQuickLinks();
    if(renderAfter&& !$('view-news')?.hidden)renderNews();
  }
}

style();
newsView();
makeQuickLinks();
loadNews(false);

$('refresh-btn')?.addEventListener('click',()=>loadNews(false));

$('back-btn')?.addEventListener('click',event=>{
  if($('view-news')?.hidden!==false)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  closeNews();
},true);

document.querySelector('.tabbar')?.addEventListener('click',()=>{
  const view=$('view-news');
  if(view?.hidden===false)view.hidden=true;
},true);
