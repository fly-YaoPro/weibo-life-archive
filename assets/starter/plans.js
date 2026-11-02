/* Editable suggestions. No server, model calls or external task creation. */
(()=>{
  'use strict';
  const D=window.JOURNAL_DATA,U=window.JournalUI,C=window.JournalCore;
  if(!D||!U||!C)return;
  const $=s=>document.querySelector(s),{node,button,sources,showModal,notify,download}=U;
  const prefix=`journal-reading:${D.project_key}`,key=prefix+':plans',backup=prefix+':pre-import';
  let reliable=true;
  function read(k){try{return JSON.parse(localStorage.getItem(k));}catch(e){reliable=false;return null;}}
  function store(k,value){try{localStorage.setItem(k,JSON.stringify(value));return true;}catch(e){reliable=false;notify('未能保存，请下载计划备份。');return false;}}
  const seeds=D.story.plans.map(p=>({...p,done:!!p.done,note:p.note||'',origin:p.origin||'suggestion'}));
  const stored=read(key);
  // An intentionally cleared saved list stays empty; rebuilding must not revive deletions.
  let plans=C.validPlans(stored)?stored:seeds;
  for(let m=1;m<=12;m++){const option=node('option','',m+'月');option.value=m;$('#plan-month').append(option);}
  function render(){
    const list=$('#plan-list'),filter=$('#plan-month').value;$('#plans').hidden=false;list.replaceChildren();
    for(const p of plans.filter(p=>filter==='all'||Number(p.month.slice(-2))===Number(filter)).sort((a,b)=>a.month.localeCompare(b.month))){
      const card=node('article','plan-card');card.dataset.done=!!p.done;card.dataset.planId=p.id;
      card.append(node('span','plan-label',p.origin==='manual'?'自己写的小事':'根据记录整理的建议'),node('p','plan-date',p.month),node('h3','',p.title));
      if(p.reason)card.append(node('p','plan-reason',p.reason));if(p.note)card.append(node('p','',p.note));card.append(sources(p.source_ids));
      const actions=node('div','plan-actions');
      actions.append(button(p.done?'改为未完成':'标记完成',()=>{p.done=!p.done;persist();}),button('编辑',()=>edit(p)),button('删除',()=>{
        const box=node('div');box.append(node('p','',`删除“${p.title}”？将保留删除前备份。`),button('确认删除',()=>{if(!store(backup,plans))return;plans=plans.filter(x=>x.id!==p.id);persist();$('#modal').close();}));showModal('删除计划',box);
      }));card.append(actions);list.append(card);
    }
    if(!list.children.length)list.append(node('p','empty',filter==='all'?'这里暂时没有计划，可以新增或恢复备份。':'这个月还没有计划。'));
    $('#storage-note').textContent=reliable?'修改保存在当前浏览器；换电脑前可下载备份。':'浏览器保存不可用，请及时下载备份。';
  }
  function persist(){store(key,plans);render();}
  function edit(p){
    const form=node('form','plan-form');
    function field(label,tag,type,value){const wrap=node('label','',label),input=node(tag);if(type)input.type=type;input.value=value||'';wrap.append(input);form.append(wrap);return input;}
    const title=field('要做什么','input','text',p?.title),month=field('放在哪个月','input','month',p?.month||`${D.meta.plan_year}-01`),note=field('给自己留句话','textarea',null,p?.note);
    title.required=true;title.maxLength=160;month.required=true;const submit=node('button','primary','保存');submit.type='submit';form.append(submit);
    form.onsubmit=e=>{e.preventDefault();const updated={...(p||{id:'manual-'+Date.now()+'-'+Math.random().toString(36).slice(2,8),done:false,source_ids:[]}),title:title.value.trim(),month:month.value,note:note.value,origin:'manual'};
      if(!updated.title||!C.validPlans([updated]))return;if(p)plans=plans.map(x=>x.id===p.id?updated:x);else plans.push(updated);persist();$('#modal').close();};showModal(p?'编辑计划':'新增计划',form);
  }
  $('#plan-month').onchange=render;$('#add-plan').onclick=()=>edit();
  $('#export-plans').onclick=()=>download('手账计划备份.json',new Blob([JSON.stringify({schema_version:2,project_key:D.project_key,plans},null,2)],{type:'application/json'}));
  $('#import-plans').onchange=async e=>{
    const file=e.target.files[0];if(!file)return;
    try{if(file.size>2000000)throw Error('文件过大');const data=JSON.parse(await file.text()),incoming=Array.isArray(data)?data:data.plans;
      if(!C.validPlans(incoming))throw Error('计划格式不正确');if(data.project_key&&data.project_key!==D.project_key)throw Error('这是另一份手账的备份');
      const box=node('div');box.append(node('p','',`读取到${incoming.length}条。相同ID保留当前手动版本，新ID追加。`),button('确认合并',()=>{if(!store(backup,plans))return;plans=C.mergePlans(plans,incoming);persist();$('#modal').close();}));showModal('合并计划',box);
    }catch(error){notify('未导入：'+error.message);}finally{e.target.value='';}
  };
  $('#restore-plans').onclick=()=>{const old=read(backup);if(!C.validPlans(old)){notify('没有有效备份。');return;}const box=node('div');box.append(node('p','',`恢复备份中的${old.length}条？当前版本也会保留。`),button('确认恢复',()=>{if(!store(backup,plans))return;plans=old;persist();$('#modal').close();}));showModal('恢复计划',box);};
  window.JournalPlans={render,snapshot:()=>plans.map(p=>({...p}))};render();
})();
