/* Offline DOM/canvas doubles verify control flow, not visual/browser rendering. */
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'../assets/starter');

function runtime(records,metaOverrides={}){
  const all=[],bySelector=new Map();
  class Element{
    constructor(tag='div',cls=''){this.tagName=tag.toUpperCase();this.className=cls;this.children=[];this.dataset={};this.style={setProperty(){}};this.attributes={};this.events={};this.hidden=false;this.open=false;this.value='';this.textContent='';this.offsetHeight=80;this.clientHeight=0;this.scrollHeight=0;this.isConnected=true;this.classList={add:(...xs)=>xs.forEach(x=>{if(!this.className.split(' ').includes(x))this.className+=' '+x;}),remove:()=>{},toggle:()=>false};all.push(this);}
    append(...xs){for(const x of xs){if(x==null)continue;this.children.push(x);if(typeof x==='object')x.parentElement=this;}}
    prepend(...xs){for(const x of xs.reverse()){this.children.unshift(x);if(typeof x==='object')x.parentElement=this;}}
    replaceChildren(...xs){this.children=[];this.append(...xs);}
    setAttribute(k,v){this.attributes[k]=String(v);}
    removeAttribute(k){delete this.attributes[k];}
    addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
    click(){if(this.onclick)this.onclick();for(const fn of this.events.click||[])fn({target:this,preventDefault(){}});}
    after(x){this.parentElement?.append(x);}
    before(x){this.parentElement?.append(x);}
    insertBefore(x,before){const i=this.children.indexOf(before);this.children.splice(i<0?0:i,0,x);x.parentElement=this;}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    querySelectorAll(selector){const descendants=[];function walk(n){for(const x of n.children||[]){if(typeof x!=='object')continue;descendants.push(x);walk(x);}}walk(this);return descendants.filter(x=>matches(x,selector));}
    showModal(){this.open=true;}
    close(){this.open=false;for(const fn of this.events.close||[])fn();}
    scrollIntoView(){}
    focus(){}
    get childNodes(){return this.children;}
  }
  function matches(el,selector){if(selector.startsWith('#'))return el.id===selector.slice(1);if(selector.startsWith('.'))return el.className.split(' ').includes(selector.slice(1));if(selector==='button[data-view]')return el.tagName==='BUTTON'&&el.dataset.view;return el.tagName===selector.toUpperCase();}
  const document={createElement:tag=>new Element(tag),querySelector(selector){return bySelector.get(selector)||all.find(x=>matches(x,selector))||null;},querySelectorAll(selector){if(selector==='button[data-view]')return all.filter(x=>matches(x,selector));if(selector==='.mini-days button')return all.filter(x=>x.dataset.date);return all.filter(x=>matches(x,selector));},addEventListener(){},dispatchEvent(){},fonts:{ready:Promise.resolve()}};
  document.body=new Element('body');
  document.documentElement=new Element('html');
  const selectors=['.site-header','#close-modal','#modal','#modal-title','#modal-content','#spread','#review','#pager','#search','#category','#calendar','#scene','#future','.brand','#year','#previous-year','#next-year','#month-note','#year-grid','.calendar-legend','.month-toolbar','#day-detail','.calendar-layout','#archive-timeline','#search-results','#category-label','#plan-list','#plans','#brand-title','#calendar .section-heading h2','#notice','#share-button'];
  for(const selector of selectors){const el=new Element(selector.includes('button')?'button':'div',selector.startsWith('.')?selector.slice(1):'');if(selector.startsWith('#')&&!selector.includes(' '))el.id=selector.slice(1);bySelector.set(selector,el);document.body.append(el);}
  for(const view of ['review','calendar','future']){const el=new Element('button');el.dataset.view=view;document.body.append(el);}
  bySelector.get('#category').value='all';
  const D={meta:{platform:'photos',title:'合成相册',target:{collection_id:'fixture',collection_name:'合成相册'},requested_range:{start:'2016-01-01',end:'2026-11-09'},...metaOverrides},skin:'paper',project_key:'fixture',records,story:{overview:{headline:'合成照片',text:'测试。',source_ids:records.map(r=>r.id)},themes:[{id:'t1',title:'相册',text:'合成测试。',source_ids:records.map(r=>r.id)}],wishes:[{id:'w1',title:'再拍一张',text:'只验证流程。',source_ids:[records[0].id]}],share:{letter_text:'合成测试。',entries:records.map(r=>({source_id:r.id,title:r.title,text:'合成图片说明。'}))}}};
  const window={JOURNAL_DATA:D,addEventListener(){},scrollTo(){}};
  const context={window,document,ResizeObserver:class{observe(){}},innerWidth:1200,innerHeight:850,localStorage:{getItem(){return null;},setItem(){}},location:{hash:'#review',search:''},history:{replaceState(){}},URLSearchParams,CustomEvent:class{},requestAnimationFrame:fn=>{fn();return 1;},cancelAnimationFrame(){},setTimeout,clearTimeout,matchMedia:()=>({matches:false}),console};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,'core.js'),'utf8'),context);
  window.JournalReader={prepare:()=>[{...D.story.overview,id:'overview',title:D.story.overview.headline,chapterId:'overview',text:'测试。',part:0,images:[]}],render:()=>new Element('article'),pieces:t=>[t]};
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),context);
  return {D,window,document,context,Element,all};
}

