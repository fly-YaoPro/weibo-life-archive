/* Responsive reading sheets. Content continues on another page instead of shrinking or clipping. */
(()=>{
  'use strict';const C=window.JournalCore;
  function pieces(text,budget){
    if(!text)return [''];const tokens=C.titleSegments(String(text)),chunks=[];let part='';
    for(const token of tokens){if(part&&Array.from(part+token).length>budget){chunks.push(part);part='';}part+=token;}
    if(part)chunks.push(part);return chunks;
  }
  function prepare(D){
    const width=innerWidth,short=innerHeight<700,mobile=width<700,header=document.querySelector('.site-header').offsetHeight;
    const textWidth=mobile?Math.max(220,width-88):Math.max(320,Math.min(1200,width-80)/2-90);
    const fontSize=mobile?16:17,charsPerLine=Math.floor(textWidth/fontSize)*.88;
    const bookHeight=innerHeight-header-100,visualHeight=mobile?Math.max(100,Math.min(180,bookHeight*.33)):0;
    const chapters=[{...D.story.overview,id:'overview',title:D.story.overview.headline},...D.story.themes],result=[];
    for(const [index,chapter] of chapters.entries()){
      const images=chapter.images?.length?chapter.images:(chapter.source_ids||[]).flatMap(id=>{const r=D.records.find(r=>r.id===id);return (r?.video?.covers||[]).map(im=>({...im,date:r.date,record_id:r.id,media_kind:'video-cover',caption:'视频封面 · '+(im.caption||r.title)}));}),titleLines=Math.ceil(Array.from(chapter.title||'').length/(textWidth/(mobile?25:35)));
      const copyHeight=bookHeight-visualHeight-(mobile?130:160)-titleLines*(mobile?35:48);
      const budget=Math.max(short?24:44,Math.min(chapter.id==='overview'?(mobile?80:120):(mobile?104:200),Math.floor(copyHeight/(fontSize*1.8))*charsPerLine));
      const text=[chapter.text,chapter.note].filter(Boolean).join('\n\n'),chunks=pieces(text,budget),pair=!mobile&&chapter.layout==='B'?2:1;
      const distinctExcerpt=chapter.id!=='overview'&&chapter.excerpt&&!text.includes(chapter.excerpt)&&!chapter.excerpt.includes(text),shortExcerpt=distinctExcerpt&&innerHeight<600&&!mobile;
      let consumed=0;
      chunks.forEach((text,part)=>{const selected=((chapter.id==='overview'&&(mobile||innerHeight<600))||shortExcerpt)&&part===0?[]:images.slice(consumed,consumed+pair);consumed+=selected.length;result.push({...chapter,text,images:selected,chapterId:chapter.id,chapterIndex:index,part,kind:'story',id:part?chapter.id+'-'+part:chapter.id});});
      if(mobile&&distinctExcerpt){pieces(chapter.excerpt,Math.max(40,budget)).forEach((text,j)=>result.push({...chapter,id:chapter.id+'-excerpt-'+j,chapterId:chapter.id+'-excerpt',text,excerpt:null,images:[],chapterIndex:index,part:j,kind:'excerpt'}));}
      if((width<1000||innerHeight<760)&&chapter.id==='overview'&&chapter.portrait){const portrait=chapter.portrait,profileText=[chapter.opening,portrait.text].filter(Boolean).join('\n\n');pieces(profileText,Math.max(60,budget)).forEach((text,j)=>result.push({...chapter,id:'overview-portrait-'+j,chapterId:'overview-portrait',title:portrait.title||'从这些片段里看见的你',text,source_ids:portrait.source_ids,images:[],part:j,chapterIndex:0,kind:'profile',portrait:null}));}
      const galleryStep=mobile||innerHeight<500?1:2;
      for(let i=consumed;i<images.length;i+=galleryStep){result.push({...chapter,text:'',images:images.slice(i,i+galleryStep),chapterId:chapter.id,chapterIndex:index,part:chunks.length+i-consumed,kind:'gallery',id:chapter.id+'-photo-'+i});}
    }
    // Explicit milestones stay available as compact reading pages; no invented fallback summary.
    (D.story.milestones||[]).forEach((m,i)=>{const record=D.records.find(r=>r.id===m.source_ids[0]);pieces(m.text||'',innerWidth<700?80:160).forEach((text,j)=>result.push({...m,id:'milestone-'+i+'-'+j,chapterId:'milestone-'+i,chapterIndex:chapters.length+i,part:j,kind:'story',text,images:record?.images.slice(0,1).map(im=>({...im,date:record.date,caption:im.caption||record.title}))||[]}));});
    return result;
  }
  function highlights(D,ids){
    const rows=D.records.filter(r=>ids.includes(r.id)),years=[...new Set(rows.map(r=>r.date.slice(0,4)))].sort();
    const chosen=years.length>3?[years[0],years[Math.floor(years.length/2)],years.at(-1)]:years;
    return chosen.map((year,index)=>{const candidates=rows.filter(r=>r.date.startsWith(year)),row=candidates[index%candidates.length],theme=D.story.themes.find(t=>t.source_ids.includes(row.id));return {row,year,title:theme?.title||row.title};});
  }
  function profileCard(D,U){
    const P=D.meta.profile;if(!P)return null;const {node}=U,card=node('section','user-profile');card.setAttribute('aria-label','微博主页资料');card.dataset.uid=P.uid;
    const row=node('div','profile-heading');if(P.avatar_path){const avatar=node('img','profile-avatar');avatar.src=window.JOURNAL_ASSETS?.[P.avatar_path]||P.avatar_path;avatar.alt=P.name+'的微博头像';row.append(avatar);}
    const name=node('div','profile-name-wrap');name.append(node('p','profile-eyebrow','微博里的这些年'),node('h2','profile-name',P.name));row.append(name);card.append(row);
    const counts=node('dl','profile-counts');for(const [key,label] of [['followers','粉丝'],['following','关注'],['engagement','转评赞']]){const cell=node('div');cell.dataset.metric=key;cell.append(node('dt','',label),node('dd','',P[key]?.display||'—'));counts.append(cell);}card.append(counts);return card;
  }
  function render(D,p,U){
    const {node,photo,sources,button}=U,book=node('article','book reader-book reader-'+p.kind+' theme-'+(p.layout||'A'));
    book.dataset.chapter=p.chapterId;
    const first=p.chapterId==='overview'&&p.part===0;if(first&&D.meta.profile)book.classList.add('profile-first');
    const copy=node('div','leaf reader-copy reader-main-copy editorial'),head=node('div','reader-heading');
    if(first&&innerWidth<700){const identity=profileCard(D,U);if(identity)head.append(identity);}
    head.append(node('p','ribbon',p.chapterId==='overview'?'回看':p.kind==='excerpt'?'原文摘句':`片段 ${String(p.chapterIndex).padStart(2,'0')}${p.part?' · 续页':''}`),node('h1','',p.title));
    copy.append(head);
    const body=node('div','reader-prose');if(p.text)body.append(node('p','lead',p.text));
    if(innerWidth>=1000&&innerHeight>=760&&p.chapterId!=='overview'&&p.excerpt&&p.excerpt!==p.text&&!p.text.includes(p.excerpt)&&p.part===0){const quote=node('blockquote','reader-quote',pieces(p.excerpt,55)[0]);body.prepend(quote);}
    copy.append(body,sources(p.source_ids,true));
    const visual=node('div','leaf reader-visual');(p.images||[]).forEach((asset,i)=>visual.append(photo(asset,i,'reader-photo')));
    visual.dataset.count=String(p.images?.length||0);
    const cover=first&&p.kind==='story'&&innerWidth>=1000&&innerHeight>=760;
    if(first&&innerWidth>=700){const identity=profileCard(D,U);if(identity){visual.prepend(identity);visual.classList.add('identity-visual');}}
    if(cover){
      book.classList.add('reader-cover');visual.classList.add('cover-visual');
      if(p.opening)visual.append(node('p','cover-opening',p.opening));
      if(p.portrait){const portrait=node('section','cover-portrait');portrait.append(node('h2','',p.portrait.title||'从这些片段里看见的你'),node('p','',p.portrait.text));const tags=node('div','portrait-tags');(p.portrait.tags||[]).slice(0,4).forEach(t=>tags.append(node('span','',t)));portrait.append(tags);copy.append(portrait);}
      const memories=node('div','reader-highlights');highlights(D,p.source_ids).forEach(({row,year,title})=>{const card=button('',()=>window.JournalUI.openRecords([row.id],row.date+' · '+row.title),'highlight-card');card.dataset.recordId=row.id;card.append(node('time','highlight-year',year),node('h3','',title));memories.append(card);});copy.append(memories);
    }
    if(!p.images?.length){
      book.classList.add('reader-text-only');
      if(innerWidth>=700){
        const quoteLeaf=node('div','leaf reader-copy reader-quote-leaf');
        if(first&&D.meta.profile){quoteLeaf.append(profileCard(D,U));if(p.opening&&cover)quoteLeaf.append(node('p','cover-opening',p.opening));}
        else{
          const explicit=p.excerpt&&p.part===0&&!(innerWidth>=1000&&innerHeight>=760),source=D.records.find(r=>(p.source_ids||[]).includes(r.id));
          if(explicit){
            quoteLeaf.append(node('p','eyebrow','原文摘句'),node('blockquote','reader-quote',p.excerpt));
            const evidence=D.records.find(r=>(p.source_ids||[]).includes(r.id)&&r.text.includes(p.excerpt));if(evidence)quoteLeaf.append(node('time','',evidence.date));
          }else{
            // A record may support multiple chapters with different evidence. Its first
            // paragraph is not a chapter-specific quote, so never invent that fallback.
            quoteLeaf.append(node('p','eyebrow',p.part?'沿着这一段，继续读':'这一页的记忆'),node('p','reader-page-mark',String(p.chapterIndex).padStart(2,'0')),node('p','reader-continuation',p.title));if(source)quoteLeaf.append(node('time','',source.date));
          }

        }
        const spine=node('div','spine');spine.setAttribute('aria-hidden','true');for(let i=0;i<5;i++)spine.append(node('i','ring'));book.append(quoteLeaf,spine,copy);
      }else book.append(copy);
    }
    else if(p.kind==='gallery'){
      if(innerWidth>=700){book.classList.add('reader-gallery-spread');const left=node('div','leaf reader-visual gallery-leaf');left.dataset.count='1';left.append(photo(p.images[0],0,'reader-photo'));const right=node('div','leaf '+(p.images[1]?'reader-visual gallery-leaf':'reader-copy editorial'));const title=node('div','reader-heading');title.append(node('p','ribbon','照片里的那一天'),node('h1','',p.title));right.append(title);
        if(p.images[1])right.append(photo(p.images[1],1,'reader-photo'));else if(p.images[0].caption)right.append(node('p','lead',p.images[0].caption));right.append(sources(p.source_ids,true));const spine=node('div','spine');spine.setAttribute('aria-hidden','true');for(let i=0;i<5;i++)spine.append(node('i','ring'));book.append(left,spine,right);
      }else{const title=node('div','reader-gallery-heading');title.append(node('p','eyebrow','照片里的那一天'),node('h1','',p.title));book.append(title,visual,sources(p.source_ids,true));}
    }
    else{const spine=node('div','spine');spine.setAttribute('aria-hidden','true');for(let i=0;i<5;i++)spine.append(node('i','ring'));if(p.layout==='C')book.append(copy,spine,visual);else book.append(visual,spine,copy);}
    return book;
  }
  window.JournalReader={prepare,render,pieces,profileCard};
})();
