/* Offline 1080px keepsake: profile, review, room, real posts, letter, three small things. */
(()=>{
  'use strict';const D=window.JOURNAL_DATA,U=window.JournalUI,C=window.JournalCore;if(!D||!U||!C)return;
  const {node,button,showModal,download,recordMedia}=U,byId=new Map(D.records.map(r=>[r.id,r])),glass=D.skin==='frosted';
  const P=glass?{ink:'#2d3c2c',muted:'#68785f',accent:'#718342',paper:'#eaf0e4',panel:'#ffffffbd',alt:'#f1f4dc'}:{ink:'#514132',muted:'#8d755c',accent:'#be5045',paper:'#fbf5e8',panel:'#fffbf2',alt:'#eef1df'};
  const face=(size,bold=false)=>`${bold?'600':'400'} ${size}px ${glass?'system-ui, sans-serif':'"Noto Serif CJK SC", "Songti SC", serif'}`;
  const rows=(ctx,text,width)=>String(text||'').split('\n').flatMap(p=>p?C.balancedLines(p,width,t=>ctx.measureText(t).width):['']);
  async function loadImage(path){
    if(!path)return null;
    const src = window.JOURNAL_ASSETS?.[path] || path;
    let objectURL = null;
    try {
      // 已经是 data URI 或 blob URI 时直接使用，不会污染 canvas
      if (src.startsWith('data:') || src.startsWith('blob:')) {
        return await new Promise((resolve,reject)=>{
          const im=new Image();
          im.onload=()=>resolve(im);
          im.onerror=()=>reject(new Error('配图未能读取，请重新打开完整手账'));
          im.src=src;
        });
      }
      // 普通 URL / 本地文件：先 fetch 再转 blob，避免 tainted canvas
      const response = await fetch(src);
      if (!response.ok) throw new Error('配图读取失败');
      const blob = await response.blob();
      objectURL = URL.createObjectURL(blob);
      const im = await new Promise((resolve,reject)=>{
        const image=new Image();
        image.onload=()=>resolve(image);
        image.onerror=()=>reject(new Error('配图未能读取，请重新打开完整手账'));
        image.src=objectURL;
      });
      // 保留 object URL 以便后续清理
      im._objectURL = objectURL;
      return im;
    } catch (e) {
      if (objectURL) URL.revokeObjectURL(objectURL);
      throw e;
    }
  }
  function selectEntries(){
    if(D.story.share?.entries?.length)return D.story.share.entries.map(e=>({...e,record:byId.get(e.source_id)}));
    const source=D.story.milestones?.length?D.story.milestones:D.story.themes,items=[...source];
    for(const theme of D.story.themes)if(!items.some(n=>theme.source_ids.some(id=>n.source_ids.includes(id))))items.push(theme);
    return items.map(n=>{const records=n.source_ids.map(id=>byId.get(id)).filter(Boolean).sort((a,b)=>a.date.localeCompare(b.date));
      const record=records.find(r=>recordMedia(r).length)||records[0];return {title:n.title,text:n.text,source_id:record.id,record};});
  }
  async function renderPoster(options={includeProfile:false,includePhotos:false}){
    const loadedImages = [];
    async function trackedLoad(path){
      const im = await loadImage(path);
      if (im) loadedImages.push(im);
      return im;
    }
    try {
      await document.fonts.ready;const profile=options.includeProfile?D.meta.profile:null,wishes=(window.JournalPlans?.snapshot()||D.story.plans||[]).slice(0,6),letter=D.story.share?.letter_text||D.story.letter?.closing;

    const entries=selectEntries().sort((a,b)=>a.record.date.localeCompare(b.record.date));if(entries.length>24)throw new Error('重点片段过多，请先整理为清晰的阶段');
    const avatar=profile?.avatar_path?await trackedLoad(profile.avatar_path):null,scene=D.story.scene?.image_path?await trackedLoad(D.story.scene.image_path):null;
    const scratch=document.createElement('canvas').getContext('2d'),ops=[],breaks=[0],sections=[],imageSources=[];let y=72;
    function op(fn){ops.push(fn);}
    function panel(x,top,w,h,fill=P.panel){op(c=>{c.fillStyle=fill;c.beginPath();c.roundRect(x,top,w,h,glass?30:8);c.fill();c.strokeStyle=glass?'#ffffffbd':'#d9c4a081';c.lineWidth=1.5;c.stroke();if(!glass){c.strokeStyle='#d4bd972e';c.strokeRect(x+9,top+9,w-18,h-18);}});}
    function text(value,x,top,size=48,width=920,color=P.ink,bold=false,leading=size*1.62){scratch.font=face(size,bold);const lines=rows(scratch,value,width);
      op(c=>{c.fillStyle=color;c.font=face(size,bold);c.textBaseline='top';lines.forEach((line,i)=>c.fillText(line,x,top+i*leading));});return lines.length*leading;}
    function flourish(x,top,scale=1){op(c=>{c.save();c.translate(x,top);c.scale(scale,scale);c.strokeStyle=glass?'#9bac76':'#b29765';c.lineWidth=2;c.beginPath();c.moveTo(-33,8);c.quadraticCurveTo(-8,-6,31,7);c.stroke();for(const [dx,dy,angle] of [[-19,0,-.5],[-4,-2,-.1],[12,1,.5]]){c.save();c.translate(dx,dy);c.rotate(angle);c.fillStyle=glass?'#adbe883d':'#b39f6740';c.beginPath();c.ellipse(0,-7,5,11,0,0,Math.PI*2);c.fill();c.restore();}c.restore();});}
    function section(kind,title){sections.push({kind,top:y});text(title,80,y,54,920,P.accent,true,82);flourish(944,y+35,.9);y+=104;}
    function photo(im,x,top,w,h,caption=''){op(c=>{c.save();c.shadowColor=glass?'#49604224':'#7b5b3423';c.shadowBlur=18;c.shadowOffsetY=7;c.fillStyle=glass?'#ffffffea':'#fffdf6';c.beginPath();c.roundRect(x-13,top-13,w+26,h+67,glass?20:2);c.fill();c.restore();
      c.strokeStyle=glass?'#ffffffdb':'#dfceaf';c.lineWidth=1.5;c.strokeRect(x-5,top-5,w+10,h+10);
      const scale=Math.min(w/im.width,h/im.height);c.drawImage(im,x+(w-im.width*scale)/2,top+(h-im.height*scale)/2,im.width*scale,im.height*scale);
      c.save();if(glass){c.strokeStyle='#8fa385';c.lineWidth=3;c.beginPath();c.roundRect(x+w-26,top-24,14,38,7);c.stroke();}else{c.translate(x+w*.47,top-14);c.rotate(-.08);c.fillStyle='#d4bd789e';c.fillRect(-40,-9,80,23);c.strokeStyle='#af955d4d';c.lineWidth=1;for(let i=-35;i<40;i+=8){c.beginPath();c.moveTo(i,-9);c.lineTo(i,14);c.stroke();}}c.restore();
      if(caption){c.fillStyle=P.muted;c.font=face(28);c.textBaseline='top';c.fillText(caption,x+8,top+h+15);}});}
    // A single layout is shared by preview, download and clipboard. No new images are generated here.
    op(c=>{if(glass){const g=c.createLinearGradient(0,0,1080,height);g.addColorStop(0,'#deebd0');g.addColorStop(.5,'#edf0e8');g.addColorStop(1,'#f3dfcc');c.fillStyle=g;}else c.fillStyle=P.paper;c.fillRect(0,0,1080,height);
      c.strokeStyle=glass?'#ffffff7d':'#cbb58f0f';c.lineWidth=1;for(let line=12;line<height;line+=glass?130:11){c.beginPath();c.moveTo(32,line);c.lineTo(1048,line);c.stroke();}
      c.strokeStyle=glass?'#ffffffab':'#ccb1888c';c.lineWidth=2;c.strokeRect(34,34,1012,height-68);c.setLineDash([4,8]);c.strokeRect(44,44,992,height-88);c.setLineDash([]);});
    if(profile?.name){
    sections.push({kind:'profile',top:y});
    text('微博里的这些年',82,y,32,920,P.accent,false,48);y+=62;
    if(avatar)op(c=>{c.save();c.beginPath();c.arc(148,yAvatar+64,66,0,Math.PI*2);c.fillStyle='#fffdf1';c.fill();c.clip();const scale=Math.max(128/avatar.width,128/avatar.height);c.drawImage(avatar,84+(128-avatar.width*scale)/2,yAvatar+(128-avatar.height*scale)/2,avatar.width*scale,avatar.height*scale);c.restore();});
    const yAvatar=y;const nameH=text(profile.name,254,y+3,62,746,P.ink,true,85);text('微博人生手账',254,y+nameH+9,34,746,P.muted,false,51);y+=Math.max(152,nameH+76);
    for(const [i,key,label] of [[0,'followers','粉丝'],[1,'following','关注'],[2,'engagement','转评赞']]){const x=80+i*314;panel(x,y,292,140,i===1?P.alt:P.panel);text(profile[key]?.display||'—',x+22,y+19,52,248,P.ink,true,68);text(label,x+22,y+88,32,248,P.muted,false,46);}
    if(avatar)imageSources.push({kind:'avatar',path:profile.avatar_path});y+=192;breaks.push(Math.ceil(y));
    }
    section('review','回看总结');const reviewTop=y;scratch.font=face(66,true);const headH=rows(scratch,D.story.share?.headline||D.story.overview.headline,844).length*92;scratch.font=face(48);const bodyH=rows(scratch,D.story.share?.text||D.story.overview.text,844).length*78;panel(56,reviewTop-12,968,headH+bodyH+96,P.panel);
    text(D.story.share?.headline||D.story.overview.headline,98,y+18,66,844,P.ink,true,92);text(D.story.share?.text||D.story.overview.text,98,y+headH+42,48,844,P.ink,false,78);y+=headH+bodyH+126;breaks.push(Math.ceil(y));
    if(scene){section('scene','记忆小屋');const sceneH=920*scene.height/scene.width;photo(scene,80,y+8,920,sceneH,'把熟悉的日子，轻轻收好');imageSources.push({kind:'generated_scene',path:D.story.scene.image_path});y+=sceneH+118;breaks.push(Math.ceil(y));}
    section('posts','微博里的重要片段');
    for(let i=0;i<entries.length;i++){
      const n=entries[i],record=n.record,asset=options.includePhotos?recordMedia(record)[0]:null,path=asset?(asset.original||asset.large||asset.path):null,im=await trackedLoad(path),column=im?416:842,x=im?(i%2?94:566):110;
      scratch.font=face(52,true);const titleH=rows(scratch,n.title,column).length*76;scratch.font=face(46);const copyH=rows(scratch,n.text||record.text,column).length*74;
      const imH=im?Math.min(478,390*im.height/im.width):0,rowH=Math.max(112+titleH+copyH+38,imH+142),top=y;
      if(rowH>13800)throw new Error('单个片段过长，请先提炼重点内容');panel(56,top-12,968,rowH+24,i%2?P.alt:P.panel);
      text(record.date.replaceAll('-','.'),x,top+20,40,column,P.accent,true,62);text(n.title,x,top+92,52,column,P.ink,true,76);text(n.text||record.text,x,top+108+titleH,46,column,P.ink,false,74);
      if(im){const px=i%2?592:94,py=top+(rowH-imH-52)/2;photo(im,px,py,390,imH,asset.media_kind==='video-cover'?'那一天的视频封面':'那一天留下的照片');const scale=Math.min(390/im.width,imH/im.height);imageSources.push({kind:asset.media_kind==='video-cover'?'video_cover':'record',record_id:record.id,date:record.date,path,draw_bounds:{x:px+(390-im.width*scale)/2,y:py+(imH-im.height*scale)/2,width:im.width*scale,height:im.height*scale}});}
      flourish(i%2?1001:77,top+28,.55);y+=rowH+68;breaks.push(Math.ceil(y));
    }
    if(letter){section('letter','给未来的信');const letterTop=y;scratch.font=face(48);const letterH=rows(scratch,letter,838).length*79;panel(56,y-12,968,letterH+86,P.panel);text(letter,108,y+22,48,838,P.ink,false,79);y+=letterH+126;breaks.push(Math.ceil(y));}
    section('tomorrow','留给明天的小事');
    for(let i=0;i<wishes.length;i++){
      const wish=wishes[i],w=762;scratch.font=face(48,true);const th=rows(scratch,wish.title,w).length*71;scratch.font=face(44);const bh=rows(scratch,wish.note||wish.text||wish.reason||'',w).length*71;const h=th+bh+60;panel(56,y-10,968,h,P.alt);
      op(c=>{c.fillStyle=glass?'#dce993':'#efd7aa';c.beginPath();c.arc(126,wishTop+39,32,0,Math.PI*2);c.fill();c.fillStyle=P.accent;c.font=face(32,true);c.textBaseline='middle';c.fillText(String(i+1).padStart(2,'0'),105,wishTop+39);});const wishTop=y;
      text(wish.title,184,y+16,48,w,P.ink,true,71);text(wish.note||wish.text||wish.reason||'',184,y+24+th,44,w,P.ink,false,71);y+=h+35;breaks.push(Math.ceil(y));
    }
    flourish(540,y+36,1.2);y+=90;text(D.story.share?.closing||'把这些日子，轻轻收好。',94,y,36,892,P.muted,false,56);y+=110;
    y+=text(D.scope+(D.meta.mode==='selected'?' · 基于精选记录整理':''),80,y,28,920,P.muted,false,44)+60;
    const height=Math.ceil(y),maximum=14000,blobs=[];let offset=0;
    while(offset<height){const target=Math.min(height,offset+maximum),safe=breaks.filter(b=>b>offset+300&&b<=target),end=target===height?height:Math.max(...safe);
      if(!Number.isFinite(end))throw new Error('单个部分过长，请先提炼后再分享');const canvas=document.createElement('canvas');canvas.width=1080;canvas.height=Math.ceil(end-offset);const ctx=canvas.getContext('2d');ctx.translate(0,-offset);ops.forEach(fn=>fn(ctx));const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw new Error('浏览器暂时无法生成此尺寸的图片');blobs.push({blob,width:1080,height:canvas.height,top:offset});offset=end;
    }
    return {blobs,height,sections,imageSources,entries:entries.map(n=>({source_id:n.record.id,date:n.record.date}))};
    } finally {
      // 清理临时 blob URL，避免内存泄漏；canvas 绘制已完成，不影响结果
      for (const im of loadedImages) {
        if (im._objectURL) {
          URL.revokeObjectURL(im._objectURL);
          im._objectURL = null;
        }
      }
    }
  }
  let studioURLs=[];function clearURLs(){studioURLs.forEach(URL.revokeObjectURL);studioURLs=[];}
  document.querySelector('#modal').addEventListener('close',clearURLs);
  const openPoster=async()=>{
    clearURLs();const box=node('div','share-studio'),status=node('p','share-status','正在把这些日子排成一张长图…'),toolbar=node('div','share-toolbar'),preview=node('div','share-preview');preview.setAttribute('aria-label','分享图滚动预览');
    const select=node('select','share-part'),save=button('下载 PNG',()=>{},'primary'),copy=button('复制图片',()=>{},'quiet');select.setAttribute('aria-label','选择分享图片');select.hidden=true;save.disabled=true;copy.disabled=true;const zoom=button('放大预览',()=>{const enlarged=preview.classList.toggle('is-zoomed');zoom.textContent=enlarged?'适合屏幕':'放大预览';},'quiet');toolbar.append(select,save,copy,zoom);box.append(status,toolbar,preview);showModal('先看看这张回忆长图',box);document.querySelector('#modal').classList.add('share-dialog');
    try{
      const result=await renderPoster(window.JournalShare.options);window.JournalShare.lastLayout={height:result.height,sections:result.sections,imageSources:result.imageSources,entries:result.entries,parts:result.blobs.map(({width,height,top})=>({width,height,top}))};if(!box.isConnected||!document.querySelector('#modal').open)return;let selected=0;
      for(const [i,part] of result.blobs.entries()){const url=URL.createObjectURL(part.blob);studioURLs.push(url);const image=node('img','share-preview-image');image.src=url;image.alt='分享图'+(i+1);const sheet=node('figure','share-preview-sheet');if(result.blobs.length>1)sheet.append(node('figcaption','','第 '+(i+1)+' 张'));sheet.append(image);preview.append(sheet);const option=node('option','',String(i+1)+' / '+result.blobs.length);option.value=i;select.append(option);}
      status.textContent='上下滚动看看，喜欢的话就把它带走。';save.disabled=false;copy.disabled=false;select.hidden=result.blobs.length===1;
      select.onchange=()=>{selected=Number(select.value);preview.children[selected]?.scrollIntoView({block:'nearest',behavior:'smooth'});};
      save.onclick=()=>download('微博人生手账_1080'+(result.blobs.length>1?'_'+(selected+1):'')+'.png',result.blobs[selected].blob);
      copy.onclick=async()=>{if(!navigator.clipboard?.write||typeof ClipboardItem==='undefined'){status.textContent='这个浏览器暂时无法复制图片，可以下载后分享。';return;}copy.disabled=true;
        try{await navigator.clipboard.write([new ClipboardItem({'image/png':result.blobs[selected].blob})]);status.textContent='图片已复制，可以贴到聊天里分享。';}
        catch(error){status.textContent='这次没有复制成功，可以下载图片后分享。';}finally{copy.disabled=false;}};
    }catch(error){status.textContent='这次没能排好分享图：'+error.message;}
  };
  document.querySelector('#modal').addEventListener('close',()=>document.querySelector('#modal').classList.remove('share-dialog'));
  document.querySelector('#share-button').onclick=()=>{
    const box=node('div'),choices=node('div','share-permissions');
    function permission(label){const wrap=node('label'),input=node('input');input.type='checkbox';wrap.append(input,node('span','',label));choices.append(wrap);return input;}
    const identity=permission('包含头像和主页资料'),photos=permission('包含微博原图');
    box.append(node('p','','先选择分享内容。生成后可以预览，不会自动上传。'),choices,button('生成预览',()=>{window.JournalShare.options={includeProfile:identity.checked,includePhotos:photos.checked};openPoster();},'primary'));showModal('分享内容',box);
  };
  window.JournalShare={renderPoster,selectEntries,options:{includeProfile:false,includePhotos:false}};
})();
