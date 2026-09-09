"""Real-browser, real-OS-clipboard integration checks; no Clipboard API mocks."""
import os, subprocess, time, json, pathlib, sys
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FS
from selenium.webdriver.chrome.service import Service as CS
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

os.environ['DISPLAY'] = ':99'
OUT = pathlib.Path('/opt/test/results')

def clip(display, value=None):
    env = dict(os.environ, DISPLAY=display)
    if value is not None:
        p = subprocess.Popen(['xclip', '-selection', 'clipboard', '-in'], env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.stdin.write(value.encode()); p.stdin.close(); p.wait(timeout=3)
        return
    return subprocess.run(['xclip', '-selection', 'clipboard', '-out'], env=env, capture_output=True, timeout=3).stdout.decode()

def text():
    return json.loads((OUT / 'clipboard-app.json').read_text())['text']

def inserted(value):
    state = json.loads((OUT / 'clipboard-app.json').read_text())
    return state['text'][:state['cursor']] + value + state['text'][state['cursor']:]

failed = False
for kind, grant in [('firefox', False), ('chrome', True), ('chrome', False)]:
    if os.environ.get('ONLY') and os.environ['ONLY'] != kind + str(grant): continue
    if kind == 'firefox':
        opt = webdriver.FirefoxOptions(); opt.binary_location = '/opt/test/firefox/firefox'
        d = webdriver.Firefox(options=opt, service=FS('/opt/test/geckodriver'))
    else:
        opt = webdriver.ChromeOptions(); opt.binary_location = '/usr/bin/google-chrome'; opt.add_argument('--no-sandbox')
        d = webdriver.Chrome(options=opt, service=CS('/opt/test/chromedriver-linux64/chromedriver'))
    result = {'browser': kind, 'version': d.capabilities['browserVersion'], 'granted': grant, 'checks': {}}
    checks = result['checks']
    def check(name, actual, expected):
        checks[name] = {'pass': actual == expected, 'actual': actual, 'expected': expected}
        print(kind, grant, name, actual == expected, repr(actual)[:160], flush=True)
    def chord(*keys):
        a = ActionChains(d)
        for k in keys[:-1]: a.key_down(k)
        a.send_keys(keys[-1])
        for k in reversed(keys[:-1]): a.key_up(k)
        a.perform(); time.sleep(.4)
    def view_only(value):
        # Import in the page realm. Firefox's WebDriver sandbox can otherwise
        # instantiate a separate UI module, which has no connected RFB object.
        result = d.execute_async_script('''
            const value = arguments[0], done = arguments[1];
            window.addEventListener('clipboard-probe-view-only', e => done(e.detail), {once:true});
            const script = document.createElement('script');
            script.type = 'module';
            script.textContent = `import UI from './app/ui.js';
                try { UI.rfb.viewOnly = ${value};
                    window.dispatchEvent(new CustomEvent('clipboard-probe-view-only', {detail:'ok'}));
                } catch(e) { window.dispatchEvent(new CustomEvent('clipboard-probe-view-only', {detail:String(e)})); }`;
            document.head.appendChild(script);
        ''', value)
        if result != 'ok': raise RuntimeError(result)
    try:
        if grant:
            for origin in ['http://localhost:8090', 'http://localhost:6083']:
                d.execute_cdp_cmd('Browser.grantPermissions', {'origin': origin, 'permissions': ['clipboardReadWrite', 'clipboardSanitizedWrite']})
        d.set_window_size(1200, 850)
        d.get('http://localhost:8090/novnc-embedded.html')
        d.switch_to.frame(d.find_element(By.TAG_NAME, 'iframe'))
        c = WebDriverWait(d, 20).until(lambda x: next((c for c in x.find_elements(By.TAG_NAME, 'canvas') if c.size['width'] > 300), False))
        time.sleep(2); c.click()
        # Use a known remote clipboard to catch stale first-paste ordering.
        for name, keys in [('ctrl_v', (Keys.CONTROL, 'v')), ('ctrl_shift_v', (Keys.CONTROL, Keys.SHIFT, 'v'))]:
            clip(':101', 'STALE-REMOTE'); time.sleep(.4)
            value = name + '-λ✓\nsecond line'
            clip(':99', value)
            expected = inserted(value)
            chord(*keys)
            check(name + '_remote_clipboard', clip(':101'), value)
            check(name + '_app_insertion', text(), expected)
            expected = inserted('z'); ActionChains(d).send_keys('z').perform(); time.sleep(.3)
            check(name + '_no_stuck_modifiers', text(), expected)
            check(name + '_canvas_focus', d.execute_script('return document.activeElement.tagName'), 'CANVAS')
        # Select and copy using the remote application's real keyboard handler.
        chord(Keys.CONTROL, 'a'); chord(Keys.CONTROL, 'c'); time.sleep(.5)
        check('remote_app_copy_to_local', clip(':99'), text())
        time.sleep(7); clip(':101', 'IDLE-REMOTE-λ✓'); time.sleep(.5)
        if grant: check('remote_idle_automatic', clip(':99'), 'IDLE-REMOTE-λ✓')
        c.click(); time.sleep(.5)
        check('remote_idle_click_retry', clip(':99'), 'IDLE-REMOTE-λ✓')
        # A pending write must not overwrite the local clipboard as paste starts.
        time.sleep(7); clip(':101', 'PENDING-OLD'); time.sleep(.5)
        clip(':99', 'FRESH-LOCAL'); expected = inserted('FRESH-LOCAL'); chord(Keys.CONTROL, 'v')
        check('pending_write_does_not_clobber_paste', clip(':99'), 'FRESH-LOCAL')
        check('pending_write_pastes_fresh_text', text(), expected)
        # Switching out to copy locally must cancel an old remote click retry.
        time.sleep(7); clip(':101', 'PENDING-BEFORE-BLUR'); time.sleep(.4)
        d.switch_to.default_content(); d.find_element(By.ID, 'outside').click()
        clip(':99', 'COPIED-ELSEWHERE')
        d.switch_to.frame(d.find_element(By.TAG_NAME, 'iframe')); c.click(); time.sleep(.5)
        check('refocus_does_not_clobber_local', clip(':99'), 'COPIED-ELSEWHERE')
        if grant: check('chrome_focus_sync_retained', clip(':101'), 'COPIED-ELSEWHERE')
        check('manual_panel_available', d.execute_script('return document.getElementById("noVNC_clipboard_button").classList.contains("noVNC_hidden")'), False)
        # Exercise actual RFB view-only gating, not a mocked clipboard API.
        view_only(True)
        clip(':101', 'VIEW-ONLY-REMOTE'); clip(':99', 'VIEW-ONLY-LOCAL'); time.sleep(.5)
        c.click(); chord(Keys.CONTROL, 'v')
        check('view_only_no_local_read', clip(':101'), 'VIEW-ONLY-REMOTE')
        check('view_only_no_local_write', clip(':99'), 'VIEW-ONLY-LOCAL')
        view_only(False)
        c.click(); clip(':99', 'AFTER-VIEW-ONLY'); chord(Keys.CONTROL, 'v')
        check('clipboard_restored_after_view_only', clip(':101'), 'AFTER-VIEW-ONLY')
    except Exception as e:
        result['error'] = str(e)
    finally:
        label = 'fallback-' + kind + ('-granted' if grant else '-default')
        (OUT / (label + '.json')).write_text(json.dumps(result, indent=2, ensure_ascii=False))
        d.save_screenshot(str(OUT / (label + '.png')))
        d.quit()
        failed |= 'error' in result or any(not item['pass'] for item in checks.values())

sys.exit(1 if failed else 0)
