/* The scene and letter are creative illustrations; evidence photos stay in records. */
(()=>{
  'use strict';
  const D=window.JOURNAL_DATA,U=window.JournalUI,$=s=>document.querySelector(s);
  if(!D||!U)return;
  const {node,button,image,photo,sources,openRecords,recordMedia}=U,byId=new Map(D.records.map(r=>[r.id,r]));
  function enable(view){const tab=$(`button[data-view="${view}"]`);if(tab)tab.hidden=false;}
  function photos(ids,limit=3,seen=new Set()){const wrap=node('div','memory-photos');if(limit<=0)return wrap;for(const id of ids||[]){const r=byId.get(id);if(!r)continue;for(const im of r.images){if(seen.has(im.path))continue;seen.add(im.path);wrap.append(photo({...im,date:r.date,caption:im.caption||r.title},wrap.children.length));if(wrap.children.length>=limit)return wrap;}}return wrap;}
  let setMusic=async()=>false,sceneReady=Promise.resolve(),welcomeShown=false;
  const welcome=$('#welcome'),welcomeKey='journal-welcome:'+D.project_key;
  try{welcomeShown=sessionStorage.getItem(welcomeKey)==='seen';}catch(e){}
  function rememberWelcome(){welcomeShown=true;try{sessionStorage.setItem(welcomeKey,'seen');}catch(e){}}
  function enterSilently(){rememberWelcome();welcome.close();}
  $('#welcome-silent').onclick=enterSilently;$('#welcome-close').onclick=enterSilently;welcome.addEventListener('close',rememberWelcome);
  $('#welcome-music').onclick=()=>{const playing=setMusic(true);enterSilently();return playing;};
  async function openWelcome(){await sceneReady;if(!welcomeShown&&document.body.dataset.view==='scene'&&!welcome.open)welcome.showModal();}
  document.addEventListener('journal:view',e=>{if(e.detail==='scene')openWelcome();});
  if(D.story.scene){
    enable('scene');const S=D.story.scene,host=$('#scene'),windowEl=node('div','scene-window'),stage=node('div','memory-scene');
    const atmosphere=image(S.image_path,'','scene-atmosphere');atmosphere.setAttribute('aria-hidden','true');atmosphere.loading='eager';host.append(atmosphere);
    const world=node('div','scene-world'),background=image(S.image_path,S.alt,'scene-background');background.loading='eager';world.append(background);stage.append(world);windowEl.append(stage);host.append(windowEl);
    const dust=node('div','scene-dust');dust.setAttribute('aria-hidden','true');for(let i=0;i<7;i++){const mote=node('i');mote.style.cssText='left:'+(17+i*11)+'%;top:'+(22+(i*23)%61)+'%;--mote:'+i;dust.append(mote);}world.append(dust);const glow=node('div','scene-cursor-glow');glow.setAttribute('aria-hidden','true');stage.append(glow);
    const defaultGuide='找找熟悉的小物，轻轻点一下。',guide=node('p','scene-guide');guide.setAttribute('aria-live','off');
    function guideText(){
      const full=S.guidance||defaultGuide;guide.textContent=innerWidth<650?(S.mobile_guidance||(full.length<=22?full:defaultGuide)):full;
      guide.style.fontSize='';guide.style.letterSpacing='';
      // Preserve one meaningful line; never insert br, crop words or hide overflow.
      let size=parseFloat(getComputedStyle(guide).fontSize),minimum=innerWidth<650?12.5:16;
      while(guide.scrollWidth>guide.clientWidth+1&&size>minimum){size-=.5;guide.style.fontSize=size+'px';}
      if(guide.scrollWidth>guide.clientWidth+1)guide.style.letterSpacing='0';
      if(guide.scrollWidth>guide.clientWidth+1){guide.textContent=defaultGuide;guide.setAttribute('aria-label',full);}else guide.removeAttribute('aria-label');
    }
    host.append(guide);requestAnimationFrame(guideText);window.addEventListener('resize',()=>requestAnimationFrame(guideText));document.fonts?.ready.then(guideText);
    const list=node('div','scene-directory');let activeSpot,activeBox,effectTimer,positionFrame;
    function closeInsight(restore=false){activeBox?.remove();if(restore&&activeSpot?.isConnected)activeSpot.focus({preventScroll:true});activeBox=null;activeSpot=null;}
    function positionInsight(){
      cancelAnimationFrame(positionFrame);positionFrame=requestAnimationFrame(()=>{
        if(!activeBox?.isConnected||!activeSpot?.isConnected)return;
        const r=activeSpot.getBoundingClientRect(),width=Math.min(292,innerWidth-32),left=Math.max(16,Math.min(innerWidth-width-16,r.left+r.width/2-width/2));
        if(r.left<8||r.right>innerWidth-8){activeBox.hidden=true;return;}activeBox.hidden=false;
        Object.assign(activeBox.style,{width:width+'px',left:left+'px',maxHeight:Math.max(150,innerHeight-105)+'px',overflow:'auto'});
        const height=activeBox.getBoundingClientRect().height,below=r.bottom+18;
        activeBox.style.top=Math.max(76,Math.min(innerHeight-height-18,below+height<innerHeight-18?below:r.top-height-18))+'px';
      });
    }
    function objectFeedback(h){
      clearTimeout(effectTimer);world.querySelector('.scene-object-effect')?.remove();
      const effect=node('div','scene-object-effect');effect.dataset.effect=h.effect||'sparkle';effect.setAttribute('aria-hidden','true');effect.style.left=h.x+'%';effect.style.top=h.y+'%';
      for(let i=0;i<5;i++){const particle=node('i');particle.style.setProperty('--spark',i);effect.append(particle);}world.append(effect);
      effectTimer=setTimeout(()=>effect.remove(),1500);
    }
    function findObject(spot){spot.focus({preventScroll:true});}
    S.hotspots.forEach(h=>{
      const activate=()=>{
        const bounds=spot.getBoundingClientRect();if(bounds.left<8||bounds.right>innerWidth-8)findObject(spot);
        closeInsight();spot.classList.add('is-found');spot.querySelector('.hotspot-dot').textContent='✧';objectFeedback(h);
        const box=node('aside','scene-insight');box.setAttribute('role','region');box.setAttribute('aria-label',h.label);
        box.append(node('span','insight-pin'),button('×',()=>closeInsight(true),'insight-close'),node('p','insight-eyebrow','藏在小物里的日子'),node('h2','',h.label),node('p','insight-copy',h.description));
        const linked=(h.image_paths?.length?h.image_paths:[]),assets=(h.source_ids||[]).flatMap(id=>{const r=byId.get(id);return (r?recordMedia(r):[]).map(im=>({...im,date:r.date,caption:im.caption||r.title,record_id:r.id}));});
        const choices=linked.length?assets.filter(im=>linked.includes(im.path)||linked.includes(im.large)||linked.includes(im.original)):assets;
        if(choices.length){const gallery=node('div','insight-photos');choices.slice(0,2).forEach((asset,i)=>{const frame=photo({...asset,path:asset.original||asset.large||asset.path},i,'insight-photo');frame.dataset.recordId=asset.record_id;frame.querySelectorAll('img').forEach(im=>{im.loading='eager';im.addEventListener('load',positionInsight,{once:true});});gallery.append(frame);});box.append(gallery);}
        box.append(sources(h.source_ids),button('翻到这段记忆',()=>{closeInsight();if(h.target.view==='review')window.JournalMotion.enter(h.target);else U.go(h.target);},'primary'));
        box.querySelector('.insight-close').setAttribute('aria-label','合上这段小记');box.hidden=true;document.body.append(box);activeSpot=spot;activeBox=box;positionInsight();
      };
      const spot=button('',activate,'scene-hotspot');spot.dataset.hotspotId=h.id;spot.dataset.effect=h.effect||'sparkle';spot.style.left=h.x+'%';spot.style.top=h.y+'%';spot.style.setProperty('--spot',S.hotspots.indexOf(h));
      spot.append(node('span','hotspot-dot','✧'),node('span','hotspot-label',h.label));
      const tip=node('span','hotspot-tip',h.description);tip.id='tip-'+h.id;spot.append(tip);spot.setAttribute('aria-describedby',tip.id);spot.setAttribute('aria-label',h.label);world.append(spot);
      list.append(button(h.label,()=>{findObject(spot);activate();}));
    });
    windowEl.addEventListener('scroll',positionInsight,{passive:true});window.addEventListener('resize',positionInsight);
    document.addEventListener('pointerdown',event=>{if(activeBox&&!event.target.closest?.('.scene-insight,.scene-hotspot,.scene-directory'))closeInsight();});
    document.addEventListener('keydown',event=>{if(event.key==='Escape')closeInsight(true);});
    document.addEventListener('journal:view',event=>{if(event.detail!=='scene'){closeInsight();world.querySelector('.scene-object-effect')?.remove();}});
    if(matchMedia('(hover: hover)').matches){let pointerFrame;
      host.addEventListener('pointermove',event=>{if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;cancelAnimationFrame(pointerFrame);pointerFrame=requestAnimationFrame(()=>{
        const rect=stage.getBoundingClientRect(),x=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y=Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height));
        world.style.setProperty('--look-x',((x-.5)*12).toFixed(2)+'px');world.style.setProperty('--look-y',((y-.5)*8).toFixed(2)+'px');
        dust.style.setProperty('--dust-x',((x-.5)*17).toFixed(2)+'px');dust.style.setProperty('--dust-y',((y-.5)*11).toFixed(2)+'px');
        glow.style.setProperty('--glow-x',x*100+'%');glow.style.setProperty('--glow-y',y*100+'%');glow.dataset.active='true';
      });},{passive:true});
      host.addEventListener('pointerleave',()=>{world.style.setProperty('--look-x','0px');world.style.setProperty('--look-y','0px');dust.style.setProperty('--dust-x','0px');dust.style.setProperty('--dust-y','0px');glow.dataset.active='false';});
    }

    const foot=node('div','scene-footer'),directoryToggle=button('找一找',()=>{list.hidden=!list.hidden;directoryToggle.setAttribute('aria-expanded',String(!list.hidden));},'scene-find-toggle');list.hidden=true;directoryToggle.setAttribute('aria-expanded','false');foot.append(button('翻开这本手账 →',()=>window.JournalMotion?.enter(),'primary'),directoryToggle,list);host.append(foot);const panHint=node('span','scene-pan-hint','↔ 左右看看');host.append(panHint);
    const loading=node('div','scene-loading');loading.append(node('span','door-glow'),node('p','','正在推开记忆的门…'));host.append(loading);
    function layout(){
      const w=host.clientWidth,h=host.clientHeight,ratio=background.naturalWidth/background.naturalHeight||1.6;
      // Keep the entire generated composition and all its image-anchored objects in view.
      // Reserve a narrow rim for parallax movement and the cover's controls.
      const narrow=w<650,availableWidth=Math.max(1,w-(narrow?24:36)),availableHeight=Math.max(1,h-(narrow?150:130));
      const planeWidth=Math.min(availableWidth,availableHeight*ratio);
      stage.style.width=planeWidth+'px';stage.style.height=planeWidth/ratio+'px';
      host.dataset.fit='contain';windowEl.scrollLeft=0;panHint.hidden=true;positionInsight();
    }
    new ResizeObserver(layout).observe(host);
    sceneReady=(background.decode?background.decode():new Promise(resolve=>{background.onload=resolve;background.onerror=resolve;})).catch(()=>{}).then(()=>{layout();host.dataset.ready='true';loading.remove();});
    openWelcome();
  }
  if(D.metrics){
    enable('stats');const M=D.metrics,host=$('#stats'),shownPhotos=new Set();host.append(node('p','eyebrow','年历 · 那些留下来的日子'),node('h1','','日子留下的形状'),node('p','lead',D.story.overview.text));
    const totals=node('div','archive-totals');[['收进手账的片段',M.saved_count],['留在相册的照片',new Set(D.records.flatMap(r=>r.images.map(im=>im.path))).size],['留下记录的日子',M.active_days],['一起走过的年份',new Set(D.records.map(r=>r.date.slice(0,4))).size]].forEach(([label,value])=>{const cell=node('div');cell.append(node('strong','',String(value)),node('span','',label));totals.append(cell);});host.append(totals,photos(D.story.overview.source_ids,3,shownPhotos));
    const tags=node('div','tags');(D.story.overview.tags||[]).forEach(t=>tags.append(node('span','',t)));host.append(tags);
    (D.story.findings||[]).forEach(f=>{const section=node('article','annual-review');section.append(node('h2','',f.title),node('p','',f.text),sources(f.source_ids));host.append(section);});
    const chartPaper=node('article','chart-paper');chartPaper.append(node('p','eyebrow','每个月，留下一点声音'),node('h2','','记录的节奏'));
    const monthly=new Map();for(const r of D.records){const month=r.date.slice(0,7);if(!monthly.has(month))monthly.set(month,[]);monthly.get(month).push(r);}
    const keys=[...monthly.keys()].sort(),span=keys.length?((Number(keys.at(-1).slice(0,4))-Number(keys[0].slice(0,4)))*12+Number(keys.at(-1).slice(5))-Number(keys[0].slice(5))+1):0;
    const groups=new Map();for(const month of keys){const group=span>48&&keys.length>18?month.slice(0,4):month;if(!groups.has(group))groups.set(group,[]);groups.get(group).push(...monthly.get(month));}
    const chart=node('div','publication-chart'),maximum=Math.max(1,...[...groups.values()].map(rs=>rs.length));chart.setAttribute('role','group');chart.setAttribute('aria-label','按实际收录范围展开的记录节奏');chart.dataset.buckets=String(groups.size);
    chartPaper.append(node('p','rhythm-range',keys.length?keys[0]+' — '+keys.at(-1)+(span>48&&keys.length>18?' · 按年读这些片段':' · 有记录的月份'):'这一页，等下一段记忆'));
    groups.forEach((rows,period)=>{const cell=button('',()=>openRecords(rows.map(r=>r.id),period+' · '+rows.length+'个片段'),'publication-month');cell.title=period+' · '+rows.length+'个片段';cell.setAttribute('aria-label',cell.title);cell.dataset.period=period;
      const bar=node('span','publication-bar');bar.style.height=Math.max(10,rows.length/maximum*100)+'%';const tip=node('span','rhythm-tip',cell.title),label=node('span','rhythm-label',period.length===4?period:period.slice(2).replace('-','.'));cell.append(bar,tip,label);chart.append(cell);});
    chartPaper.append(chart);host.append(chartPaper);
    const notes=node('details','year-stories'),summary=node('summary','','沿着这些日子，读几段小记');notes.append(summary);
    (D.story.annual_reviews||D.story.themes.map(t=>({year:byId.get(t.source_ids[0]).date.slice(0,4),...t}))).forEach(y=>{const section=node('article','annual-review');section.append(node('p','eyebrow',String(y.year)),node('h2','',y.title),node('p','',y.text));if(y.award)section.append(node('p','award',y.award));const gallery=photos(y.source_ids,Math.min(2,8-shownPhotos.size),shownPhotos);if(gallery.children.length)section.append(gallery);section.append(sources(y.source_ids));notes.append(section);});host.append(notes);
  }
  enable('future');const L=D.story.letter,host=$('#letter-content'),paper=node('article','future-letter');
  if(L){paper.append(node('p','eyebrow','DEAR FUTURE YOU · 留给接下来的日子'),node('h1','',L.title));L.paragraphs.forEach(p=>paper.append(node('p','',p)));paper.append(node('p','letter-closing',L.closing),sources(L.source_ids));if(L.image_path){const keepsake=node('figure','letter-keepsake photo-frame');keepsake.dataset.fastener='tape';const mount=node('div','photo-mount');mount.append(image(L.image_path,L.image_alt||'熟悉的小东西与温柔的灯光','letter-image'));keepsake.append(mount);paper.append(keepsake,node('p','letter-afterword','把熟悉的小东西，留给明天'));};}
  else{paper.append(node('p','eyebrow','接下来'),node('h1','','留给想继续的事'));}
  if(D.story.song){const s=D.story.song,card=node('section','song');card.append(node('h2','',s.name+' · '+s.artist),node('p','',s.reason));if(/^https?:\/\//i.test(s.url||'')){const a=node('a','','听听这首歌');a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';card.append(a);}paper.append(card);}if(L||D.story.song)host.append(paper);else host.hidden=true;
  if(D.story.bgm){
    const B=D.story.bgm,controlHost=$('#music-control'),audio=document.createElement('audio');audio.src=window.JOURNAL_ASSETS?.[B.path]||B.path;audio.preload='metadata';audio.loop=true;audio.volume=.22;controlHost.hidden=false;
    const control=button('',()=>setMusic(audio.paused),'record-player-button');control.setAttribute('aria-label','打开音乐');control.setAttribute('aria-pressed','false');
    const turntable=node('span','turntable');turntable.setAttribute('aria-hidden','true');turntable.append(node('span','turntable-disc'),node('span','tonearm'),node('span','power-light'));control.append(turntable);
    const sleeve=node('span','record-player-copy'),hint=node('span','music-hint',B.title),status=node('span','music-status','轻轻放一首歌');sleeve.append(node('span','record-label','小屋唱片机'),hint,status);control.append(sleeve);controlHost.append(audio,control);$('.site-header').append(controlHost);
    function placePlayer(){if(document.body.dataset.view==='scene')document.body.append(controlHost);else $('.site-header').append(controlHost);}
    document.addEventListener('journal:view',placePlayer);window.addEventListener('resize',placePlayer);placePlayer();
    setMusic=async enabled=>{if(enabled){try{await audio.play();return true;}catch(e){status.textContent='暂时没听到声音';return false;}}audio.pause();return true;};
    audio.onplay=()=>{controlHost.dataset.playing='true';control.setAttribute('aria-label','暂停音乐');control.setAttribute('aria-pressed','true');status.textContent='音乐在轻轻地放';};audio.onpause=()=>{controlHost.dataset.playing='false';control.setAttribute('aria-label','打开音乐');control.setAttribute('aria-pressed','false');status.textContent='轻轻放一首歌';};audio.onerror=()=>status.textContent='暂时没听到声音';
    if(B.attribution){const credits=button('唱片资料',()=>{const info=node('div');info.append(node('p','',B.attribution));if(/^https?:\/\//i.test(B.license_url||'')){const a=node('a','','作品许可');a.href=B.license_url;a.target='_blank';a.rel='noopener';info.append(a);}U.showModal('这张唱片',info);},'record-info');controlHost.append(credits);}
  }else $('#welcome-music').hidden=true;
  document.addEventListener('journal:view',e=>{if(e.detail!=='scene')document.querySelector('.scene-insight')?.remove();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelector('.scene-insight')?.remove();});
  window.JournalExperience={setMusic,sceneReady};
  if(document.body.dataset.view==='scene')openWelcome();
})();
