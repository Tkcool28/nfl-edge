import test from 'node:test';
import assert from 'node:assert/strict';

const mod=await import('../presentation-semantics-v1.js');
const {headlineSecondarySemantics,exactSecondarySemantics}=mod;

test('HHR and Balanced preserve the existing worse-price Play Through corridor',()=>{
  const raw={line:null,price_american:-225};
  assert.deepEqual(headlineSecondarySemantics('HHR',-218,raw),{label:'Play Through',price_american:-225,line:null});
  assert.deepEqual(headlineSecondarySemantics('BALANCED',-120,raw),{label:'Play Through',price_american:-225,line:null});
});

test('headline Play Through never turns a better/equal target into an extension',()=>{
  assert.equal(headlineSecondarySemantics('HHR',-218,{line:null,price_american:-187}),null);
  assert.equal(headlineSecondarySemantics('BALANCED',-120,{line:null,price_american:-110}),null);
});

test('Value Through is shown only when the existing corridor boundary itself is strict positive EV',()=>{
  const raw={line:5.5,price_american:-117};
  assert.deepEqual(
    headlineSecondarySemantics('VALUE',-112,raw,{supported:true,ev:0.001}),
    {label:'Value Through',price_american:-117,line:5.5},
  );
  assert.equal(headlineSecondarySemantics('VALUE',-112,raw,{supported:true,ev:0}),null);
  assert.equal(headlineSecondarySemantics('VALUE',-112,raw,{supported:true,ev:-0.001}),null);
});

test('exact-offer BET uses Play Through while exact-offer NO uses Bet At or better',()=>{
  assert.deepEqual(
    exactSecondarySemantics('BET',null,-120,{line:null,price_american:-130}),
    {label:'Play Through',suffix:'',line:null,price_american:-130,inside:true},
  );
  assert.deepEqual(
    exactSecondarySemantics('NO',null,136,{line:null,price_american:163}),
    {label:'Bet At',suffix:' or better',line:null,price_american:163,inside:false},
  );
});
