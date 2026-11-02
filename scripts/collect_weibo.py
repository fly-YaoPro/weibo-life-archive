"""Logged-in desktop snapshots and observed same-origin timelines, with checkpoints."""
import hashlib
from copy import deepcopy
import json
import math
import time
from datetime import datetime
from pathlib import Path

from archive_common import BEIJING, date_key, load, months, project_file, save, timestamp
from archive_pipeline import ingest
from weibo_web import desktop_expression, full_time, history_gate_expression, permalink_mid, timeline_expression, timeline_payload, timeline_request, mobile_container_path, mobile_gate_expression, mobile_payload, mobile_url


def configure_desktop(bu, root, selectors, minimum_interval=4):
    root = Path(root); uid = load(root / 'project_meta.json')['target']['uid']
    expression = desktop_expression(uid, selectors)
    if not isinstance(minimum_interval, (int, float)) or minimum_interval < 4:
        raise ValueError('桌面快照保守串行，间隔至少4秒；不是免风控保证')
    result = bu.js(expression); result = json.loads(result) if isinstance(result, str) else result
    if not isinstance(result, dict) or not result.get('success'):
        return {'status': result.get('reason', 'invalid_snapshot') if isinstance(result, dict) else 'invalid_snapshot'}
    save(root / 'desktop-collection.json', {'uid': uid, 'selectors': selectors, 'minimum_interval': minimum_interval,
                                         'verified_at': datetime.now(BEIJING).isoformat()})
    return {'status': 'configured', 'route': 'logged_in_desktop_dom', 'observed_count': result['observed_count']}


