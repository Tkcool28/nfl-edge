import {ApiClient,ApiError} from './api.js';
import {buildExactWagerPayload,esc,line,money,odds,pct,playThroughPresentation,units} from './ui-core.js';

const api=new ApiClient({baseUrl:globalThis.NFL_EDGE_API_BASE||''});
const $=id=>document.getElementById(id);
let current=null;

function style(){
  if(document.getElementById('manual-guidance-style'))return;
  const node=document.createElement('style');
  node.id='manual-guidance-style';
  node.textContent=`
  .manual-guidance-card{margin-top:14px;padding:15px;border:1px solid var(--line);border-radius:14px;background:var(--surface-2);color:var(--ink)}
  .manual-guidance-top{display:flex;align-items:center;justify-content:space-between;gap:10px}.manual-price-chip{display:inline-flex;padding:5px 8px;border:1px solid var(--line);border-radius:999px;font-size:.68rem;font-weight:900;letter-spacing:.05em}.manual-price-chip.value,.manual-price-chip.playable{border-color:var(--cmp-price);color:var(--cmp-price)}.manual-price-chip.outside{color:var(--ink-3)}
  .manual-offer-title{margin:11px 0 4px;font-size:1.08rem}.manual-recommendation{margin:12px 0;padding:12px;border:1px solid var(--line);border-radius:11px;background:var(--surface)}.manual-recommendation strong{display:block;font-size:.92rem;line-height:1.35}.manual-recommendation span{display:block;margin-top:5px;color:var(--ink-2);font-size:.8rem;line-height:1.45}.manual-recommendation.low{border-left:4px solid var(--cmp-worse)}
  .manual-essentials{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:10px}.manual-essential{padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:var(--surface)}.manual-essential span{display:block;color:var(--ink-3);font-size:.67rem}.manual-essential strong{display:block;margin-top:2px;font-size:.96rem}.manual-essential.reliability-low strong{color:var(--cmp-worse)}
  .manual-guidance-card details{margin-top:10px}.manual-guidance-card details summary{cursor:pointer;color:var(--ink-2);font-size:.76rem;font-weight:800}.manual-detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;font-size:.72rem;color:var(--ink-2)}
  .manual-log-note{margin:10px 0 0;color:var(--ink-3);font-size:.74rem;line-height:1.4}.manual-guidance-card>.btn-primary,.manual-guidance-card>.btn-secondary{width:100%;margin-top:10px}
  .manual-log-dialog{max-width:min(430px,calc(100vw - 24px));width:100%;border:0;padding:0;background:transparent;color:var(--ink)}.manual-log-card{padding:16px;border:1px solid var(--line);border-radius:14px;background:var(--surface);color:var(--ink)}.manual-log-card input{width:100%;min-width:0;box-sizing:border-box}.manual-log-card .manual-row{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
  .install-help-dialog{max-width:min(420px,calc(100vw - 24px));width:100%;border:0;padding:0;background:transparent;color:var(--ink)}.install-help-card{padding:16px;border:1px solid var(--line);border-radius:14px;background:var(--surface);color:var(--ink)}.install-help-card p{color:var(--ink-2);line-height:1.5}.install-help-note{font-size:.78rem}
  [data-theme="extreme"] .manual-guidance-card,[data-theme="extreme"] .manual-recommendation,[data-theme="extreme"] .manual-essential,[data-theme="extreme"] .manual-log-card,[data-theme="extreme"] .install-help-card{background:#000;color:var(--ink);box-shadow:none}
  @media(max-width:340px){.manual-essentials{grid-template-columns:1fr}.manual-log-card .manual-row{grid-template-columns:1fr}}
  `;
  document.head.append(node);
}

function safeMessage(error){
  if(error instanceof ApiError){
    if(error.status===401)return 'Sign in again to continue.';
    if(error.status===409)return 'This wager conflicts with a saved wager. Refresh Bets and review it first.';
    if(error.status===422)return 'This exact offer cannot be evaluated.';
    if(error.status===0)return 'App unavailable. Check your connection.';
  }
  return 'Request could not be completed.';
}

function offerFromForm(){
  const market=$('offer-market').value;
  const rawLine=$('offer-line').value.trim();
  const price=Number($('offer-price').value);
  const offer={game_id:$('offer-game').value,market_type:market,selection:$('offer-selection').value,book:'MANUAL',line:market==='MONEYLINE'?null:Number(rawLine),price};
  if(!Number.isFinite(price)||(market!=='MONEYLINE'&&(!rawLine||!Number.isFinite(offer.line))))return null;
  return offer;
}