function row(id,date,precision){return {id,date,date_precision:precision,date_label:date===null?'日期待确认':precision==='year'?date+'年':precision==='month'?date.slice(0,4)+'年'+Number(date.slice(5,7))+'月':date,title:id,text:'合成说明 '+id,images:[{path:'images/'+id+'.png',large:'images/'+id+'.png',origin:'synthetic_fixture',caption:'合成照片'}],url:null};}

test('photo archive puts only exact dates on calendar and keeps month/year/unknown groups',()=>{
  const rows=[row('year','2022','year'),row('month','2024-03','month'),row('day','2024-05-03','day'),row('unknown',null,'unknown')],R=runtime(rows);
  R.window.JournalUI.switchView('calendar');
  assert.equal(R.document.querySelector('#year').value,'2024');
  assert.equal(R.all.filter(el=>el.dataset.populated===true).length,1);
  const groups=R.document.querySelector('#photo-date-groups');
  assert.ok(groups);assert.deepEqual(groups.children.map(x=>x.dataset.date),['2024-03','unknown']);
  R.document.querySelector('#year').value='2022';R.document.querySelector('#year').onchange();
  assert.deepEqual(groups.children.map(x=>x.dataset.date),['2022','unknown']);
  assert.equal(R.document.querySelector('#year-grid').children.length,0);
  // Unknown is never turned into Jan 1 and is still directly accessible.
  assert.ok(R.window.JournalUI.recordCard(rows[3]).children.some(el=>el.textContent==='日期待确认'));
  assert.equal(R.D.records[3].date,null);
});

test('all unknown photos boot and search/locate without fake current-day calendar',()=>{
  const R=runtime([row('unknown',null,'unknown')]);R.window.JournalUI.switchView('calendar');
  assert.equal(R.document.querySelector('#year-grid').children.length,0);
  assert.equal(R.document.querySelector('#day-detail').hidden,true);
  const card=R.window.JournalUI.recordCard(R.D.records[0],false,true);
  assert.ok(card.children.some(el=>el.className.includes('photo')));
  R.document.querySelector('#search').value='unknown';R.document.querySelector('#search').oninput();
  assert.equal(R.document.querySelector('#search-results').hidden,false);
  R.window.JournalUI.openRecords(['unknown']);assert.equal(R.document.querySelector('#modal').open,true);
  const locate=R.all.find(el=>el.tagName==='BUTTON'&&el.textContent==='在相册中定位');assert.ok(locate);locate.click();
  assert.equal(R.document.querySelector('#modal').open,false);assert.equal(R.D.records[0].date,null);
});

