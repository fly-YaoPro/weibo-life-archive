const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const context={module:{exports:{}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../assets/starter/core.js'),'utf8'),context);
const C=context.module.exports;
test('Beijing date handles UTC and offsets',()=>{assert.equal(C.dateKey('2025-01-01T20:00:00Z'),'2025-01-02');assert.equal(C.dateKey('2025-01-01T23:00:00+08:00'),'2025-01-01');});
test('leap year, Monday offset and last day',()=>{const days=C.monthDays(2024,2);assert.equal(days.filter(Boolean).length,29);assert.equal(days[0],null);assert.equal(days[3],'2024-02-01');assert.equal(days.at(-1),'2024-02-29');assert.equal(C.monthDays(2026,6)[0],'2026-06-01');});
test('merge keeps manual edits and avoids duplicate new IDs',()=>{const a=[{id:'a',title:'manual'}],b=[{id:'a',title:'old'},{id:'b',title:'new'},{id:'b',title:'twice'}];assert.deepEqual(JSON.parse(JSON.stringify(C.mergePlans(a,b))),[{id:'a',title:'manual'},{id:'b',title:'new'}]);assert.equal(a.length,1);});
test('plan schema rejects malformed imports',()=>{assert.equal(C.validPlans([{id:'a',title:'x',month:'2027-01',done:false}]),true);for(const v of [null,{},[{id:'a',title:'x',month:'2027-13',done:false}],[{id:'a',title:'x',month:'2027-01',done:'false'}]])assert.equal(C.validPlans(v),false);});
test('selected, unread, failed are not empty',()=>{for(const status of ['selected','unread','failed','partial'])assert.notEqual(C.scopeStatus('2025-01-01',[{year:2025,status}]),C.scopeStatus('2025-01-01',[{year:2025,status:'empty'}]));});
test('search spans all dates and categories',()=>{const r=[{id:'1',date:'2020-01-01',title:'book',text:'old',category:'A'},{id:'2',date:'2026-10-01',title:'cat',text:'new',category:'B'}];assert.equal(C.search(r,'old')[0].id,'1');assert.equal(C.search(r,'','B')[0].id,'2');});
test('monthly scan distinguishes unselected, empty, failed and outside range',()=>{const m={requested_range:{start:'2025-01-15',end:'2025-04-15'},days:{'2025-01-20':3},monthly:[{month:'2025-01',status:'complete'},{month:'2025-02',status:'unread'},{month:'2025-03',status:'failed'}]};assert.match(C.scopeStatus('2025-01-20',[],m),/已扫描到记录/);assert.match(C.scopeStatus('2025-01-21',[],m),/没有可访问原创/);assert.match(C.scopeStatus('2025-02-01',[],m),/尚未读取/);assert.match(C.scopeStatus('2025-03-01',[],m),/读取失败/);assert.match(C.scopeStatus('2025-01-01',[],m),/范围之外/);});

test('title wrapping balances CJK lines and avoids orphan punctuation',()=>{for(const title of ['把日子慢慢收进一间温暖的小屋','那一年，窗台的薄荷又长出了一片新叶','翻开一本旧书，也翻开那些日子']){const rows=Array.from(C.balancedLines(title,10,t=>Array.from(t).length));assert.equal(rows.join(''),title);assert.ok(rows.every(r=>r.length<=10));assert.ok(rows.at(-1).length>2);assert.ok(rows.every(r=>!/[，。！？：；、）》」』]/.test(r[0])));}});
test('title wrapping preserves English word boundaries',()=>{const rows=Array.from(C.balancedLines('A Room Full of Memories',12,t=>t.length));assert.equal(rows.join(' '),'A Room Full of Memories');});

test('title segmentation keeps Chinese words together',()=>{const title='合成演示：在普通日子里，留下光',rows=Array.from(C.balancedLines(title,12,t=>Array.from(t).length));assert.equal(rows.join(''),title);assert.ok(rows.every((row,i)=>!(row.endsWith('普')&&rows[i+1]?.startsWith('通'))));});

const readerContext={window:{JournalCore:C}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../assets/starter/reader.js'),'utf8'),readerContext);
test('reading pagination preserves every character and punctuation',()=>{for(const text of ['窗台的薄荷又长了一片叶子。每次浇水，都像给普通的一天打一个小小的记号。','A quiet room full of memories. Keep every word here.','第一段。\n\n第二段，还有旧书和练习曲。']){const parts=Array.from(readerContext.window.JournalReader.pieces(text,18));assert.equal(parts.join(''),text);assert.ok(parts.length>1);}});