function priceState(v,pt){
  if(!v.supported)return {key:'unsupported',label:'UNSUPPORTED'};
  if(v.ev!=null&&Number(v.ev)>0)return {key:'value',label:'VALUE PRICE'};
  if(pt?.inside===true)return {key:'playable',label:'PLAYABLE PRICE'};
  return {key:'outside',label:'OUTSIDE RANGE'};
}

function recommendationCopy(v,offer,pt,price){
  const zero=Number(v.recommended_units||0)<=0;
  const clears=pt?.inside===true;
  const lowReliability=v.supported&&zero&&(price.key==='value'||price.key==='playable');
  if(v.verdict==='BET'&&!zero){
    return {low:false,title:`Recommended stake ${units(v.recommended_units)}`,body:'This offer meets the model price and reliability requirements for a recommended wager.',reliability:'MEETS THRESHOLD'};
  }
  if(lowReliability){
    const threshold=pt?.price_american==null?'the Play Through price':`Play Through ${odds(pt.price_american)}`;
    const body=clears
      ? `Your ${odds(offer.price)} price clears ${threshold}, but NFL EDGE does not have enough confidence in this model state to recommend.`
      : `This price qualifies on value, but NFL EDGE does not have enough confidence in this model state to recommend.`;
    return {low:true,title:'No recommended stake because model reliability is LOW.',body,reliability:'LOW'};
  }
  if(!v.supported)return {low:false,title:'No recommendation',body:(v.warnings||[])[0]||'Required model or market evidence is unavailable.',reliability:'—'};
  if(pt&&pt.inside===false)return {low:false,title:'No recommended stake at this price.',body:`Your ${odds(offer.price)} price is outside Play Through ${odds(pt.price_american)}.`,reliability:'—'};
  return {low:false,title:'No recommended stake.',body:'This offer does not meet the current requirements for a wager recommendation.',reliability:'—'};
}

function render(result,offer){
  const host=$('exact-result');
  const v=result.evaluation;
  const pt=playThroughPresentation(offer.line,offer.price,v.play_through);
  const price=priceState(v,pt);
  const rec=recommendationCopy(v,offer,pt,price);
  const recommendedDollars=v.verdict==='BET'&&result.recommended_dollars!=null?` · ${money(result.recommended_dollars)}`:'';
  const logNote=Number(v.recommended_units||0)>0
    ? 'Log the wager you actually made.'
    : 'You can log this wager for tracking, but NFL EDGE is not recommending a stake.';
  const action=v.supported
    ? result.user
      ? '<button class="btn-primary" type="button" data-manual-log>Log Wager</button>'
      : '<button class="btn-secondary" type="button" data-manual-signin>Sign in to log wager</button>'
    : '';
  host.innerHTML=`<section class="manual-guidance-card"><div class="manual-guidance-top"><span class="manual-price-chip ${price.key}">${price.label}</span><span class="offer-source">Manual offer</span></div><h3 class="manual-offer-title">${esc(offer.selection)} ${line(offer.line)} · ${odds(offer.price)}</h3><section class="manual-recommendation ${rec.low?'low':''}"><strong>${rec.title}</strong><span>${rec.body}</span></section><div class="manual-essentials"><div class="manual-essential"><span>Model probability</span><strong>${pct(v.probability)}</strong></div><div class="manual-essential"><span>Expected value</span><strong>${v.ev==null?'—':`${(Number(v.ev)*100).toFixed(2)}%`}</strong></div><div class="manual-essential"><span>Play Through</span><strong>${pt?odds(pt.price_american):'—'}</strong></div><div class="manual-essential ${rec.low?'reliability-low':''}"><span>Reliability</span><strong>${rec.reliability}</strong></div><div class="manual-essential"><span>Recommended stake</span><strong>${units(v.recommended_units)}${recommendedDollars}</strong></div></div><details><summary>Model details</summary><div class="manual-detail-grid"><span>Trust probability</span><strong>${pct(v.trust_probability)}</strong><span>Break-even probability</span><strong>${pct(v.break_even_probability)}</strong><span>Evaluator result</span><strong>${esc(v.verdict)}</strong></div></details><p class="manual-log-note">${logNote}</p>${action}<p class="evaluation-disclaimer">Model evaluation only. NFL EDGE does not place sportsbook wagers.</p></section>`;
  host.querySelector('[data-manual-log]')?.addEventListener('click',()=>openLog(result,offer));
  host.querySelector('[data-manual-signin]')?.addEventListener('click',()=>document.querySelector('[data-nav="account"]')?.click());
}

