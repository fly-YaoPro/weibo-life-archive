(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.JournalCore=factory();})(typeof window==='undefined'?this:window,function(){
  'use strict';
  function dateKey(value){const time=new Date(value);if(Number.isNaN(time.getTime()))throw new Error('无效日期');return new Date(time.getTime()+28800000).toISOString().slice(0,10);}
  function monthDays(year,month){const first=(new Date(Date.UTC(year,month-1,1)).getUTCDay()+6)%7;const total=new Date(Date.UTC(year,month,0)).getUTCDate();return [...Array(first).fill(null),...Array.from({length:total},(_,i)=>`${year}-${String(month).padStart(2,'0')}-${String(i+1).padStart(2,'0')}`)];}
  function mergePlans(current,incoming){const result=current.map(x=>({...x}));const ids=new Set(result.map(x=>x.id));for(const p of incoming)if(!ids.has(p.id)){result.push({...p});ids.add(p.id);}return result;}
  function validPlans(value){return Array.isArray(value)&&value.length<=1000&&value.every(p=>p&&typeof p.id==='string'&&p.id.length<200&&typeof p.title==='string'&&p.title.length<=160&&/^(19|20|21)\d{2}-(0[1-9]|1[0-2])$/.test(p.month)&&typeof p.done==='boolean'&&(p.note==null||typeof p.note==='string')&&(p.reason==null||typeof p.reason==='string')&&(p.source_ids==null||Array.isArray(p.source_ids)&&p.source_ids.every(s=>typeof s==='string')));}
  function scopeStatus(day,coverage,metrics){if(metrics){if(day<metrics.requested_range.start||day>metrics.requested_range.end)return '日期在本次范围之外';const count=metrics.days[day]||0,m=metrics.monthly.find(m=>m.month===day.slice(0,7));if(count)return '当天已扫描到记录，未收录部分不在精选中';if(m?.status==='complete')return '本次完整扫描范围内当天没有可访问原创图文';if(m?.status==='failed')return '该月读取失败，不能判断当天是否发布';if(m?.status==='unread')return '该月尚未读取，不能判断当天是否发布';return '该月仅部分读取，不能判断当天是否发布';}const c=coverage.find(x=>Number(x.year)===Number(day.slice(0,4)));if(!c)return '未读取，不能判断当天是否有记录';return ({complete:'本次完整读取范围内未收录当天记录',empty:'该年已完整读取，没有记录',selected:'精选未收录，不代表当天没有发布',partial:'部分读取，不能判断当天是否有记录',unread:'尚未读取',failed:'读取失败，不能判断当天是否有记录'})[c.status]||'覆盖状态未知';}
  function search(records,query,category){const q=query.trim().toLocaleLowerCase();return records.filter(r=>(!category||category==='all'||r.category===category)&&(!q||`${r.text} ${r.title} ${r.date}`.toLocaleLowerCase().includes(q)));}
  function titleSegments(text){
    const raw=typeof Intl.Segmenter==='function'?Array.from(new Intl.Segmenter('zh',{granularity:'word'}).segment(String(text)),s=>s.segment):Array.from(String(text)),result=[];let prefix='';
    for(const part of raw){if(/^[（《「『“‘]+$/.test(part)){prefix+=part;continue;}if(/^[，。！？：；、）》」』”’]+$/.test(part)&&result.length){result[result.length-1]+=part;continue;}result.push(prefix+part);prefix='';}if(prefix)result.push(prefix);return result;
  }
  function balancedLines(text,width,measure){
    const chars=Array.from(String(text||''));if(!chars.length)return [''];
    const n=chars.length,total=measure(chars.join('')),cuts=new Set([0]);let position=0;for(const token of titleSegments(text)){position+=Array.from(token).length;cuts.add(position);}
    if(total<=width)return [chars.join('')];
    let count=1,start=0;for(let j=1;j<=n;j++){if(measure(chars.slice(start,j).join(''))>width&&j>start+1){count++;start=j-1;}}
    const close=/[，。！？：；、）》」』”’]/,open=/[（《「『“‘]/,word=/[A-Za-z0-9]/;
    for(let k=count;k<=Math.min(n,count+2);k++){
      const target=total/k,dp=Array.from({length:k+1},()=>Array(n+1).fill(Infinity)),prev=Array.from({length:k+1},()=>Array(n+1).fill(-1));dp[0][0]=0;
      for(let row=1;row<=k;row++)for(let end=row;end<=n;end++)for(let begin=row-1;begin<end;begin++){
        if(!Number.isFinite(dp[row-1][begin]))continue;
        const line=chars.slice(begin,end).join('').trim(),w=measure(line);
        if(!line||w>width||close.test(chars[begin])||open.test(chars[end-1])||(typeof Intl.Segmenter==='function'&&!cuts.has(end)))continue;
        let cost=(w-target)**2;
        if(end<n&&word.test(chars[end-1])&&word.test(chars[end]))cost+=width**2*100;
        if(row===k&&line.length<=2)cost+=width**2*100;
        if(/[,，:：;；]/.test(chars[end-1]))cost-=width*2;
        if(dp[row-1][begin]+cost<dp[row][end]){dp[row][end]=dp[row-1][begin]+cost;prev[row][end]=begin;}
      }
      if(Number.isFinite(dp[k][n])){const result=[];let end=n;for(let row=k;row>0;row--){const begin=prev[row][end];result.unshift(chars.slice(begin,end).join('').trim());end=begin;}return result;}
    }
    throw new Error('标题存在无法容纳的文字或标点，请调整标题措辞或版式宽度');
  }
  return{dateKey,monthDays,mergePlans,validPlans,scopeStatus,search,balancedLines,titleSegments};
});