def collect_snapshot(bu, root, clock=time.time):
    root = Path(root); uid = load(root / 'project_meta.json')['target']['uid']
    config = load(root / 'desktop-collection.json')
    if not config:
        return {'status': 'setup_required', 'note': '先读取宿主computer_use/browser_use Skill，登录weibo.com并核验原创列表选择器'}
    if config.get('uid') != uid:
        raise ValueError('桌面采集设置与目标UID不符')
    state = load(root / 'desktop-state.json', {'uid': uid, 'snapshots': [], 'unchanged': 0})
    if state.get('uid') != uid:
        raise ValueError('断点账号不匹配')
    if state.get('blocked'):
        return {'status': 'handoff', 'reason': state['blocked'], 'note': '保留断点；用户完成登录/站点验证并正常核验后才解除，不删除失败状态'}
    now = clock()
    if now < state.get('next_allowed_at', 0):
        return {'status': 'cooldown', 'wait_seconds': round(state['next_allowed_at'] - now, 2)}
    try:
        value = bu.js(desktop_expression(uid, config['selectors']))
        value = json.loads(value) if isinstance(value, str) else value
        if not isinstance(value, dict) or type(value.get('success')) is not bool:
            raise ValueError('宿主未返回同步JSON快照')
    except Exception as error:
        state['failures'] = state.get('failures', 0) + 1
        state['next_allowed_at'] = now + 45
        if state['failures'] >= 2:
            state['blocked'] = 'snapshot_failed'
        save(root / 'desktop-state.json', state)
        return {'status': 'handoff' if state.get('blocked') else 'verify_once', 'reason': type(error).__name__}
    state['next_allowed_at'] = now + config['minimum_interval']
    if not value['success']:
        reason = value.get('reason', 'invalid_snapshot')
        state['blocked'] = reason
        save(root / 'desktop-state.json', state)
        return {'status': 'login_required' if reason == 'login_required' else 'handoff', 'reason': reason}
    from user_profile import desktop_url
    if not desktop_url(value.get('source_url',''),uid):
        state['blocked']='wrong_target';save(root/'desktop-state.json',state);return {'status':'handoff','reason':'wrong_target'}
    observed_at = datetime.now(BEIJING).isoformat(); records, pending = [], []
    for observation in value.get('records', []):
        if observation.get('author_uid') != uid or observation.get('is_original') is not True:
            continue
        try:
            rid = permalink_mid(observation.get('url') or '', uid)
            if observation.get('observed_id') and observation['observed_id'] != rid:
                raise ValueError('DOM mid与原帖链接不匹配')
            created_at = full_time(observation['raw_time'], observed_at)
            records.append({**observation, 'id': rid, 'created_at': created_at, 'selected': False})
        except ValueError as error:
            # Fingerprints only identify unresolved LOCAL observations, never platform IDs.
            key = hashlib.sha256(json.dumps(observation, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            pending.append({'observation_key': key, 'reason': str(error), 'observed_at': observed_at, 'observation': observation})
    valid_urls={r["url"] for r in records}
    unresolved = {p['observation_key']: p for p in load(root / 'pending-observations.json', []) if p["observation"].get("url") not in valid_urls}
    unresolved.update({p['observation_key']: p for p in pending})
    save(root / 'pending-observations.json', list(unresolved.values()))
    before = {r['id'] for r in load(root / 'candidates.json', [])}
    result = ingest(root, records)
    added = len({r['id'] for r in load(root / 'candidates.json', [])} - before)
    state['unchanged'] = state.get('unchanged', 0) + 1 if not added else 0
    state['failures'] = 0
    state['snapshots'].append({'observed_at': observed_at, 'observed_count': value['observed_count'],
                               'added': added, 'pending': len(pending), 'end_visible': value.get('end_visible', False)})
    save(root / 'desktop-state.json', state)
    return {'status': 'resolve_pending' if pending else 'verify_boundary' if value.get('end_visible') or state['unchanged'] >= 2 else 'ready',
            'candidate_count': result['candidate_count'], 'added': added, 'pending': len(unresolved),
            'note': '只采当前可见DOM；下一次由宿主正常滚动/选择日期，不用空页或停住证明读完十年'}


def resume_after_verification(bu, root):
    root = Path(root); config = load(root / 'desktop-collection.json')
    if not config:
        return {'status': 'setup_required'}
    result = bu.js(desktop_expression(config['uid'], config['selectors']))
    result = json.loads(result) if isinstance(result, str) else result
    if not isinstance(result, dict) or not result.get('success'):
        return {'status': 'handoff', 'reason': result.get('reason', 'invalid_snapshot') if isinstance(result, dict) else 'invalid_snapshot'}
    state = load(root / 'desktop-state.json', {'uid': config['uid'], 'snapshots': [], 'unchanged': 0})
    state.pop('blocked', None); state['failures'] = 0; state['next_allowed_at'] = time.time() + config['minimum_interval']
    save(root / 'desktop-state.json', state)
    return {'status': 'verified', 'note': '保留已采记录，核验后按节奏继续'}


def resolve_observations(root, resolved):
    """Merge normal detail-page observations; a local fingerprint never becomes a post ID."""
    root = Path(root); uid = load(root / 'project_meta.json')['target']['uid']
    pending = {p['observation_key']: p for p in load(root / 'pending-observations.json', [])}
    records, keys = [], set()
    for value in resolved:
        key, record = value['observation_key'], value['record']
        if key not in pending or key in keys or record.get('author_uid') != uid or record.get('is_original') is not True:
            raise ValueError('只能补齐待确认的同一目标原创帖')
        if permalink_mid(record['url'], uid) != record['id']:
            raise ValueError('补齐ID必须与正常原帖URL匹配，不用文本哈希')
        full_time(record['created_at'], datetime.now(BEIJING).isoformat())
        records.append(record); keys.add(key)
    result = ingest(root, records)
    save(root / 'pending-observations.json', [p for key, p in pending.items() if key not in keys])
    return {**result, 'resolved': len(keys), 'pending': len(pending) - len(keys)}


def collect_pages(bu, root, max_pages=1):
    """Compatibility name: one visible desktop snapshot, never nested mobile page requests."""
    if type(max_pages) is not int or not 1 <= max_pages <= 3:
        raise ValueError('每次只处理一个当前可见网页快照')
    return collect_snapshot(bu, root)


def page_expression(*args, **kwargs):
    raise ValueError('移动端API不再是采集入口；登录网页端后使用configure_desktop/collect_snapshot')


def configure_history(bu, root, selectors, observed_request, minimum_interval=4):
    """Register the sole supported feature=0 route after checking the normal target page.

    observed_request may be its observed request path, or this skill's trace-verified
    /ajax/statuses/mymblog?uid=<target>&page=1&feature=0&count=20 adapter. Confirm its
    first response with max_pages=1 before continuing batches; no network panel is needed.
    """
    root = Path(root)
    meta = load(root / 'project_meta.json'); uid = meta['target']['uid']
    timeline_request(uid, observed_request)
    if type(minimum_interval) not in (int, float) or not math.isfinite(minimum_interval) or minimum_interval < 4:
        raise ValueError('历史时间线保守串行，间隔至少4秒')
    value = bu.js(history_gate_expression(uid, selectors))
    value = json.loads(value) if isinstance(value, str) else value
    from user_profile import desktop_url
    if not isinstance(value, dict) or value.get('success') is not True or not desktop_url(value.get('source_url', ''), uid):
        return {'status': 'handoff', 'reason': value.get('reason', 'invalid_snapshot') if isinstance(value, dict) else 'invalid_snapshot'}
    config = {'uid': uid, 'selectors': selectors, 'observed_request': observed_request,
              'minimum_interval': minimum_interval, 'requested_range': meta['requested_range'],
              'verified_at': datetime.now(BEIJING).isoformat(), 'source_url': value['source_url']}
    prior = load(root / 'history-collection.json')
    if prior and any(prior.get(key) != config[key] for key in ('uid', 'observed_request', 'requested_range')):
        raise ValueError('已有历史断点与目标/日期/请求不符；使用独立项目，不覆盖旧采集')
    save(root / 'history-collection.json', config)
    return {'status': 'configured', 'route': 'logged_in_desktop_timeline', 'note': '逐页保留响应数据和游标；站点验证后才恢复阻挡状态'}


def _history_context(root):
    root = Path(root); config = load(root / 'history-collection.json')
    if not config: raise ValueError('先在正常登录页面观察请求并运行 configure_history')
    meta = load(root / 'project_meta.json')
    if config['uid'] != meta['target']['uid'] or config['requested_range'] != meta['requested_range']:
        raise ValueError('历史采集目标或日期范围与断点不符')
    state = load(root / 'history-state.json', {'uid': config['uid'], 'requested_range': config['requested_range'],
                                            'page': 1, 'since_id': None, 'pages': [], 'failures': 0, 'boundary_streak': 0})
    if state.get('uid') != config['uid'] or state.get('requested_range') != config['requested_range']:
        raise ValueError('历史断点目标或日期范围不符')
    timeline_request(config['uid'], config['observed_request'], state['page'], state['since_id'])
    return root, config, state


def _history_failure(root, state, reason, now, immediate=False):
    state['failures'] = state.get('failures', 0) + 1
    state['next_allowed_at'] = now + 45
    if immediate or state['failures'] >= 2: state['blocked'] = reason
    save(root / 'history-state.json', state)
    return {'status': 'handoff' if state.get('blocked') else 'verify_once', 'reason': reason,
            'page': state['page'], 'note': '保留已采数据与游标，不保存登录/错误响应正文'}


def _commit_history_page(root, config, state, envelope, now):
    """Replayable page commit: cache first, ingest second, advance cursor last."""
    checkpoint = state
    state = deepcopy(state)
    payload = _history_page_payload(root, config, envelope); rows = payload['data']['list']
    page = state['page']; path = envelope['cache_path']
    # A saved page is replayed after an interrupted ingest, without another network request.
    ordinary, all_days = [], []
    excluded = set(state.get('verified_pin_ids', [])) | {value['id'] for value in state.get('order_exceptions', [])}
    for row in rows:
        day = date_key(row['created_at']); all_days.append(day)
        author = row.get('user', {}).get('idstr') or row.get('user', {}).get('id')
        if str(author) != config['uid']:
            raise ValueError('时间线夹入其他作者，停止核验而非推断日期边界')
        if row['idstr'] not in excluded and not (row.get('isTop') or row.get('is_top') or row.get('top') or row.get('is_pinned')):
            ordinary.append((row['idstr'], timestamp(row['created_at'])))
    # The observed real first page has older posts before its newest ordinary post,
    # without a visible pin field in the trace. Retain these records and defer their
    # boundary role until normal DOM pin evidence identifies them; never invent a flag.
    if page == 1 and ordinary:
        newest_index = max(range(len(ordinary)), key=lambda i: ordinary[i][1])
        suffix = ordinary[newest_index:]
        if 0 < newest_index <= 5 and all(suffix[i][1] >= suffix[i + 1][1] for i in range(len(suffix) - 1)):
            exceptions = state.setdefault('order_exceptions', [])
            existing_exception_ids = {value['id'] for value in exceptions}
            for rid, created in ordinary[:newest_index]:
                if rid not in existing_exception_ids:
                    exceptions.append({'id': rid, 'created_at': created, 'page': page, 'reason': 'older_first_page_prefix', 'verified_as_pin': False})
                    excluded.add(rid)
            ordinary = suffix
    seen = {rid for prior in state['pages'] for rid in prior['ids']}
    new = [(rid, created) for rid, created in ordinary if rid not in seen]
    monotonic = all(ordinary[i][1] >= ordinary[i + 1][1] for i in range(len(ordinary) - 1))
    if new and state.get('oldest_ordinary_at') and new[0][1] > state['oldest_ordinary_at']:
        monotonic = False
    before = {r['id'] for r in load(root / 'candidates.json', [])}
    result = ingest(root, payload)
    added = len({r['id'] for r in load(root / 'candidates.json', [])} - before)
    summary = {'page': page, 'request_path': envelope['request_path'], 'source_url': envelope['source_url'],
               'observed_at': envelope['observed_at'], 'cache_path': path,
               'sha256': hashlib.sha256((root / path).read_bytes()).hexdigest(), 'input_since_id': state['since_id'],
               'observed_months': sorted({day[:7] for day in all_days}), 'attempt': state.get('attempt', 0),
               'excluded_from_boundary_ids': sorted(excluded & {row['idstr'] for row in rows}),
               'detail_override_ids': [row['idstr'] for row in rows if row.get('history_time_override')],
               'ids': [row['idstr'] for row in rows], 'observed_count': len(rows), 'added': added,
               'oldest': min(all_days) if all_days else None, 'newest': max(all_days) if all_days else None,
               'ordinary_oldest': ordinary[-1][1] if ordinary else None, 'ordinary_newest': ordinary[0][1] if ordinary else None,
               'chronology_verified': monotonic, 'next_since_id': payload['data'].get('since_id'),
               'platform_total': payload['data'].get('total'), 'batch': result['batch']}
    state['pages'].append(summary); state['failures'] = 0
    state['next_allowed_at'] = now + config['minimum_interval']
    if not monotonic:
        state['blocked'] = 'non_monotonic_timeline'
        state['boundary_streak'] = 0
    elif not rows:
        state['terminal'] = 'empty_page_needs_verification'
    elif not new and not (state.get('boundary_retry_active') and payload['data'].get('since_id') not in (None, '', '0')):
        state['terminal'] = 'unchanged_page_needs_verification'
    elif new:
        state['oldest_ordinary_at'] = ordinary[-1][1]
        boundary = ordinary[-1][1][:10] < config['requested_range']['start']
        # One old item, including an unrecognised pin, is never sufficient to finish.
        state['boundary_streak'] = state.get('boundary_streak', 0) + 1 if boundary else 0
        if state['boundary_streak'] >= 2:
            unresolved = any(not value.get('verified_as_pin') for value in state.get('order_exceptions', []))
            state['terminal'] = 'lower_boundary_waiting_for_order_verification' if unresolved else 'lower_boundary_confirmed'
    cursor = payload['data'].get('since_id')
    # A normal-page retry of this same request may return the cursor already seen in
    # its earlier empty/partial response; that cursor never advanced the chain.
    prior_cursors = {p['next_since_id'] for p in state['pages'][:-1]
                     if p['next_since_id'] and p['page'] != page and p['observed_count'] and p['chronology_verified']}
    if rows and cursor not in (None, '', '0') and (cursor == state['since_id'] or cursor in prior_cursors):
        state['blocked'] = 'repeated_cursor'
        if state.get('terminal') in {'lower_boundary_confirmed', 'lower_boundary_waiting_for_order_verification'}: state.pop('terminal')
    if not state.get('terminal') and not state.get('blocked'):
        if cursor in (None, '', '0'):
            state['terminal'] = 'missing_cursor_needs_verification'
    # Evidence covers only the returned accessible timeline, never hidden/deleted posts.
    _write_history_coverage(root, config, state)
    # Keep the same request when a terminal response needs a normal-page check/retry.
    if state.get('terminal', '').endswith('needs_verification'):
        state['page'] = page
    else:
        state['page'] = page + 1; state['since_id'] = cursor; state['attempt'] = 0
    state.pop('boundary_retry_active', None)
    state.pop('pending_page', None)
    save(root / 'history-state.json', state)
    checkpoint.clear(); checkpoint.update(state)
    return added


def _invalid_history_time(row):
    try:
        timestamp(row['created_at'])
    except (KeyError, ValueError, TypeError):
        return True
    return False


def _history_page_payload(root, config, envelope, observations=None):
    """Apply separately recorded detail evidence to a copy, never to cached raw JSON."""
    payload = deepcopy(envelope['payload'])
    if observations is None:
        evidence = load(root / 'history-detail-overrides.json', {'schema_version': 1, 'uid': config['uid'], 'observations': []})
        if evidence.get('uid') != config['uid'] or not isinstance(evidence.get('observations'), list):
            raise ValueError('历史详情覆盖证据与目标不符')
        observations = evidence['observations']
    path = project_file(root, envelope['cache_path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    matching = {entry['id']: entry for entry in observations
                if entry.get('cache_path') == envelope['cache_path'] and entry.get('cache_sha256') == digest}
    for row in payload['data']['list']:
        entry = matching.get(row['idstr'])
        if entry and _invalid_history_time(row):
            if entry.get('author_uid') != config['uid'] or permalink_mid(entry['source_url'], config['uid']) != row['idstr']:
                raise ValueError('详情覆盖作者或原帖链接不符')
            timestamp(entry['captured_at'])
            row['created_at'] = timestamp(entry['created_at'])
            row['history_time_override'] = {'source_url': entry['source_url'], 'captured_at': entry['captured_at'], 'reason': entry['reason']}
    return payload


def resolve_history_observations(root, observations):
    """Register 1–25 normal-detail date observations for the current malformed raw page."""
    root, config, state = _history_context(root)
    if not isinstance(observations, list) or not 1 <= len(observations) <= 25:
        raise ValueError('单次补齐1至25条正常原帖时间证据')
    if state.get('blocked') != 'invalid_page_requires_detail_verification' or not state.get('pending_page'):
        raise ValueError('只能补齐当前待重放的无效历史页，不清除其他阻挡')
    pending = state['pending_page']; path = project_file(root, pending['path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != pending['sha256']:
        raise ValueError('原始历史页校验值改变；不以详情覆盖绕过损坏缓存')
    envelope = load(path)
    request_path = timeline_request(config['uid'], config['observed_request'], state['page'], state['since_id'])
    if envelope.get('cache_path') != pending['path'] or envelope.get('request_path') != request_path:
        raise ValueError('详情证据必须绑定同一原始请求与断点页')
    raw_by_id = {}
    for row in envelope['payload']['data']['list']:
        raw_by_id.setdefault(row['idstr'], []).append(row)
    evidence_path = root / 'history-detail-overrides.json'
    evidence = load(evidence_path, {'schema_version': 1, 'uid': config['uid'], 'observations': []})
    if evidence.get('uid') != config['uid'] or not isinstance(evidence.get('observations'), list):
        raise ValueError('历史详情覆盖证据与目标不符')
    entries, seen = [], set()
    for observation in observations:
        if not isinstance(observation, dict): raise ValueError('详情证据必须是对象')
        rid = observation.get('id')
        if not isinstance(rid, str) or not rid.isdigit() or rid in seen or rid not in raw_by_id:
            raise ValueError('补齐ID须为当前原始页唯一真实mid，不造新ID')
        if observation.get('author_uid') != config['uid'] or permalink_mid(observation.get('source_url', ''), config['uid']) != rid:
            raise ValueError('详情作者、原帖永久链接和mid须与目标及原始记录一致')
        originals = raw_by_id[rid]
        if any(str(row.get('user', {}).get('idstr') or row.get('user', {}).get('id')) != config['uid'] for row in originals):
            raise ValueError('不能用时间证据更换原始记录作者')
        if any(not _invalid_history_time(row) for row in originals):
            raise ValueError('原记录已有完整时间，不以修复入口修改真实日期')
        created_at = timestamp(observation.get('created_at'))
        captured_at = timestamp(observation.get('captured_at'))
        entries.append({'id': rid, 'author_uid': config['uid'], 'source_url': observation['source_url'],
                        'created_at': created_at, 'captured_at': captured_at, 'cache_path': pending['path'],
                        'cache_sha256': digest, 'request_path': request_path,
                        'raw_created_at': originals[0].get('created_at'),
                        'reason': 'missing_created_at' if originals[0].get('created_at') is None else 'invalid_created_at'})
        seen.add(rid)
    # Existing observations remain an audit trail; a later normal observation is appended.
    combined = evidence['observations'] + entries
    repaired = _history_page_payload(root, config, envelope, combined)
    remaining = sum(_invalid_history_time(row) for row in repaired['data']['list'])
    ready = remaining == 0
    if ready:
        from archive_pipeline import normalize
        for row in repaired['data']['list']:
            if str(row.get('user', {}).get('idstr') or row.get('user', {}).get('id')) != config['uid']:
                ready = False; break
            if config['requested_range']['start'] <= date_key(row['created_at']) <= config['requested_range']['end']:
                try:
                    normalize(row, config['uid'])
                except (ValueError, KeyError, TypeError):
                    ready = False; break
    save(evidence_path, {**evidence, 'observations': combined})
    state.setdefault('detail_repairs', []).append({'registered_at': datetime.now(BEIJING).isoformat(), 'cache_path': pending['path'],
                                                  'cache_sha256': digest, 'ids': sorted(seen), 'remaining_invalid_times': remaining})
    if ready:
        state.setdefault('resolved_blocks', []).append({'reason': state['blocked'], 'resolved_at': datetime.now(BEIJING).isoformat(),
                                                       'method': 'normal_detail_time_observations', 'cache_path': pending['path']})
        state.pop('blocked'); state['failures'] = 0
    save(root / 'history-state.json', state)
    return {'status': 'replay_ready' if ready else 'resolve_pending', 'registered': len(entries),
            'remaining_invalid_times': remaining, 'page': state['page'], 'raw_sha256': digest,
            'note': '保留原始页与游标；collect_history从缓存副本重放，不重采、不改原始响应'}


def _history_complete(state):
    return state.get('terminal') in {'lower_boundary_confirmed', 'site_end_confirmed'} and not state.get('blocked')


def _write_history_coverage(root, config, state):
    covered = {c['month']: c for c in load(root / 'monthly_coverage.json', [])}
    confirmed = _history_complete(state)
    observed = {month for page in state['pages'] for month in page.get('observed_months', [])}
    for month in months(config['requested_range']['start'], config['requested_range']['end']):
        if confirmed or month in observed:
            if not confirmed and covered.get(month, {}).get('status') == 'complete': continue
            boundary_note = '正常页面可见结束标记已核验' if state.get('terminal') == 'site_end_confirmed' else '两批普通项单调跨越起始日'
            covered[month] = {'month': month, 'status': 'complete' if confirmed else 'partial',
                              'note': '正常登录 feature=0 可访问时间线，已读页 %d；%s。证据 history-state.json 和 history-pages/；不含不可访问/删除微博。' %
                              (len(state['pages']), boundary_note if confirmed else '仅已读页，未证实完整月份'),
                              'evidence': {'route': 'logged_in_desktop_timeline', 'first_page': 1, 'last_page': state['pages'][-1]['page'],
                                           'boundary_confirmed': confirmed, 'terminal': state.get('terminal')}}
    save(root / 'monthly_coverage.json', sorted(covered.values(), key=lambda c: c['month']))


def collect_history(bu, root, max_pages=3, deadline_seconds=20, clock=time.time, sleep=time.sleep):
    """Bounded serial batch with a soft deadline checked between synchronous requests.

    The host must also set its browser tool timeout: sync XHR cannot interrupt itself.
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 5:
        raise ValueError('单批1至5页；由宿主观察结果后续跑')
    if type(deadline_seconds) not in (int, float) or not math.isfinite(deadline_seconds) or not 0 < deadline_seconds <= 60:
        raise ValueError('每批明确1至60秒时间预算')
    root, config, state = _history_context(root)
    if state.get('blocked'): return {'status': 'handoff', 'reason': state['blocked'], 'page': state['page']}
    if state.get('terminal'):
        return {'status': 'complete' if _history_complete(state) else 'verify_order' if state['terminal'] == 'lower_boundary_waiting_for_order_verification' else 'verify_boundary', 'reason': state['terminal'], 'page': state['page']}
    if state.get('boundary_retry_active'): max_pages = 1
    deadline = clock() + deadline_seconds; processed = added = 0
    for _ in range(max_pages):
        now = clock(); wait = max(0, state.get('next_allowed_at', 0) - now)
        if now + wait >= deadline: break
        if wait: sleep(wait)
        if clock() >= deadline: break
        request_path = timeline_request(config['uid'], config['observed_request'], state['page'], state['since_id'])
        name = '%06d' % state['page'] + ('-attempt%02d' % state['attempt'] if state.get('attempt') else '')
        cached_path = root / ('history-pages/' + name + '.json')
        if state.get('pending_page'):
            envelope = load(cached_path)
            if envelope.get('request_path') != request_path or hashlib.sha256(cached_path.read_bytes()).hexdigest() != state['pending_page']['sha256']:
                return _history_failure(root, state, 'invalid_cached_page', clock(), True)
        else:
            try:
                raw = bu.js(timeline_expression(config['uid'], config['selectors'], request_path))
                value = json.loads(raw) if isinstance(raw, str) else raw
                payload, reason = timeline_payload(value, config['uid'], request_path)
            except Exception:
                return _history_failure(root, state, 'request_failed', clock())
            if reason:
                immediate = reason not in {'request_failed', 'HTTP 500', 'HTTP 502', 'HTTP 503', 'HTTP 504'}
                return _history_failure(root, state, reason, clock(), immediate)
            envelope = {'request_path': request_path, 'source_url': value['source_url'],
                        'observed_at': datetime.now(BEIJING).isoformat(), 'payload': payload,
                        'cache_path': cached_path.relative_to(root).as_posix()}
            save(cached_path, envelope)
            state['pending_page'] = {'path': cached_path.relative_to(root).as_posix(),
                                     'sha256': hashlib.sha256(cached_path.read_bytes()).hexdigest()}
            save(root / 'history-state.json', state)
        try:
            added += _commit_history_page(root, config, state, envelope, clock())
        except OSError:
            return _history_failure(root, state, 'cached_page_io_failure', clock())
        except (ValueError, KeyError, TypeError):
            return _history_failure(root, state, 'invalid_page_requires_detail_verification', clock(), True)
        processed += 1
        if state.get('terminal') or state.get('blocked'): break
    status = 'handoff' if state.get('blocked') else 'complete' if _history_complete(state) else 'verify_order' if state.get('terminal') == 'lower_boundary_waiting_for_order_verification' else 'verify_boundary' if state.get('terminal') else 'ready' if processed else 'cooldown'
    return {'status': status, 'reason': state.get('blocked') or state.get('terminal'), 'processed_pages': processed,
            'added': added, 'candidate_count': len(load(root / 'candidates.json', [])),
            'next_page': state['page'], 'wait_seconds': max(0, round(state.get('next_allowed_at', 0) - clock(), 2)),
            'note': '继续使用同一断点；空页/总数/单条旧置顶均不证明十年完整'}


def resume_history_after_verification(bu, root, retry_boundary=False):
    root, config, state = _history_context(root)
    value = bu.js(history_gate_expression(config['uid'], config['selectors']))
    value = json.loads(value) if isinstance(value, str) else value
    from user_profile import desktop_url
    if not isinstance(value, dict) or value.get('success') is not True or not desktop_url(value.get('source_url', ''), config['uid']):
        return {'status': 'handoff', 'reason': 'normal_page_verification_required'}
    # Login/challenge and transient failures may resume. Data/chronology corruption needs investigation.
    if state.get('blocked') in {'non_monotonic_timeline', 'repeated_cursor', 'invalid_cached_page', 'invalid_page_requires_detail_verification'}:
        return {'status': 'handoff', 'reason': state['blocked'], 'note': '页面恢复不能消除数据证据错误，先核对缓存页'}
    if state.get('terminal'):
        if _history_complete(state): return {'status': 'complete', 'reason': state['terminal']}
        if state['terminal'] == 'lower_boundary_waiting_for_order_verification':
            return {'status': 'verify_order', 'reason': state['terminal'], 'note': '用 verify_history_pins 核验正常页面上的实际置顶；不猜测旧项身份'}
        if not retry_boundary or state.get('boundary_retries', 0) >= 1:
            return {'status': 'verify_boundary', 'reason': state['terminal'], 'note': '正常页面核验后可显式 retry_boundary=True 单页复查一次，或 confirm_history_end 核验实际结束标记'}
        state['boundary_verifications'] = state.get('boundary_verifications', []) + [{'observed_at': datetime.now(BEIJING).isoformat(), 'source_url': value['source_url'], 'reason': state['terminal']}]
        state['boundary_retries'] = state.get('boundary_retries', 0) + 1
        state['attempt'] = state.get('attempt', 0) + 1
        state['boundary_retry_active'] = True
        state.pop('terminal')
    state.pop('blocked', None); state['failures'] = 0
    state['next_allowed_at'] = time.time() + config['minimum_interval']
    save(root / 'history-state.json', state)
    return {'status': 'verified', 'next_page': state['page']}


def confirm_history_end(bu, root, note):
    """Confirm an actual visible site end marker, never a count or empty response alone."""
    root, config, state = _history_context(root)
    if not isinstance(note, str) or not note.strip(): raise ValueError('记录正常页面结束标记的实际核验说明')
    if state.get('blocked') or not state.get('terminal', '').endswith('needs_verification') or not state['pages']:
        return {'status': 'handoff', 'reason': 'terminal_observation_required'}
    if any(not value.get('verified_as_pin') for value in state.get('order_exceptions', [])):
        return {'status': 'verify_order', 'reason': 'order_exceptions_need_normal_page_verification'}
    if not config['selectors'].get('end_marker'):
        return {'status': 'verify_boundary', 'reason': 'observed_end_marker_selector_required'}
    value = bu.js(history_gate_expression(config['uid'], config['selectors']))
    value = json.loads(value) if isinstance(value, str) else value
    from user_profile import desktop_url
    if not isinstance(value, dict) or value.get('success') is not True or value.get('end_visible') is not True or not desktop_url(value.get('source_url', ''), config['uid']):
        return {'status': 'verify_boundary', 'reason': 'visible_site_end_not_verified'}
    if not all(page.get('chronology_verified') for page in state['pages']):
        return {'status': 'handoff', 'reason': 'chronology_evidence_required'}
    state['terminal'] = 'site_end_confirmed'
    state['end_verification'] = {'observed_at': datetime.now(BEIJING).isoformat(), 'source_url': value['source_url'],
                                 'selector': config['selectors']['end_marker'], 'note': note}
    _write_history_coverage(root, config, state); save(root / 'history-state.json', state)
    return {'status': 'complete', 'reason': 'site_end_confirmed', 'scope': 'accessible_logged_in_timeline'}


def verify_history_pins(bu, root, selectors):
    """Resolve first-page ordering exceptions from visible, verified pinned-card DOM."""
    root, config, state = _history_context(root)
    if any(not isinstance(selectors.get(key), str) or not selectors[key].strip() for key in ('pinned_cards', 'permalink')):
        raise ValueError('正常页面核验 pinned_cards 与其 permalink 选择器，不用列表位置猜置顶')
    gate = history_gate_expression(config['uid'], config['selectors'])
    expression = """(()=>{
      const gate=JSON.parse(%s);if(!gate.success)return JSON.stringify(gate);
      const root=document.querySelector(%s),s=%s;
      const pinned_urls=[...root.querySelectorAll(s.pinned_cards)].filter(e=>e.getClientRects().length>0).slice(0,10).map(e=>e.querySelector(s.permalink)?.href).filter(Boolean);
      return JSON.stringify({...gate,pinned_urls});
    })()""" % (gate, json.dumps(config['selectors']['root']), json.dumps(selectors))
    value = bu.js(expression); value = json.loads(value) if isinstance(value, str) else value
    from user_profile import desktop_url
    if not isinstance(value, dict) or value.get('success') is not True or not desktop_url(value.get('source_url', ''), config['uid']) or not isinstance(value.get('pinned_urls'), list):
        return {'status': 'handoff', 'reason': 'normal_pin_observation_required'}
    ids = {permalink_mid(url, config['uid']) for url in value['pinned_urls']}
    state['verified_pin_ids'] = sorted(set(state.get('verified_pin_ids', [])) | ids)
    state['pin_verifications'] = state.get('pin_verifications', []) + [{'observed_at': datetime.now(BEIJING).isoformat(), 'source_url': value['source_url'], 'pinned_urls': value['pinned_urls'], 'selectors': selectors}]
    for item in state.get('order_exceptions', []):
        if item['id'] in state['verified_pin_ids']: item['verified_as_pin'] = True
    if state['pages']:
        _rebuild_history_order(root, config, state)
    unresolved = sum(not item.get('verified_as_pin') for item in state.get('order_exceptions', []))
    if state.get('terminal') == 'lower_boundary_waiting_for_order_verification' and not unresolved:
        state['terminal'] = 'lower_boundary_confirmed'
    if state['pages']: _write_history_coverage(root, config, state)
    save(root / 'history-state.json', state)
    return {'status': 'handoff' if state.get('blocked') else 'complete' if _history_complete(state) else 'verify_order' if unresolved else 'verified',
            'verified_pin_ids': state['verified_pin_ids'], 'unresolved_order_exceptions': unresolved}


def _rebuild_history_order(root, config, state):
    """Recheck cached chronology after actual pin evidence, retaining original responses."""
    excluded = set(state.get('verified_pin_ids', [])) | {value['id'] for value in state.get('order_exceptions', [])}
    seen, oldest, streak, all_ordered = set(), None, 0, True
    revised_at = datetime.now(BEIJING).isoformat()
    for page in state['pages']:
        cache_path = root / page['cache_path']
        if not cache_path.is_file() or hashlib.sha256(cache_path.read_bytes()).hexdigest() != page['sha256']:
            state['blocked'] = 'invalid_cached_page'
            return
        envelope = load(cache_path)
        ordinary = []
        for row in _history_page_payload(root, config, envelope)['data']['list']:
            if row['idstr'] not in excluded and not (row.get('isTop') or row.get('is_top') or row.get('top') or row.get('is_pinned')):
                ordinary.append((row['idstr'], timestamp(row['created_at'])))
        new = [(rid, created) for rid, created in ordinary if rid not in seen]
        ordered = all(ordinary[i][1] >= ordinary[i + 1][1] for i in range(len(ordinary) - 1))
        if new and oldest and new[0][1] > oldest: ordered = False
        old_evidence = {key: page.get(key) for key in ('chronology_verified', 'ordinary_oldest', 'ordinary_newest', 'excluded_from_boundary_ids')}
        new_evidence = {'chronology_verified': ordered,
                        'ordinary_oldest': ordinary[-1][1] if ordinary else None,
                        'ordinary_newest': ordinary[0][1] if ordinary else None,
                        'excluded_from_boundary_ids': sorted(excluded & set(page['ids']))}
        if old_evidence != new_evidence:
            page.setdefault('order_revisions', []).append({'revised_at': revised_at, 'previous': old_evidence,
                                                          'verified_pin_ids': state['verified_pin_ids']})
            page.update(new_evidence)
        all_ordered = all_ordered and ordered
        if ordered and new:
            oldest = ordinary[-1][1]
            streak = streak + 1 if oldest[:10] < config['requested_range']['start'] else 0
        elif not ordered:
            streak = 0
        seen.update(page['ids'])
    state['boundary_streak'] = streak
    if oldest: state['oldest_ordinary_at'] = oldest
    if not all_ordered:
        state['blocked'] = 'non_monotonic_timeline'
        return
    if state.get('blocked') == 'non_monotonic_timeline':
        state.setdefault('resolved_blocks', []).append({'reason': state['blocked'], 'resolved_at': revised_at,
                                                       'method': 'cached_chronology_with_observed_pin_ids'})
        state.pop('blocked'); state['failures'] = 0
        state['next_allowed_at'] = time.time() + config['minimum_interval']
    if streak >= 2 and not state.get('blocked'):
        unresolved = any(not value.get('verified_as_pin') for value in state.get('order_exceptions', []))
        state['terminal'] = 'lower_boundary_waiting_for_order_verification' if unresolved else 'lower_boundary_confirmed'


# --- m.weibo.cn page-addressable feed: bisection boundary probe + bounded collection ---

MOBILE_HALF_YEAR_KEY = "半年"


def _mobile_config(root):
    root = Path(root)
    config = load(root / 'mobile-collection.json')
    if not config:
        raise ValueError("先运行 configure_mobile 初始化移动站采集")
    uid = load(root / 'project_meta.json')['target']['uid']
    if config.get('uid') != uid:
        raise ValueError('移动站采集配置与目标UID不符')
    return root, config, uid


def configure_mobile(bu, root, minimum_interval=4):
    """Verify the m.weibo.cn target page and initialize page-addressable collection."""
    root = Path(root)
    meta = load(root / 'project_meta.json')
    uid = meta['target']['uid']
    if type(minimum_interval) not in (int, float) or minimum_interval < 4:
        raise ValueError('移动站保守串行，间隔至少4秒；不是免风控保证')
    info = bu.page_info()
    if not mobile_url(info.get('url'), uid):
        return {'status': 'setup_required', 'note': '先在已登录浏览器打开 m.weibo.cn 目标主页 /u/UID'}
    prior_config = load(root / 'mobile-collection.json')
    prior_state = load(root / 'mobile-state.json')
    if prior_config or prior_state:
        if not prior_config or not prior_state or prior_config.get('uid') != uid or prior_state.get('uid') != uid:
            raise ValueError('已有移动采集状态不完整或属于其他目标；保留原状态，在新项目中初始化')
        return {'status': 'handoff' if prior_state.get('blocked') else 'configured',
                'route': 'm_weibo_container', 'resumed': True, 'next_page': prior_state['next_page'],
                'source_url': prior_config['source_url'], 'reason': prior_state.get('blocked')}
    config = {'uid': uid, 'minimum_interval': minimum_interval,
              'verified_at': datetime.now(BEIJING).isoformat(), 'source_url': info['url']}
    state = {'uid': uid, 'next_page': 1, 'next_allowed_at': 0, 'failures': 0,
             'boundary': {'last_page': None, 'half_year_visible': None, 'notices': []}, 'pages': []}
    save(root / 'mobile-collection.json', config)
    save(root / 'mobile-state.json', state)
    return {'status': 'configured', 'route': 'm_weibo_container', 'source_url': info['url']}


def _mobile_wait(state, config, clock, sleep):
    wait = max(0, state.get('next_allowed_at', 0) - clock())
    if wait:
        sleep(wait)


def _mobile_request_page(bu, config, page):
    """Fetch one container page via same-origin sync XHR; return (mblogs, notices, path)."""
    uid = config['uid']
    request_path = mobile_container_path(uid, page)
    raw = bu.js(mobile_gate_expression(uid, request_path))
    value = json.loads(raw) if isinstance(raw, str) else raw
    mblogs, notices, reason = mobile_payload(value, uid, request_path)
    if reason:
        raise ValueError(reason)
    return mblogs, notices, request_path


def probe_mobile_boundary(bu, root, high_page=2000, deadline_seconds=60, clock=time.time, sleep=time.sleep):
    """Bisect page numbers to find the last valid page and detect half-year visibility."""
    root, config, _ = _mobile_config(root)
    state = load(root / 'mobile-state.json')
    if state.get('blocked'):
        return {'status': 'handoff', 'reason': state['blocked']}
    if type(high_page) is not int or high_page < 2:
        raise ValueError('high_page 为大于1的整数')
    if type(deadline_seconds) not in (int, float) or not 0 < deadline_seconds <= 120:
        raise ValueError('探测时间预算 1至120秒')
    deadline = clock() + deadline_seconds
    notices_all = []

    def fetch(page):
        if clock() >= deadline:
            raise TimeoutError('deadline')
        _mobile_wait(state, config, clock, sleep)
        mblogs, notices, _ = _mobile_request_page(bu, config, page)
        state['next_allowed_at'] = clock() + config['minimum_interval']
        notices_all.extend(notices)
        return mblogs, notices

    try:
        progress = state.get('boundary_probe')
        if progress and progress.get('high_page') != high_page:
            raise ValueError('边界探测上限与已有断点不同；先完成同一探测，不隐式重置')
        if not progress and not fetch(1)[0]:
            raise ValueError('page=1 无内容，先核验移动站目标页')
        if not progress and fetch(high_page)[0]:
            raise ValueError('high_page 仍有内容，请调大探测上限')
        lo, hi = (progress['lo'], progress['hi']) if progress else (1, high_page)
        notices_all.extend(progress.get('notices', []) if progress else [])
        half_year = any(MOBILE_HALF_YEAR_KEY in name for name in notices_all)
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            mblogs, notices = fetch(mid)
            if not mblogs and not notices:
                # A transient empty page must not truncate the whole history window.
                mblogs, notices = fetch(mid)
            half_year = half_year or any(MOBILE_HALF_YEAR_KEY in name for name in notices)
            lo, hi = (mid, hi) if mblogs else (lo, mid)
            state['boundary_probe'] = {'high_page': high_page, 'lo': lo, 'hi': hi, 'notices': notices_all}
            save(root / 'mobile-state.json', state)
        last_page = lo
    except TimeoutError:
        save(root / 'mobile-state.json', state)
        return {'status': 'cooldown', 'note': '探测时间预算用尽，可再次调用继续',
                'probed_last': state['boundary'].get('last_page')}
    except ValueError as exc:
        state['failures'] = state.get('failures', 0) + 1
        state['next_allowed_at'] = clock() + config['minimum_interval']
        state['blocked'] = str(exc)
        save(root / 'mobile-state.json', state)
        return {'status': 'handoff', 'reason': str(exc)}

    state['boundary'] = {'last_page': last_page, 'half_year_visible': half_year,
                         'notices': sorted(set(notices_all))}
    state['failures'] = 0
    state.pop('boundary_probe', None)
    save(root / 'mobile-state.json', state)
    return {'status': 'boundary_found', 'last_page': last_page,
            'half_year_visible': half_year, 'notices': state['boundary']['notices']}


def collect_mobile(bu, root, max_pages=5, deadline_seconds=60, clock=time.time, sleep=time.sleep):
    """Bounded serial collection from next_page; page needs no cursor chain."""
    root, config, _ = _mobile_config(root)
    state = load(root / 'mobile-state.json')
    if state.get('blocked'):
        return {'status': 'handoff', 'reason': state['blocked']}
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError('单批1至10页')
    if type(deadline_seconds) not in (int, float) or not 0 < deadline_seconds <= 120:
        raise ValueError('每批时间预算1至120秒')
    last_page = (state.get('boundary') or {}).get('last_page')
    deadline = clock() + deadline_seconds
    processed = added = 0
    reached_end = False

    for _ in range(max_pages):
        page = state['next_page']
        if last_page and page > last_page:
            reached_end = True
            break
        if clock() >= deadline:
            break
        _mobile_wait(state, config, clock, sleep)
        try:
            mblogs, notices, request_path = _mobile_request_page(bu, config, page)
        except ValueError as exc:
            state['failures'] = state.get('failures', 0) + 1
            state['next_allowed_at'] = clock() + 45
            if state['failures'] >= 2:
                state['blocked'] = str(exc)
            save(root / 'mobile-state.json', state)
            return {'status': 'handoff' if state.get('blocked') else 'verify_once',
                    'reason': str(exc), 'page': page}
        state['next_allowed_at'] = clock() + config['minimum_interval']
        state['failures'] = 0
        cache_path = root / ('mobile-pages/%06d.json' % page)
        data = {'cards': [{'card_type': 9, 'mblog': m} for m in mblogs]}
        save(cache_path, {'request_path': request_path, 'source_url': config['source_url'],
                          'observed_at': datetime.now(BEIJING).isoformat(), **data})
        before = len(load(root / 'candidates.json', []))
        result = ingest(root, data)
        added += result['candidate_count'] - before
        days = [date_key(m['created_at']) for m in mblogs]
        state['pages'].append({'page': page, 'cache_path': cache_path.relative_to(root).as_posix(),
                               'observed_count': len(mblogs), 'notices': notices,
                               'oldest': min(days) if days else None,
                               'newest': max(days) if days else None})
        state['next_page'] = page + 1
        processed += 1
        if notices:
            reached_end = True
            break

    save(root / 'mobile-state.json', state)
    if state.get('blocked'):
        status = 'handoff'
    elif reached_end or (last_page and state['next_page'] > last_page):
        status = 'complete'
    elif not processed:
        status = 'cooldown'
    else:
        status = 'ready'
    return {'status': status, 'processed_pages': processed, 'added': added,
            'candidate_count': len(load(root / 'candidates.json', [])),
            'next_page': state['next_page'], 'boundary': state.get('boundary'),
            'wait_seconds': max(0, round(state.get('next_allowed_at', 0) - clock(), 2))}
