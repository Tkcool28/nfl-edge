import {ApiClient} from './api.js';
import {odds,pct,playThroughPresentation} from './ui-core.js';

const api=new ApiClient({baseUrl:globalThis.NFL_EDGE_API_BASE||''});

export function headlineSecondarySemantics(lane,currentPrice,playThrough,boundaryEvaluation=null){
  if(!playThrough||playThrough.price_american==null||!Number.isFinite(Number(currentPrice)))return null;
  const boundary=Number(playThrough.price_american),current=Number(currentPrice);
  if(boundary>=current)return null;
  const normalized=String(lane||'').toUpperCase();
  if(normalized==='VALUE'){
    if(!boundaryEvaluation||boundaryEvaluation.supported!==true||Number(boundaryEvaluation.ev)<=0)return null;
    return {label:'Value Through',price_american:boundary,line:playThrough.line??null};
  }
  if(normalized==='HIT_RATE'||normalized==='HHR'||normalized==='BALANCED'){
    return {label:'Play Through',price_american:boundary,line:playThrough.line??null};
  }
  return null;
}

export function exactSecondarySemantics(verdict,currentLine,currentPrice,playThrough){
  const pt=playThroughPresentation(currentLine,currentPrice,playThrough);
  if(!pt)return null;
  const v=String(verdict||'').toUpperCase();
  if(v==='BET'&&pt.inside===true)return {label:'Play Through',suffix:'',...pt};
  if(v==='NO'&&pt.inside===false&&Number(pt.price_american)>Number(currentPrice))return {label:'Bet At',suffix:' or better',...pt};
  return null;
}

function headlineRequest(h,price=null){
  if(!h?.game_id||!h?.market||!h?.selection||!h?.book||h.american_odds==null)return null;
  return {
    game_id:String(h.game_id),
    market_type:String(h.market),
    selection:String(h.selection),
    book:String(h.book),
    line:h.line==null?null:Number(h.line),
    price:Number(price??h.american_odds),
  };
}

const evaluationCache=new Map();
async function evaluate(request){
  const key=JSON.stringify(request);
  if(!evaluationCache.has(key))evaluationCache.set(key,api.evaluateOffer(request).catch(error=>{evaluationCache.delete(key);throw error}));
  return evaluationCache.get(key);
}

function setLabel(container,from,to){
  container?.querySelectorAll?.('.k,.evaluation-stat span,.manual-essential span,.manual-detail-grid span').forEach(node=>{
    if(node.textContent.trim().toLowerCase()===from.toLowerCase())node.textContent=to;
  });
}

function ensureHeadlineEvaluatorRows(card,evaluation){
  const body=card.querySelector('.hcard-math-body');
  if(!body)return;
  setLabel(body,'model probability','Selector probability');
  setLabel(body,'trust probability','Selector trust');
  setLabel(body,'market probability','Pinnacle anchor');
  setLabel(body,'EV','Evaluator EV');
  if(body.querySelector('[data-evaluator-win-probability]'))return;
  const winLabel=document.createElement('span');winLabel.className='k';winLabel.dataset.evaluatorWinProbability='1';winLabel.textContent='Evaluator win probability';
  const winValue=document.createElement('span');winValue.className='v';winValue.textContent=pct(evaluation.probability);
  const beLabel=document.createElement('span');beLabel.className='k';beLabel.textContent='Break-even probability';
  const beValue=document.createElement('span');beValue.className='v';beValue.textContent=pct(evaluation.break_even_probability);
  body.append(winLabel,winValue,beLabel,beValue);
}

function removePrimarySecondary(card){
  card.querySelectorAll('.hcard-secondary:not(.value-at)').forEach(node=>node.remove());
}

function renderHeadlineSecondary(card,semantics,currentLine,currentPrice){
  removePrimarySecondary(card);
  if(!semantics)return;
  const pt=playThroughPresentation(currentLine,currentPrice,semantics);
  if(!pt||pt.inside!==true)return;
  const node=document.createElement('div');
  node.className='hcard-secondary';
  node.innerHTML=`<span class="verb">${semantics.label}</span> ${semantics.line==null?'':`${Number(semantics.line)>0?'+':''}${Number(semantics.line)} `}${odds(semantics.price_american)} · current offer inside range`;
  const details=card.querySelector('.hcard-math');
  if(details)card.insertBefore(node,details);else card.append(node);
}

