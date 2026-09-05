const button=document.getElementById('install-btn');
let deferredPrompt=null;

const isStandalone=()=>globalThis.matchMedia?.('(display-mode: standalone)')?.matches===true||globalThis.navigator?.standalone===true;

function ensureHelpDialog(){
  let dialog=document.getElementById('install-help-dialog');
  if(dialog)return dialog;
  const ua=navigator.userAgent||'';
  const ios=/iPhone|iPad|iPod/.test(ua);
  const android=/Android/.test(ua);
  const instructions=ios
    ? 'In Safari, tap Share, then Add to Home Screen.'
    : android
      ? 'Open the browser menu (⋮), then choose Install app or Add to Home screen.'
      : 'Open your browser menu and choose Install app or Add to Home screen.';
  dialog=document.createElement('dialog');
  dialog.id='install-help-dialog';
  dialog.className='install-help-dialog';
  dialog.innerHTML=`<section class="install-help-card"><div class="dialog-head"><div><h2>Install NFL EDGE</h2><p>${instructions}</p></div><button class="dialog-close" type="button" aria-label="Close">×</button></div><p class="install-help-note">If the install option is missing, reload this page once and check the browser menu again.</p></section>`;
  document.body.append(dialog);
  dialog.querySelector('.dialog-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close()});
  return dialog;
}

function syncButton(){
  if(!button)return;
  button.hidden=isStandalone();
  if(!button.hidden)button.textContent='Install App';
}

window.addEventListener('beforeinstallprompt',event=>{
  event.preventDefault();
  deferredPrompt=event;
  syncButton();
});

window.addEventListener('appinstalled',()=>{
  deferredPrompt=null;
  if(button)button.hidden=true;
});

document.addEventListener('click',async event=>{
  const target=event.target.closest?.('#install-btn');
  if(!target)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if(isStandalone()){target.hidden=true;return}
  if(deferredPrompt){
    const prompt=deferredPrompt;
    deferredPrompt=null;
    await prompt.prompt();
    const choice=await prompt.userChoice.catch(()=>null);
    if(choice?.outcome==='accepted')target.hidden=true;
    else syncButton();
    return;
  }
  ensureHelpDialog().showModal();
},true);

syncButton();
