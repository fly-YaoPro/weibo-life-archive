/* Offline runtime. No fetch, CDN, remote model, or executable source content. */
(()=>{
  'use strict';
  const D=window.JOURNAL_DATA,C=window.JournalCore,$=s=>document.querySelector(s);
  if(!D||!C){document.body.textContent='手账数据未能加载，请重新打开完整HTML文件。';return;}
  new ResizeObserver(()=>{document.documentElement.style.setProperty('--header-height',document.querySelector('.site-header').offsetHeight+'px');if(window.JournalUI)requestAnimationFrame(refreshReadingLayout);}).observe(document.querySelector('.site-header'));
  const records=D.records,byId=new Map(records.map(r=>[r.id,r])),days=new Map(),photoMode=D.meta.platform==='photos';
  const exactDate=r=>/^\d{4}-\d{2}-\d{2}$/.test(r.date||'')&&(!photoMode||r.date_precision==='day');
  const dateLabel=r=>r.date_label||(r.date?String(r.date):'日期待确认');
  const withDate=records.filter(r=>/^\d{4}(?:-\d{2})?(?:-\d{2})?$/.test(r.date||''));
  records.filter(exactDate).forEach(r=>{if(!days.has(r.date))days.set(r.date,[]);days.get(r.date).push(r);});
  let pages=window.JournalReader.prepare(D),layoutSignature='';
  const key=`journal-reading:${D.project_key}`;
  function read(k,fallback){try{const raw=localStorage.getItem(k);return raw===null?fallback:JSON.parse(raw);}catch(e){return fallback;}}
  function save(k,v){try{localStorage.setItem(k,JSON.stringify(v));}catch(e){/* Reading still works without storage. */}}
  const initial=read(key,{page:0});
  let page=Number.isInteger(initial.page)?Math.min(Math.max(0,initial.page),pages.length-1):0;
  const latestDay=records.filter(exactDate).at(-1),latestDate=withDate.at(-1)?.date||(photoMode?null:D.meta.requested_range?.end||String(new Date().getFullYear()));
  let currentMonth=latestDay?.date.slice(0,7)||(latestDate?(latestDate.length>=7?latestDate.slice(0,7):latestDate.slice(0,4)+'-01'):null);
  let selectedDay=latestDay?.date||null,returnPage=null,activeView=D.story.scene?'scene':'review',searchPage=0;
  let noticeTimer;
  function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!=null){if(['h1','h2','h3'].includes(tag)){el.setAttribute('aria-label',text);C.titleSegments(text).forEach(part=>{const span=document.createElement('span');span.className='title-unit';span.textContent=part;el.append(span);});}else el.textContent=text;}return el;}
  function button(text,fn,cls){const b=node('button',cls,text);b.type='button';b.addEventListener('click',fn);return b;}
  function notify(text){$('#notice').textContent=text;$('#notice').hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('#notice').hidden=true,4000);}
  function link(text,url){const a=node('a','',text);if(/^https?:\/\//i.test(url||'')){a.href=url;a.target='_blank';a.rel='noopener noreferrer';}else a.removeAttribute('href');return a;}
  function image(src,alt,cls){const img=node('img',cls);img.src=window.JOURNAL_ASSETS?.[src]||src;img.alt=alt;img.loading='lazy';img.addEventListener('error',()=>img.replaceWith(node('div','missing-photo',photoMode?'这张照片未能加载，请检查本地素材是否完整':'图片未能加载，原文仍可查看')),{once:true});return img;}
  const modalHistory=[],modalBack=button('← 返回片段',()=>restoreModal(),'modal-back');modalBack.hidden=true;$('#close-modal').before(modalBack);
  function modalDepth(){modalBack.hidden=!modalHistory.length;$('#modal').dataset.depth=String(modalHistory.length);}
  function showModal(title,content){
    const d=$('#modal'),host=$('#modal-content');
    if(d.open)modalHistory.push({title:$('#modal-title').textContent,nodes:[...host.childNodes],scroll:d.scrollTop,contentScroll:host.scrollTop,focus:document.activeElement});
    $('#modal-title').textContent=title;host.replaceChildren(content);d.scrollTop=0;host.scrollTop=0;modalDepth();if(!d.open)d.showModal();
  }
  function restoreModal(){
    const saved=modalHistory.pop();if(!saved)return;$('#modal-title').textContent=saved.title;$('#modal-content').replaceChildren(...saved.nodes);modalDepth();
    requestAnimationFrame(()=>{$('#modal').scrollTop=saved.scroll;$('#modal-content').scrollTop=saved.contentScroll;if(saved.focus?.isConnected)saved.focus.focus({preventScroll:true});});
  }
  $('#close-modal').onclick=()=>$('#modal').close();$('#modal').addEventListener('click',e=>{if(e.target===$('#modal'))$('#modal').close();});
  $('#modal').addEventListener('cancel',event=>{if(modalHistory.length){event.preventDefault();restoreModal();}});
  $('#modal').addEventListener('close',()=>{modalHistory.length=0;modalDepth();});
  function recordMedia(r){return [...(r.images||[]),...(r.video?.covers||[]).map(im=>({...im,media_kind:'video-cover',caption:'视频封面 · '+(im.caption||r.title)}))];}
  function photo(asset,index=0,variant=''){
    if(asset?.media_kind==='video-cover'&&!String(asset.caption||'').startsWith('视频封面'))asset={...asset,caption:'视频封面 · '+(asset.caption||asset.date||'那一天')};
    const f=node('figure','photo photo-frame '+variant);if(asset?.media_kind){f.dataset.mediaKind=asset.media_kind;f.classList.add(asset.media_kind);}f.dataset.fastener=index%2?'clip':'tape';
    const mount=node('div','photo-mount');
    if(asset){const open=button('',()=>showModal(asset.caption||asset.date,photoViewer(asset)), 'photo-open');open.setAttribute('aria-label','放大图片：'+(asset.caption||asset.date));const picture=image(asset.path,asset.caption||'留在这里的照片');function orient(){const ratio=picture.naturalWidth/picture.naturalHeight;f.dataset.orientation=ratio<.87?'portrait':ratio<1.15?'square':'landscape';}picture.addEventListener('load',orient);if(picture.complete&&picture.naturalWidth)orient();open.append(picture);mount.append(open);}
    else mount.append(node('div','missing-photo','把这一页，留给那时写下的字。'));
    f.append(mount);
    if(asset){const caption=node('figcaption');caption.append(node('span','',asset.caption||''),node('time','',asset.date_label||asset.date||''));f.append(caption);}return f;
  }
  function photoViewer(asset){const frame=node('figure','photo-viewer photo-frame');frame.dataset.fastener='clip';const mount=node('div','photo-mount');mount.append(image(asset.large||asset.path,asset.caption||'留在这里的照片','lightbox-image'));frame.append(mount);if(asset.date_label||asset.date)frame.append(node('figcaption','',asset.date_label||asset.date));return frame;}
  function assets(p){if(Array.isArray(p.images)&&p.images.length)return p.images;return (p.source_ids||[]).flatMap(id=>{const r=byId.get(id);return r?r.images.map(im=>({...im,date:r.date,date_label:dateLabel(r),caption:im.caption||r.title,record_id:r.id})):[];}).slice(0,3);}
  function textPhoto(p){const r=byId.get(p.source_ids?.[0]),w=node('div','text-memory');w.append(node('p','eyebrow',r?.date||'原文片段'),node('blockquote','quote',(r?.text||p.text).slice(0,160)),sources(r?[r.id]:p.source_ids));return w;}
  function locateRecord(id){const r=byId.get(id);if(!r)return;returnPage=page;if(exactDate(r)){selectedDay=r.date;currentMonth=r.date.slice(0,7);}else if(r.date){currentMonth=r.date.slice(0,4)+'-'+(r.date.slice(5,7)||'01');selectedDay=null;}$('#search').value='';$('#category').value='all';$('#modal').close();switchView('calendar');renderCalendar(id);const target=exactDate(r)?$('#day-detail'):$('#photo-date-groups');target?.scrollIntoView({block:'nearest'});}
  function openRecords(ids,title='再翻翻那时的日子'){
    const list=node('div','memory-dialog');[...new Set(ids||[])].forEach(id=>{const r=byId.get(id);if(!r)return;const card=recordCard(r,false,true);card.append(button(photoMode?'在相册中定位':'在年历中定位',()=>locateRecord(id),'record-locate'));list.append(card);});
    if(list.children.length)showModal(title,list);
  }
  function sources(ids,compact=false){
    const wrap=node('div','source-chips'),valid=[...new Set(ids||[])].filter(id=>byId.has(id));
    valid.slice(0,compact?1:2).forEach(id=>{const r=byId.get(id);wrap.append(button(compact?dateLabel(r):dateLabel(r)+' · '+r.title.slice(0,6),()=>openRecords([id],dateLabel(r)+' · '+r.title)));});
    if(valid.length>(compact?1:2))wrap.append(button(`翻开这${valid.length}个片段`,()=>openRecords(valid)));return wrap;
  }
  function song(){if(!D.story.song)return null;const s=D.story.song,w=node('div','song'),t=node('div');w.append(node('span','disc'));t.append(link(s.name+' · '+s.artist,s.url),node('p','',s.is_recommendation?'给这段记录推荐一首歌':'来自已核对记录的歌曲'),node('p','reason',s.reason));w.append(t);return w;}
  function timeline(){const w=node('div','timeline');(D.story.milestones||D.story.themes.slice(0,3).map(t=>({title:t.title,text:t.text,source_ids:t.source_ids}))).slice(0,4).forEach(m=>{const r=byId.get((m.source_ids||[])[0]);if(!r)return;const row=node('div','timeline-row');row.append(node('time','',r.date?.slice(0,4)||'日期待确认'));const im=r.images[0];row.append(im?photo({...im,date:r.date,date_label:dateLabel(r),caption:im.caption||r.title},0,'timeline-photo'):node('span','text-marker',r.date?.slice(5,7)||''));const copy=node('div');copy.append(node('h3','',m.title),node('p','',m.text||r.text.slice(0,60)));row.append(copy);w.append(row);});return w;}
  function spine(){const s=node('div','spine');for(let i=0;i<6;i++)s.append(node('i','ring'));s.setAttribute('aria-hidden','true');return s;}
  function addSticker(leaf){const s=node('span','sticker');s.setAttribute('aria-hidden','true');s.innerHTML='<svg viewBox="0 0 40 40" fill="none"><path d="M20 3v6m0 22v6M3 20h6m22 0h6M8 8l5 5m14 14 5 5M8 32l5-5M27 13l5-5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><circle cx="20" cy="20" r="7" stroke="currentColor" stroke-width="2"/></svg>';leaf.append(s);}
  function renderReview(depth=0){
    const host=$('#spread'),p=pages[page];host.replaceChildren(window.JournalReader.render(D,p,{node,photo,sources,button}));
    const copy=host.querySelector('.reader-main-copy'),prose=host.querySelector('.reader-prose');
    // Hidden spreads have no geometry. Measuring them used to split the introduction before entry.
    const visible=activeView==='review'&&!$('#review').hidden&&host.clientHeight>0;
    const overflow=visible&&copy&&copy.scrollHeight>copy.clientHeight+2;
    if(overflow&&depth<12&&p.text.length>8){const parts=window.JournalReader.pieces(p.text,Math.max(8,Math.floor(p.text.length*.55)));if(parts.length>1){pages.splice(page,1,...parts.map((text,i)=>({...p,text,part:p.part+i,id:i?p.id+'-continued-'+i:p.id,images:i?[]:p.images})));renderReview(depth+1);return;}}
    if(overflow&&depth<13&&p.images.length){const gallery={...p,text:'',kind:'gallery',part:p.part+1,id:p.id+'-photos'};p.images=[];pages.splice(page+1,0,gallery);renderReview(depth+1);return;}
    host.dataset.fit=overflow?'overflow':'ready';
    const pager=$('#pager'),prev=button('← 上一页',()=>turn(-1)),next=button('下一页 →',()=>turn(1));prev.disabled=page===0;next.disabled=page===pages.length-1;pager.replaceChildren(prev,button('目录',directory),node('span','page-counter',`${String(page+1).padStart(2,'0')} / ${String(pages.length).padStart(2,'0')}`),next);save(key,{page,chapterId:p.chapterId,part:p.part});
  }
  function turn(delta){if(page+delta<0||page+delta>=pages.length)return;const commit=()=>{page+=delta;renderReview();};if(window.JournalMotion)window.JournalMotion.flip(delta,commit);else commit();}
  function refreshReadingLayout(force=false){if(activeView!=='review'||$('#review').hidden)return;const signature=innerWidth+':'+innerHeight+':'+$('.site-header').offsetHeight;if((signature===layoutSignature&&!force)||window.JournalMotion?.busy)return;layoutSignature=signature;const current=pages[page];pages=window.JournalReader.prepare(D);const found=pages.findIndex(p=>p.chapterId===current?.chapterId&&p.part===current?.part);page=found<0?Math.max(0,pages.findIndex(p=>p.chapterId===current?.chapterId)):found;renderReview();}
  let resizeFrame;window.addEventListener('resize',()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(refreshReadingLayout);});
  function directory(){const d=node('div','directory');pages.forEach((p,i)=>d.append(button(`${String(i+1).padStart(2,'0')} / ${p.title}`,()=>{page=i;renderReview();$('#modal').close();$('#pager').scrollIntoView({block:'start'});})));showModal('目录',d);}
  function switchView(view){if(view==='plans')view='future';if(view==='stats')view='calendar';if(!['review','calendar','scene','future'].includes(view))view='review';activeView=view;for(const id of ['review','calendar','scene','future'])$('#'+id).hidden=id!==view;document.querySelectorAll('button[data-view]').forEach(b=>b.setAttribute('aria-current',b.dataset.view===view?'page':'false'));document.body.dataset.view=view;document.dispatchEvent(new CustomEvent('journal:view',{detail:view}));document.documentElement.style.setProperty('--header-height',$('.site-header').offsetHeight+'px');if(view==='calendar')renderCalendar();if(view==='future')renderPlans();if(view==='review')refreshReadingLayout();window.scrollTo({top:0,behavior:'instant'});if(location.hash!=='#'+view)history.replaceState(null,'','#'+view);}
  document.querySelectorAll('button[data-view]').forEach(b=>b.onclick=()=>switchView(b.dataset.view));$('.brand').onclick=e=>{e.preventDefault();switchView(D.story.scene?'scene':'review');};
  function option(value,label){const o=node('option','',label);o.value=value;return o;}
  const archiveMode='calendar';
  const bounds=D.meta.requested_range||{},years=withDate.length?[...new Set(withDate.map(r=>Number(r.date.slice(0,4))))].sort((a,b)=>a-b):photoMode?[]:[Number((bounds.end||String(new Date().getFullYear())).slice(0,4))],firstYear=years[0],lastYear=years.at(-1);years.forEach(y=>$('#year').append(option(y,y+'年')));
  const photoGroups=photoMode?node('section','photo-date-groups'):null;
  if(photoGroups){photoGroups.id='photo-date-groups';$('.calendar-layout').after(photoGroups);}
  function setYear(y){if(!Number.isFinite(y)||!years.includes(y))return;const available=records.filter(r=>exactDate(r)&&r.date.startsWith(String(y))),last=available.at(-1);currentMonth=last?.date.slice(0,7)||y+'-01';selectedDay=last?.date||null;returnPage=null;renderCalendar();}
  $('#previous-year').onclick=()=>{if(currentMonth)setYear(years[years.indexOf(Number(currentMonth.slice(0,4)))-1]);};$('#next-year').onclick=()=>{if(currentMonth)setYear(years[years.indexOf(Number(currentMonth.slice(0,4)))+1]);};$('#year').onchange=()=>setYear(Number($('#year').value));
  function renderCalendar(target){
    const year=currentMonth?Number(currentMonth.slice(0,4)):null;$('#year').value=year===null?'':String(year);$('#year').disabled=!years.length;
    $('#previous-year').disabled=!years.length||year<=firstYear;$('#next-year').disabled=!years.length||year>=lastYear;
    const yearRecords=withDate.filter(r=>r.date.startsWith(String(year))),annual=D.story.annual_reviews?.find(r=>r.year===year);
    const dailyRecords=yearRecords.filter(exactDate);
    $('#month-note').textContent=annual?annual.title+' · '+annual.text:photoMode?(withDate.length?`${year}年，收好了 ${yearRecords.length} 张照片`:'照片还没有确定的拍摄日期，先按相册回看。'):`${year}年，留下了 ${yearRecords.length} 个片段`;
    const grid=$('#year-grid');grid.replaceChildren();
    const activeMonths=[...new Set(dailyRecords.map(r=>Number(r.date.slice(5,7))))].sort((a,b)=>a-b);
    const months=photoMode?activeMonths:(activeMonths.length<6&&activeMonths.length?activeMonths:Array.from({length:12},(_,i)=>i+1));grid.dataset.months=String(months.length);
    $('.month-toolbar').hidden=photoMode&&!withDate.length;
    $('.calendar-legend').hidden=photoMode&&!dailyRecords.length;
    $('.calendar-legend').textContent=photoMode?'只把已确认到具体日期的照片放进日历；月份、年份和待确认照片另列在下面。':months.length<12?'只展开留下记录的月份。圆点标记片段，点击日期读原文。':'圆点标记已收录的日子，点击日期展开原文。';
    for(const month of months){
      const ym=year+'-'+String(month).padStart(2,'0'),rs=dailyRecords.filter(r=>r.date.startsWith(ym)),card=node('article','year-month'),head=node('div','year-month-head');
      head.append(node('h2','',String(month).padStart(2,'0')),node('span','',rs.length?rs.length+'个片段':'待翻的日子'));card.append(head);
      const weekdays=node('div','mini-weekdays');['一','二','三','四','五','六','日'].forEach(d=>weekdays.append(node('span','',d)));card.append(weekdays);
      const dates=node('div','mini-days');C.monthDays(year,month).forEach(day=>{if(!day){dates.append(node('span'));return;}const found=days.get(day)||[],b=button(String(Number(day.slice(-2))),()=>{selectedDay=day;currentMonth=ym;renderDay(target);document.querySelectorAll('.mini-days button').forEach(el=>el.dataset.selected=el.dataset.date===day);if(found.length)openRecords(found.map(r=>r.id),day+' · '+found.length+'个片段');else $('#day-detail').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});});b.dataset.date=day;b.dataset.populated=!!found.length;b.dataset.selected=day===selectedDay;b.setAttribute('aria-label',day+'，'+found.length+'条已收录');if(found.length){b.title=day+' · '+found.length+'个片段 · '+found[0].title;const tip=node('span','day-tip',found.length+'个片段 · '+found[0].title);tip.setAttribute('aria-hidden','true');b.append(tip);}dates.append(b);});
      while(dates.children.length<42)dates.append(node('span'));card.append(dates);
      const memory=rs.find(r=>recordMedia(r).length);if(memory){const im=recordMedia(memory)[0],frame=photo({...im,date:memory.date,date_label:dateLabel(memory),caption:im.caption||memory.title},month,'month-photo');if(D.skin==='frosted')card.insertBefore(frame,weekdays);else card.append(frame);}else{const note=node('div','month-empty-note');note.append(node('span','pressed-flower','✿'),node('p','month-memory',rs[0]?.title||'留一点空白，等风经过。'));if(D.skin==='frosted')card.insertBefore(note,weekdays);else card.append(note);}
      grid.append(card);
    }
    if(photoMode){
      photoGroups.replaceChildren();const groups=new Map();
      for(const r of records.filter(r=>!exactDate(r)&&(!r.date||r.date.startsWith(String(year))))){const group=r.date||'unknown';if(!groups.has(group))groups.set(group,[]);groups.get(group).push(r);}
      for(const [date,rows] of groups){const section=node('section','photo-date-group');section.dataset.date=date;section.append(node('p','eyebrow',date==='unknown'?'照片还在，日期慢慢补':'保留照片原有的日期精度'),node('h2','',dateLabel(rows[0])));const gallery=node('div','photo-date-gallery');for(const r of rows)gallery.append(recordCard(r,r.id===target));section.append(gallery);photoGroups.append(section);}
      $('#day-detail').hidden=!dailyRecords.length;grid.hidden=!dailyRecords.length;
    }
    renderDay(target);renderSearch();
  }
  function renderDay(target){const detail=$('#day-detail');detail.replaceChildren(node('p','eyebrow',photoMode?'把照片里的这一天展开':'把这一天展开'),node('h2','',selectedDay||'日期待确认'));if(returnPage!==null)detail.append(button('← 返回刚才的主题',()=>{page=returnPage;returnPage=null;switchView('review');renderReview();}));const rs=days.get(selectedDay)||[];if(!rs.length)detail.append(node('p','empty',photoMode?'先从有照片的日期开始翻。':'这一页先留白，想起别的日子，就再翻翻。'));else rs.forEach(r=>detail.append(recordCard(r,r.id===target)));}
  function recordCard(r,highlight=false,full=false){
    const w=node('article','record-card'+(highlight?' target':''));w.dataset.recordId=r.id;w.append(node('time','',dateLabel(r)),node('h3','',r.title));
    if(r.images[0])w.append(photo({...r.images[0],date:r.date,date_label:dateLabel(r),caption:r.images[0].caption||r.title},0,'record-photo'));
    const text=r.text||'';if(text.length>320&&!full){w.append(node('p','',text.slice(0,180)+'…'));const details=node('details'),summary=node('summary','','展开全文');details.append(summary,node('p','',text));w.append(details);}else if(text)w.append(node('p','',text));
    if(r.images.length>1){const details=node('details'),summary=node('summary','',`查看全部 ${r.images.length} 张图片`),row=node('div','compare-pair');r.images.forEach(im=>row.append(photo({...im,date:r.date,date_label:dateLabel(r),caption:im.caption||r.title})));details.append(summary,row);w.append(details);}
    const actions=node('div','record-actions');
    if(r.is_video||r.video){const video=node('section','record-video');video.append(node('p','video-label','▷ 视频片段'));const covers=r.video?.covers||[];if(covers.length){const gallery=node('div','video-covers');covers.forEach((im,i)=>gallery.append(photo({...im,media_kind:'video-cover',date:r.date,caption:'视频封面 · '+(im.caption||r.title)},i,'video-cover')));video.append(gallery);}if(r.video?.path){const player=node('video','record-video-player');player.controls=true;player.preload='metadata';player.src=window.JOURNAL_ASSETS?.[r.video.path]||r.video.path;if(covers[0])player.poster=window.JOURNAL_ASSETS?.[covers[0].path]||covers[0].path;video.append(player);}if(r.video?.source_url||r.url)video.append(link('查看原视频',r.video?.source_url||r.url));w.append(video);}
    if(!photoMode){if(r.screenshot)actions.append(button('查看原帖截图',()=>showModal('那一天的微博',photoViewer({path:r.screenshot.path,caption:'那一天的微博',date:r.date}))));if(r.text_status==='pending')w.append(node('p','muted','更多的话，留在那一天的微博里。'));if(r.expected_image_count>r.images.length)w.append(node('p','muted','有些照片，还留在那一天的微博里。'));if(r.url)actions.append(link('查看平台原文',r.url));if(r.links)r.links.forEach(l=>actions.append(link(l.label||'正文链接',l.href)));}
    if(activeView==='calendar'&&$('#search').value.trim())actions.append(button(photoMode?'在相册中定位':'定位这一天',()=>locateRecord(r.id)));w.append(actions);return w;
  }
  function renderSearch(){const query=$('#search').value.trim(),category=$('#category').value,filtered=!!query||category!=='all',results=$('#search-results');$('.calendar-layout').hidden=filtered||archiveMode==='timeline';$('#archive-timeline').hidden=filtered||archiveMode!=='timeline';if(photoGroups)photoGroups.hidden=filtered;results.hidden=!filtered;if(!filtered)return;const found=C.search(records,query,category),header=node('div','results-header');header.append(node('p','',`全部年份中找到 ${found.length} ${photoMode?'张照片':'条'}`),button('清除搜索',()=>{$('#search').value='';$('#category').value='all';renderSearch();}));results.replaceChildren(header);const g=node('div','search-grid');found.slice(searchPage*12,searchPage*12+12).forEach(r=>g.append(recordCard(r)));results.append(g);if(!found.length)results.append(node('p','empty','还没找到这段记忆，换一个词试试。'));if(found.length>12){const bar=node('div','pager'),prev=button('上一组',()=>{searchPage--;renderSearch();}),next=button('下一组',()=>{searchPage++;renderSearch();});prev.disabled=searchPage===0;next.disabled=(searchPage+1)*12>=found.length;bar.append(prev,node('span','',`${searchPage+1} / ${Math.ceil(found.length/12)}`),next);results.append(bar);}}
  $('#search').oninput=()=>{searchPage=0;renderSearch();};
  const categories=[...new Set(records.map(r=>r.category).filter(Boolean))];if(D.meta.platform==='taobao'&&categories.length>1){$('#category-label').hidden=false;categories.sort().forEach(c=>$('#category').append(option(c,c)));}$('#category').onchange=()=>{searchPage=0;renderSearch();};
  function renderPlans(){const list=$('#plan-list');list.replaceChildren();const wishes=D.story.wishes||D.story.plans||[];$('#plans').hidden=!wishes.length;
    wishes.forEach((p,i)=>{const card=node('article','wish-card');card.append(node('span','wish-number',String(i+1).padStart(2,'0')),node('h3','',p.title));if(p.text||p.reason)card.append(node('p','',p.text||p.reason));card.append(sources(p.source_ids));list.append(card);});
  }
  function download(name,blob){const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
  document.body.dataset.skin=D.skin;document.body.dataset.platform=D.meta.platform;document.title=D.meta.title;$('#brand-title').replaceChildren(...C.titleSegments(D.meta.title).map(part=>node('span','title-unit',part)));
  if(photoMode){$('#search').placeholder='搜照片的描述、地点或日期';$('#calendar .section-heading h2').textContent='翻翻照片里的日子';}
  const requestedPage=Number(new URLSearchParams(location.search).get('page'));if(Number.isInteger(requestedPage)&&requestedPage>0)page=Math.min(requestedPage-1,pages.length-1);
  window.JournalUI={switchView,node,button,image,photo,photoViewer,recordMedia,sources,openRecords,recordCard,showModal,download,notify,refreshReadingLayout,go(target){switchView(target.view);if(target.theme_id){const found=pages.findIndex(p=>p.id===target.theme_id);if(found>=0){page=found;renderReview();}}if(target.date){selectedDay=target.date;currentMonth=target.date.slice(0,7);}if(target.date&&target.view==='calendar')renderCalendar();}};
  renderReview();renderPlans();switchView(location.hash.slice(1)||(D.story.scene?'scene':'review'));
})();
