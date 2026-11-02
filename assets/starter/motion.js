/* Offline interaction choreography. No model calls, sound downloads, or device permissions. */
(()=>{
  'use strict';const U=window.JournalUI;if(!U)return;
  const {node}=U,reduced=matchMedia('(prefers-reduced-motion: reduce)'),events=[];
  const audit=(event,kind)=>events.push({event,kind,time:performance.now(),audioState:audioContext?.state||'unavailable'}),delay=ms=>new Promise(r=>setTimeout(r,ms));
  let audioContext,noiseSeed=9173;
  function sound(kind){
    const duration=kind==='portal'?2.05:.38;let context;
    try{const Constructor=window.AudioContext||window.webkitAudioContext;if(!Constructor)return delay(duration*1000);context=audioContext||(audioContext=new Constructor());context.resume().catch(()=>{});}catch(e){return delay(duration*1000);}
    const buffer=context.createBuffer(1,Math.ceil(context.sampleRate*duration),context.sampleRate),channel=buffer.getChannelData(0);
    for(let i=0;i<channel.length;i++){noiseSeed^=noiseSeed<<13;noiseSeed^=noiseSeed>>>17;noiseSeed^=noiseSeed<<5;channel[i]=((noiseSeed>>>0)/4294967296*2-1);}
    const source=context.createBufferSource(),filter=context.createBiquadFilter(),gain=context.createGain(),start=context.currentTime;
    source.buffer=buffer;filter.type='bandpass';filter.frequency.setValueAtTime(kind==='portal'?220:1200,start);filter.Q.value=.7;
    if(kind==='portal'){filter.frequency.exponentialRampToValueAtTime(1900,start+.9);filter.frequency.exponentialRampToValueAtTime(280,start+duration);}
    gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(kind==='portal'?.038:.055,start+.05);gain.gain.exponentialRampToValueAtTime(.0001,start+duration);
    source.connect(filter).connect(gain).connect(context.destination);
    if(kind==='portal')for(const [index,frequency] of [392,523.25,659.25].entries()){const oscillator=context.createOscillator(),level=context.createGain(),time=start+.25+index*.22;oscillator.type='sine';oscillator.frequency.value=frequency;level.gain.setValueAtTime(0,time);level.gain.linearRampToValueAtTime(.018,time+.04);level.gain.exponentialRampToValueAtTime(.0001,start+duration);oscillator.connect(level).connect(context.destination);oscillator.start(time);oscillator.stop(start+duration);}
    audit('sound-start',kind);source.start(start);source.stop(start+duration);
    return new Promise(resolve=>{let finished=false;const finish=()=>{if(finished)return;finished=true;clearTimeout(timer);audit('sound-end',kind);resolve();};const timer=setTimeout(finish,duration*1000+350);source.onended=()=>{source.disconnect();filter.disconnect();gain.disconnect();finish();};});
  }
  const M={busy:false,events,
    async flip(direction,commit){
      if(M.busy)return;M.busy=true;
      const host=document.querySelector('#spread'),pager=document.querySelector('#pager'),oldBook=host.firstElementChild;
      const leaves=book=>[...book.querySelectorAll(':scope>.leaf')].sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left);
      const oldLeaves=leaves(oldBook),spread=innerWidth>=700&&oldLeaves.length===2,sign=direction>0?1:-1;
      const original=spread?(sign>0?oldLeaves[1]:oldLeaves[0]):oldBook,still=spread?(sign>0?oldLeaves[0]:oldLeaves[1]):null;
      const originalClone=original.cloneNode(true),stillClone=still?.cloneNode(true),oldRect=original.getBoundingClientRect(),stillRect=still?.getBoundingClientRect(),bounds=host.getBoundingClientRect();
      const oldClasses=oldBook.className,oldChapter=oldBook.dataset.chapter,originalIndex=spread?[...oldBook.children].indexOf(original):0,stillIndex=spread?[...oldBook.children].indexOf(still):0;
      const hinge=spread?(oldLeaves[0].getBoundingClientRect().right+oldLeaves[1].getBoundingClientRect().left)/2:bounds.left+bounds.width/2;
      const width=spread?(sign>0?oldRect.right-hinge:hinge-oldRect.left):bounds.width,height=spread?oldRect.height:bounds.height,top=(spread?oldRect.top:bounds.top)-bounds.top;
      const previousCounter=pager.querySelector('.page-counter')?.textContent,hadFocus=pager.contains(document.activeElement);
      let layer,animation,frame,counter,nextCounter,finishEarly;
      pager.inert=true;host.dataset.turning=sign>0?'next':'previous';audit('flip-start','page');sound('page');
      try{
        commit();const nextBook=host.firstElementChild,nextLeaves=leaves(nextBook);
        counter=pager.querySelector('.page-counter');nextCounter=counter?.textContent;if(counter)counter.textContent=previousCounter;
        if(!reduced.matches){
          const nextLeaf=spread&&nextLeaves.length===2?(sign>0?nextLeaves[0]:nextLeaves[1]):nextBook,nextRect=nextLeaf.getBoundingClientRect();
          layer=node('div','page-turn-layer');layer.setAttribute('aria-hidden','true');layer.inert=true;layer.dataset.direction=sign>0?'next':'previous';layer.dataset.geometry=spread?'spread':'card';
          // Freeze both source pages at their real width, including the gutter. The temporary
          // slices contain inert DOM copies; no screenshot, canvas font substitution or network.
          function surface(clone,classes,chapter,x,w,h,rect,index=0){
            const face=node('div','turn-surface'),context=node('div',classes+' turn-context');context.dataset.chapter=chapter;
            Object.assign(face.style,{width:width+'px',height:height+'px'});
            Object.assign(context.style,{position:'absolute',left:x+'px',top:'0',width:w+'px',height:h+'px',display:'block',padding:'0',margin:'0',border:'0',background:'#fffaf0',boxShadow:'none'});
            if(document.body.dataset.skin==='frosted'){
              const background=getComputedStyle(document.body);
              Object.assign(context.style,{backgroundColor:background.backgroundColor,backgroundImage:background.backgroundImage,
                backgroundSize:document.body.clientWidth+'px '+Math.max(innerHeight,document.body.scrollHeight)+'px',
                backgroundPosition:-rect.left+'px '+-rect.top+'px',backgroundRepeat:background.backgroundRepeat});
            }
            Object.assign(clone.style,{width:'100%',height:'100%',margin:'0'});
            clone.querySelectorAll('img').forEach(image=>image.loading='eager');
            for(const el of [clone,...clone.querySelectorAll('[id]')])el.removeAttribute('id');
            for(let i=0;i<index;i++){const placeholder=node('span');placeholder.hidden=true;context.append(placeholder);}
            context.append(clone);face.append(context);return face;
          }
          if(stillClone){
            const stationary=node('div','turn-stationary');Object.assign(stationary.style,{left:stillRect.left-bounds.left+'px',top:stillRect.top-bounds.top+'px',width:stillRect.width+'px',height:stillRect.height+'px'});
            const fixed=surface(stillClone,oldClasses,oldChapter,0,stillRect.width,stillRect.height,stillRect,stillIndex);fixed.style.width=stillRect.width+'px';fixed.style.height=stillRect.height+'px';stationary.append(fixed);layer.append(stationary);
          }
          const shadow=node('div','turn-cast-shadow');Object.assign(shadow.style,{left:(spread?Math.min(stillRect.left,oldRect.left):bounds.left)-bounds.left+'px',top:top+'px',width:(spread?Math.max(oldRect.right,stillRect.right)-Math.min(oldRect.left,stillRect.left):width)+'px',height:height+'px'});layer.append(shadow);
          const sheet=node('div','page-turn-sheet');sheet.dataset.direction=layer.dataset.direction;Object.assign(sheet.style,{left:hinge-bounds.left+'px',top:top+'px',width:width+'px',height:height+'px'});
          const sourceFront=surface(originalClone,oldClasses,oldChapter,spread&&sign>0?oldRect.left-hinge:0,oldRect.width,oldRect.height,oldRect,originalIndex);
          const sourceBack=surface(nextLeaf.cloneNode(true),nextBook.className,nextBook.dataset.chapter,spread&&sign<0?width-nextRect.width:0,nextRect.width,nextRect.height,nextRect,spread?[...nextBook.children].indexOf(nextLeaf):0);
          const count=spread?20:12,step=width/count,strips=[];
          for(let i=0;i<count;i++){
            const strip=node('div','turn-strip'),front=node('div','turn-face turn-front'),back=node('div','turn-face turn-back');
            Object.assign(strip.style,{width:(step+.65)+'px',height:height+'px'});
            const frontSurface=sourceFront.cloneNode(true),backSurface=sourceBack.cloneNode(true);
            frontSurface.style.left=-(sign>0?i*step:width-(i+1)*step)+'px';
            backSurface.style.left=-(sign>0?width-(i+1)*step:i*step)+'px';
            for(const picture of [...frontSurface.querySelectorAll('img'),...backSurface.querySelectorAll('img')]){
              const orient=()=>{const frame=picture.closest('.photo-frame');if(frame&&picture.naturalWidth){const ratio=picture.naturalWidth/picture.naturalHeight;frame.dataset.orientation=ratio<.87?'portrait':ratio<1.15?'square':'landscape';}};
              picture.addEventListener('load',orient,{once:true});if(picture.complete)orient();
            }
            front.append(frontSurface);back.append(backSurface);back.hidden=true;strip.append(front,back,node('span','turn-strip-light'));sheet.append(strip);strips.push({strip,front,back});
          }
          layer.append(sheet);host.append(layer);
          // The clock is a WAAPI animation so capture/verification can pause exact frames.
          // Geometry is updated per strip; every visible face always faces the camera.
          animation=sheet.animate([{'--turn-clock':'0'},{'--turn-clock':'1'}],{duration:720,easing:'cubic-bezier(.26,.06,.32,1)',fill:'forwards'});
          function paint(){
            const progress=animation.effect.getComputedTiming().progress||0,angle=-sign*Math.PI*progress;
            const bend=.22*Math.sin(Math.PI*progress),mobileShift=spread?0:-sign*width*.5*Math.cos(angle);
            let x=0,z=0,backCount=0;
            for(let i=0;i<count;i++){
              const a=angle+sign*bend*(i+.5)/count,dx=sign*step*Math.cos(a),dz=-sign*step*Math.sin(a),item=strips[i],reverse=Math.cos(a)<0;
              const facing=a+(reverse?sign*Math.PI:0),cx=x+dx*.5+mobileShift,cz=z+dz*.5;
              item.strip.style.transform='translate3d('+(cx-step*.5)+'px,0,'+cz+'px) rotateY('+facing+'rad) scaleY('+(1-.98*cz/3200)+')';
              item.front.hidden=reverse;item.back.hidden=!reverse;if(reverse)backCount++;
              item.strip.style.setProperty('--turn-shade',(Math.sin(Math.PI*progress)*(.02+.16*Math.abs(Math.sin(a)))).toFixed(3));
              x+=dx;z+=dz;
            }
            layer.dataset.face=backCount===count?'back':backCount===0?'front':'edge';
            layer.dataset.progress=progress.toFixed(4);
            shadow.style.opacity=(.28*Math.sin(Math.PI*progress)).toFixed(3);
            shadow.style.setProperty('--shadow-side',(sign>0?1-progress:progress)*100+'%');
            frame=requestAnimationFrame(paint);
          }
          paint();finishEarly=()=>animation?.finish();addEventListener('resize',finishEarly,{once:true});
          await animation.finished.catch(()=>{});
        }else{
          const fade=nextBook.animate([{opacity:.3},{opacity:1}],{duration:120});await fade.finished.catch(()=>{});
        }
      }finally{
        cancelAnimationFrame(frame);if(finishEarly)removeEventListener('resize',finishEarly);animation?.cancel();layer?.remove();delete host.dataset.turning;
        if(counter?.isConnected)counter.textContent=nextCounter;pager.inert=false;M.busy=false;U.refreshReadingLayout();
        if(hadFocus)pager.querySelector(sign>0?'button:last-child':'button:first-child')?.focus({preventScroll:true});audit('flip-end','page');
      }
    },
    async enter(target={view:'review',theme_id:'overview'}){
      if(M.busy)return;M.busy=true;audit('entry-start','portal');window.JournalExperience?.setMusic(false);
      const portal=node('div','time-portal');portal.setAttribute('role','status');portal.setAttribute('aria-label','正在翻开那些日子');const rings=node('div','portal-rings');for(let i=0;i<6;i++){const ring=node('span');ring.style.setProperty('--ring',i);rings.append(ring);}portal.append(rings,node('p','portal-line','让那些日子，再慢慢走近。'));document.body.append(portal);
      try{
        const effect=sound('portal');await delay(reduced.matches?120:800);U.go(target);await Promise.all([effect,delay(reduced.matches?100:1100)]);
        portal.dataset.leaving='true';await delay(reduced.matches?80:330);
      }finally{
        portal.remove();M.busy=false;U.refreshReadingLayout();
      }
      // The introduction is already visible as the portal clears. An opacity-zero
      // animation here caused it to flash away immediately after the reveal.
      if(!reduced.matches)document.querySelector('#spread').animate([{transform:'translateY(6px)'},{transform:'translateY(0)'}],{duration:450,easing:'ease-out'});
      if(await window.JournalExperience?.setMusic(true))audit('music-start','portal');audit('entry-end','portal');
    }

  };
  window.JournalMotion=M;
  const observed=new Set(),observer='IntersectionObserver'in window?new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){entry.target.classList.add('is-revealed');observer.unobserve(entry.target);observed.delete(entry.target);}},{threshold:.06,rootMargin:'0px 0px -12px 0px'}):null;
  function reveal(){if(!observer||reduced.matches)return;for(const element of observed)if(!element.isConnected){observer.unobserve(element);observed.delete(element);}
    const selector='#stats .archive-totals>div,#stats .memory-photos>figure,#stats .annual-review>h2,#stats .annual-review>p,#stats .chart-paper,#letter-content .future-letter>h1,#letter-content .future-letter>p,#letter-content .letter-keepsake,#plans .wish-card';
    document.querySelectorAll(selector).forEach((el,i)=>{if(el.dataset.reveal)return;el.dataset.reveal='true';el.classList.add('scroll-reveal');el.style.setProperty('--reveal-delay',(i%3)*65+'ms');observer.observe(el);observed.add(el);});
  }
  let scrollFrame;function progress(){cancelAnimationFrame(scrollFrame);scrollFrame=requestAnimationFrame(()=>{const height=document.documentElement.scrollHeight-innerHeight,value=height>0?scrollY/height:0;document.documentElement.style.setProperty('--scroll-progress',Math.max(0,Math.min(1,value)));});}
  addEventListener('scroll',progress,{passive:true});document.addEventListener('journal:view',()=>{requestAnimationFrame(reveal);progress();});requestAnimationFrame(reveal);
  // A small light reflection follows the cursor; original photo pixels stay unchanged.
  if(matchMedia('(hover: hover)').matches)document.addEventListener('pointermove',event=>{if(reduced.matches)return;const mount=event.target.closest?.('.photo-mount');if(!mount)return;const r=mount.getBoundingClientRect();mount.style.setProperty('--shine-x',(event.clientX-r.left)/r.width*100+'%');mount.style.setProperty('--shine-y',(event.clientY-r.top)/r.height*100+'%');},{passive:true});
})();
