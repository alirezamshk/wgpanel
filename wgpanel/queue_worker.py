import threading
import queue
import logging
import time
import mikrotik

log = logging.getLogger('worker')

_q = queue.Queue()

def enqueue(task_type, **kwargs):
    _q.put({'type': task_type, **kwargs})

def _process(task):
    t = task['type']
    try:
        if t == 'update_peer':
            mt_id = task['mt_id']
            if not mt_id:
                return
            params = {}
            if 'comment' in task: params['comment'] = task['comment']
            if params:
                mikrotik.update_peer(mt_id, **params)

        elif t == 'disable_peer':
            mikrotik.disable_peer(task['mt_id'])

        elif t == 'enable_peer':
            mikrotik.enable_peer(task['mt_id'])

        elif t == 'delete_peer':
            mikrotik.remove_peer(task['mt_id'])

        elif t == 'add_peer':
            pass  # این sync میمونه چون pub key لازمه

        log.info(f"[worker] OK: {t} mt_id={task.get('mt_id','?')}")

    except Exception as e:
        log.error(f"[worker] FAIL: {t} — {e}")
        # retry یه بار
        retry = task.get('_retry', 0)
        if retry < 2:
            task['_retry'] = retry + 1
            time.sleep(5)
            _q.put(task)
            log.info(f"[worker] Retry {retry+1} for {t}")

def _worker_loop():
    log.info("[worker] Background queue started")
    while True:
        try:
            task = _q.get(timeout=5)
            _process(task)
            _q.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            log.error(f"[worker] Unexpected error: {e}")

def start():
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()