test('unknown photo time scope never exposes internal guard bounds or invents the current year',()=>{
  const R=runtime([row('unknown',null,'unknown')],{requested_range:{start:'0001-01-01',end:'9999-12-31'},time_scope:{status:'unknown',range_mode:'unrestricted',observed_range:null,internal_bounds_only:true}});
  R.window.JournalUI.switchView('calendar');
  const year=R.document.querySelector('#year');assert.equal(year.children.length,0);assert.equal(year.value,'');assert.equal(year.disabled,true);
  assert.equal(R.document.querySelector('#previous-year').disabled,true);assert.equal(R.document.querySelector('#next-year').disabled,true);
  assert.equal(R.document.querySelector('#year-grid').children.length,0);
  const displayed=R.all.flatMap(el=>[el.textContent,el.value]).join(' ');
  for(const invalid of ['0001','9999',String(new Date().getFullYear())])assert.equal(displayed.includes(invalid),false);
  R.document.querySelector('#previous-year').onclick();R.document.querySelector('#next-year').onclick();year.onchange();
  R.document.querySelector('#search').value='unknown';R.document.querySelector('#search').oninput();assert.equal(R.document.querySelector('#search-results').hidden,false);
  R.window.JournalUI.openRecords(['unknown']);const locate=R.all.find(el=>el.tagName==='BUTTON'&&el.textContent==='在相册中定位');locate.click();
  assert.equal(R.document.querySelector('#photo-date-groups').children[0].dataset.date,'unknown');
  assert.equal(year.children.length,0);assert.equal(year.value,'');assert.equal(R.D.records[0].date,null);
});

test('mobile photo cover keeps a real photo on page one while Weibo pagination stays unchanged',()=>{
  const R=runtime([row('first',null,'unknown'),row('second','2023-05','month')]);
  R.context.innerWidth=390;R.context.innerHeight=844;R.D.story.themes=[];
  R.D.story.overview.images=R.D.records.map(r=>({...r.images[0],date:r.date,date_label:r.date_label,record_id:r.id}));
  vm.runInContext(fs.readFileSync(path.join(root,'reader.js'),'utf8'),R.context);
  const pages=R.window.JournalReader.prepare(R.D);
  assert.equal(pages[0].images.length,1);assert.equal(pages[0].images[0].record_id,'first');
  assert.equal(pages.flatMap(p=>p.images).length,2);
  const book=R.window.JournalReader.render(R.D,pages[0],R.window.JournalUI);
  assert.ok(book.className.includes('photo-cover'));assert.ok(book.querySelector('.reader-visual').querySelector('img'));
  const weibo=JSON.parse(JSON.stringify(R.D));weibo.meta.platform='weibo';
  assert.equal(R.window.JournalReader.prepare(weibo)[0].images.length,0);
});

test('photo share uses real photos without profile/avatar or a generated scene and supports one wish',async()=>{
  const R=runtime([row('month','2024-03','month'),row('unknown',null,'unknown')]),drawn=[];
  class FakeImage{constructor(){this.width=300;this.height=200;}set src(value){this._src=value;queueMicrotask(()=>this.onload());}}
  const ctx={font:'',measureText:s=>({width:String(s).length*15}),beginPath(){},roundRect(){},arc(){},fill(){},stroke(){},save(){},restore(){},translate(){},scale(){},rotate(){},moveTo(){},quadraticCurveTo(){},lineTo(){},ellipse(){},fillRect(){},strokeRect(){},setLineDash(){},fillText(){},drawImage(im){drawn.push(im._src);}};
  const create=R.document.createElement;R.document.createElement=tag=>{if(tag!=='canvas')return create(tag);return {getContext:()=>ctx,toBlob:fn=>fn({type:'image/png'})};};
  R.context.Image=FakeImage;R.context.URL={createObjectURL:()=>'',revokeObjectURL(){}};R.window.JOURNAL_ASSETS=Object.fromEntries(R.D.records.map(r=>[r.images[0].path,'data:image/png;base64,synthesis']));
  vm.runInContext(fs.readFileSync(path.join(root,'share.js'),'utf8'),R.context);
  const result=await R.window.JournalShare.renderPoster();
  assert.ok(result.imageSources.some(im=>im.record_id==='unknown'));
  assert.equal(result.entries.find(e=>e.source_id==='unknown').date,null);
  assert.ok(result.sections.some(section=>section.kind==='photo_cover'));
  assert.equal(result.sections.some(section=>section.kind==='profile'),false);
  assert.ok(drawn.length>=2);assert.ok(result.blobs.length);
});