function ensureLogDialog(){
  let dialog=document.getElementById('manual-log-dialog');
  if(dialog)return dialog;
  dialog=document.createElement('dialog');
  dialog.id='manual-log-dialog';
  dialog.className='manual-log-dialog';
  dialog.innerHTML=`<form class="manual-log-card" data-manual-log-form><div class="dialog-head"><div><h2>Log manual wager</h2><p data-manual-log-copy></p></div><button class="dialog-close" type="button" data-manual-log-close aria-label="Close">×</button></div><div class="manual-row"><div class="manual-field"><label for="manual-log-units">Actual units</label><input id="manual-log-units" type="number" min="0" step="0.25"></div><div class="manual-field"><label for="manual-log-dollars">Actual dollars</label><input id="manual-log-dollars" type="number" min="0" step="0.01"></div></div><div class="manual-field"><label for="manual-log-note">Note</label><input id="manual-log-note" maxlength="2000"></div><div class="form-error" data-manual-log-error role="alert"></div><div class="manual-actions"><button class="btn-secondary" type="button" data-manual-log-cancel>Cancel</button><button class="btn-primary" type="submit">Save wager</button></div></form>`;
  document.body.append(dialog);
  dialog.querySelector('[data-manual-log-close]').addEventListener('click',()=>dialog.close());
  dialog.querySelector('[data-manual-log-cancel]').addEventListener('click',()=>dialog.close());
  dialog.querySelector('[data-manual-log-form]').addEventListener('submit',saveLog);
  return dialog;
}

function openLog(result,offer){
  current={result,offer};
  const dialog=ensureLogDialog();
  const recommended=Number(result.evaluation.recommended_units||0);
  dialog.querySelector('[data-manual-log-copy]').textContent=recommended>0
    ? `${offer.selection} ${line(offer.line)} · ${odds(offer.price)} · NFL EDGE recommendation ${units(recommended)}`
    : `${offer.selection} ${line(offer.line)} · ${odds(offer.price)} · NFL EDGE recommended stake 0.00u`;
  $('manual-log-units').value=recommended>0?recommended:'';
  $('manual-log-dollars').value=recommended>0&&result.recommended_dollars!=null?result.recommended_dollars:'';
  $('manual-log-note').value='';
  dialog.querySelector('[data-manual-log-error]').textContent='';
  dialog.showModal();
}

async function saveLog(event){
  event.preventDefault();
  if(!current)return;
  const {result,offer}=current;
  const rawUnits=$('manual-log-units').value;
  const rawDollars=$('manual-log-dollars').value;
  const body=buildExactWagerPayload({
    productVersion:result.product_version,
    offer,
    actualUnits:rawUnits===''?null:Number(rawUnits),
    actualDollars:rawDollars===''?null:rawDollars,
    note:$('manual-log-note').value,
    idempotencyKey:`manual-${globalThis.crypto?.randomUUID?.()||Date.now()}`.slice(0,128),
  });
  try{
    const created=await api.createWager(body);
    ensureLogDialog().close();
    current=null;
    const card=$('exact-result')?.querySelector('.manual-guidance-card');
    card?.querySelector('[data-manual-log]')?.remove();
    const note=card?.querySelector('.manual-log-note');
    if(note)note.textContent=`Wager Logged${created?.wager?.actual_dollars!=null?` · ${money(created.wager.actual_dollars)}`:''} · ${created?.wager?.status||'OPEN'}`;
  }catch(error){
    ensureLogDialog().querySelector('[data-manual-log-error]').textContent=safeMessage(error);
  }
}

async function evaluate(event){
  event.preventDefault();
  event.stopImmediatePropagation();
  const offer=offerFromForm();
  const error=$('exact-error');
  if(!offer){error.textContent='Enter a valid offer.';return}
  error.textContent='';
  $('exact-result').innerHTML='<div class="loading-card">Checking this offer…</div>';
  try{
    const result=await api.evaluateOffer(offer);
    current={result,offer};
    render(result,offer);
  }catch(err){
    $('exact-result').innerHTML='';
    error.textContent=safeMessage(err);
  }
}

style();
$('exact-form')?.addEventListener('submit',evaluate,true);
