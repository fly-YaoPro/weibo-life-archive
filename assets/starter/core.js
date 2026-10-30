(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.JournalCore=factory();})(typeof window==='undefined'?this:window,function(){
  'use strict';
  function dateKey(value){const time=new Date(value);if(Number.isNaN(time.getTime()))throw new Error('无效日期');return new Date(time.getTime()+28800000).toISOString().slice(0,10);}
  function monthDays(year,month){const first=(new Date(Date.UTC(year,month-1,1)).getUTCDay()+6)%7;const total=new Date(Date.UTC(year,month,0)).getUTCDate();return [...Array(first).fill(null),...Array.from({length:total},(_,i)=>`${year}-${String(month).padStart(2,'0')}-${String(i+1).padStart(2,'0')}`)];}
  function mergePlans(current,incoming){const result=current.map(x=>({...x}));const ids=new Set(result.map(x=>x.id));for(const p of incoming)if(!ids.has(p.id)){result.push({...p});ids.add(p.id);}return result;}
  function validPlans(value){return Array.isArray(value)&&value.length<=1000&&value.every(p=>p&&typeof p.id==='string'&&p.id.length<200&&typeof p.title==='string'&&p.title.length<=160&&/^(19|20|21)\d{2}-(0[1-9]|1[0-2])$/.test(p.month)&&typeof p.done==='boolean'&&(p.note==null||typeof p.note==='string')&&(p.reason==null||typeof p.reason==='string')&&(p.source_ids==null||Array.isArray(p.source_ids)&&p.source_ids.every(s=>typeof s==='string')));}
  function scopeStatus(day,coverage){const c=coverage.find(x=>Number(x.year)===Number(day.slice(0,4)));if(!c)return '未读取，不能判断当天是否有记录';return ({complete:'本次完整读取范围内未收录当天记录',empty:'该年已完整读取，没有记录',selected:'精选未收录，不代表当天没有发布',partial:'部分读取，不能判断当天是否有记录',unread:'尚未读取',failed:'读取失败，不能判断当天是否有记录'})[c.status]||'覆盖状态未知';}
  function search(records,query,category){const q=query.trim().toLocaleLowerCase();return records.filter(r=>(!category||category==='all'||r.category===category)&&(!q||`${r.text} ${r.title} ${r.date}`.toLocaleLowerCase().includes(q)));}
  return{dateKey,monthDays,mergePlans,validPlans,scopeStatus,search};
});