async function decorateHeadlines(){
  const root=document.getElementById('headlines');
  if(!root||!root.querySelector('.hcard'))return;
  let payload;
  try{payload=await api.productLatest()}catch{return}
  const product=payload?.product||payload;
  const mapping={HHR:'hit_rate',BALANCED:'balanced',VALUE:'value'};
  for(const card of root.querySelectorAll('.hcard[data-lane]')){
    const laneName=String(card.dataset.lane||'').toUpperCase();
    const key=mapping[laneName];
    const h=product?.headlines?.[key];
    if(!h||String(h.state)!=='BET')continue;
    const revision=`${product.generated_at_utc||''}|${laneName}|${h.game_id}|${h.line}|${h.american_odds}`;
    if(card.dataset.presentationSemanticsRevision===revision)continue;
    const request=headlineRequest(h);
    if(!request)continue;
    try{
      const current=(await evaluate(request))?.evaluation;
      if(!current)continue;
      ensureHeadlineEvaluatorRows(card,current);
      let boundaryEvaluation=null;
      const raw=current.play_through;
      if(laneName==='VALUE'&&raw?.price_american!=null&&Number(raw.price_american)<Number(h.american_odds)){
        const boundaryRequest=headlineRequest(h,raw.price_american);
        if(boundaryRequest)boundaryEvaluation=(await evaluate(boundaryRequest))?.evaluation||null;
      }
      const semantics=headlineSecondarySemantics(laneName,h.american_odds,raw,boundaryEvaluation);
      renderHeadlineSecondary(card,semantics,h.line,h.american_odds);
      card.dataset.presentationSemanticsRevision=revision;
    }catch{}
  }
}

function decorateExactEvaluations(){
  document.querySelectorAll('.offer-evaluation').forEach(card=>{
    if(card.dataset.presentationSemanticsV1==='1')return;
    setLabel(card,'Model probability','Evaluator win probability');
    setLabel(card,'Trust probability','Staking probability');
    setLabel(card,'Expected value','Evaluator EV');
    const verdict=card.querySelector('.state-chip')?.textContent?.trim()?.toUpperCase();
    const secondary=card.querySelector('.hcard-secondary:not(.value-at)');
    if(secondary){
      const verb=secondary.querySelector('.verb');
      if(verdict==='NO'&&verb){
        verb.textContent='Bet At';
        if(!secondary.dataset.betAtSuffix){secondary.append(document.createTextNode(' or better'));secondary.dataset.betAtSuffix='1';}
      }else if(verdict==='BET'&&verb){verb.textContent='Play Through';}
    }
    card.dataset.presentationSemanticsV1='1';
  });
}

function decorateManualEvaluations(){
  document.querySelectorAll('.manual-guidance-card').forEach(card=>{
    if(card.dataset.presentationSemanticsV1==='1')return;
    setLabel(card,'Model probability','Evaluator win probability');
    setLabel(card,'Trust probability','Staking probability');
    setLabel(card,'Expected value','Evaluator EV');
    const spans=[...card.querySelectorAll('.manual-detail-grid span')];
    const idx=spans.findIndex(x=>x.textContent.trim()==='Evaluator result');
    const verdict=idx>=0?spans[idx].nextElementSibling?.textContent?.trim()?.toUpperCase():null;
    const essentials=[...card.querySelectorAll('.manual-essential')];
    const threshold=essentials.find(x=>x.querySelector('span')?.textContent?.trim()==='Play Through');
    if(threshold&&verdict==='NO')threshold.querySelector('span').textContent='Bet At or better';
    card.dataset.presentationSemanticsV1='1';
  });
}

let scheduled=false;
function schedule(){
  if(scheduled)return;scheduled=true;
  queueMicrotask(async()=>{scheduled=false;decorateExactEvaluations();decorateManualEvaluations();await decorateHeadlines();});
}

export function startPresentationSemantics(){
  schedule();
  new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true});
  document.getElementById('refresh-btn')?.addEventListener('click',()=>{evaluationCache.clear();setTimeout(schedule,250)});
}

if(typeof document!=='undefined')startPresentationSemantics();
