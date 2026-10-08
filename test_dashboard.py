"""Synthetic browser-independent tests of the dashboard record calculations."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import os

HTML = (Path(__file__).parent / 'dashboard.html').read_text(encoding='utf-8')
NODE = shutil.which('node')
if not NODE:
    candidate = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    if candidate.exists():
        NODE = str(candidate)


class DashboardTests(unittest.TestCase):
    def test_style_options_keep_existing_navigation_and_use_local_fonts(self):
        for style in ('glass','clean','instrument','paper','midnight'):
            self.assertIn('value="'+style+'"',HTML)
        self.assertIn("ui_style:$('uiStyle').value",HTML)
        self.assertIn("applyStyle(c.ui_style||'glass')",HTML)
        self.assertNotIn('@font-face',HTML)
        self.assertNotIn('fonts.googleapis',HTML)
        self.assertIn('font-variant-numeric:tabular-nums',HTML)
        self.assertIn("localStorage.setItem('adapter-ui-style',style)",HTML)
        self.assertIn("localStorage.setItem('adapter-theme',value)",HTML)
        self.assertIn('applyTheme(initialTheme)',HTML)
    def test_every_style_declares_palette_option_and_hint_without_hardcoded_accents(self):
        select=HTML.split('<select id="uiStyle">')[1].split('</select>')[0]
        styles=re.findall(r'<option value="(\w+)">',select)
        self.assertEqual(styles, ['glass','clean','instrument','paper','midnight'])
        descriptions=HTML.split('const styleDescriptions={')[1].split('};')[0]
        # glass keeps the base :root palette; every other style declares its own block and hint.
        self.assertIn(':root{--bg:#f5f5f7',HTML)
        self.assertIn('glass:',descriptions)
        for style in styles[1:]:
            self.assertIn(':root[data-style='+style+']{',HTML)
            self.assertIn(style+':',descriptions)
        self.assertNotIn('background:#286ac5',HTML)
        self.assertNotIn('color:#bf7a00',HTML)
    def calculate(self, expression):
        if not NODE:
            self.skipTest('Node.js is needed to validate dashboard calculations')
        logic = HTML.split('// BEGIN RECORD LOGIC')[1].split('// END RECORD LOGIC')[0]
        result = subprocess.run([NODE, '-e', logic + '\nconsole.log(JSON.stringify(' + expression + '));'],
                                capture_output=True, text=True, encoding='utf-8', check=True,
                                env={**os.environ, 'TZ': 'Asia/Shanghai'})
        return json.loads(result.stdout)

    def settings_script(self, script):
        if not NODE:
            self.skipTest('Node.js is needed to validate dashboard settings')
        functions = '\n'.join(re.findall(
            r'^function (?:applyTheme|period|fillSettings|setConnectionControlsEnabled)\(.*$',
            HTML, re.MULTILINE))
        harness = """
const elements={};
const $=id=>elements[id]||(elements[id]={options:[],value:'',checked:false,disabled:false,
    appendChild(option){this.options.push(option)}});
const document={documentElement:{dataset:{}},createElement:()=>({dataset:{}})};
const localStorage={setItem(key,value){this[key]=value}};
let systemDark=true,selectedTheme='system';
const matchMedia=()=>({matches:systemDark});
const window={adapterSettingsDirty:true};
const fmt=n=>Number(n||0).toLocaleString('zh-CN');
const text=()=>{},applyStyle=()=>{};
"""
        result = subprocess.run([NODE, '-e', harness + functions + '\n' + script],
                                capture_output=True, text=True, encoding='utf-8', check=True)
        return json.loads(result.stdout)

    def test_restored_theme_matches_select_and_system_changes(self):
        result = self.settings_script("""
applyTheme('dark');const restored=$('theme').value;
applyTheme('invalid');const fallback=selectedTheme;
systemDark=false;applyTheme(selectedTheme);
console.log(JSON.stringify([restored,fallback,$('theme').value,
    document.documentElement.dataset.theme,localStorage['adapter-theme']]));
""")
        self.assertEqual(result, ['dark', 'system', 'system', 'light', 'system'])

    def test_browser_connection_controls_require_ready_bridge(self):
        result = self.settings_script("""
setConnectionControlsEnabled(false);
const ids=['server','secret','downloadPeriod','uploadPeriod','connectClient','autostart','saveSettings'];
const disabled=ids.every(id=>$(id).disabled);
const previewEnabled=!$('theme').disabled&&!$('uiStyle').disabled;
setConnectionControlsEnabled(true);
console.log(JSON.stringify([disabled,previewEnabled,ids.every(id=>!$(id).disabled)]));
""")
        self.assertEqual(result, [True, True, True])

    def test_client_connection_is_initial_setup_action_and_legacy_period_is_accurate(self):
        result = self.settings_script("""
const config={upstream:'',interval_seconds:7200,upload_interval_ms:5400000};
fillSettings(config);const initial=$('connectClient').checked;
$('connectClient').checked=true;
fillSettings({...config,upstream:'https://example.invalid'});
console.log(JSON.stringify([initial,$('connectClient').checked,
    $('downloadPeriod').options[0].textContent,$('uploadPeriod').options[0].textContent,
    window.adapterSettingsDirty]));
""")
        self.assertEqual(result, [True, False, '120 分钟（原配置）', '90 分钟（原配置）', False])

    def test_recent_includes_today_and_29_previous_days(self):
        result = self.calculate("recordBounds('recent','','',new Date(2026,9,8,23,59))")
        self.assertEqual((result['start'], result['end']), ('2026-09-09', '2026-10-08'))

    def test_previous_month_year_and_leap_boundaries(self):
        result = self.calculate("recordBounds('previous','','',new Date(2024,2,1))")
        self.assertEqual((result['start'], result['end']), ('2024-02-01', '2024-02-29'))
        result = self.calculate("recordBounds('previous','','',new Date(2026,0,8))")
        self.assertEqual((result['start'], result['end']), ('2025-12-01', '2025-12-31'))

    def test_custom_inclusive_and_invalid(self):
        result = self.calculate("selectRecords([{date:'2026-10-07'},{date:'2026-10-08'},{date:'2026-10-09'}],recordBounds('custom','2026-10-07','2026-10-08'))")
        self.assertEqual([r['date'] for r in result['rows']], ['2026-10-08', '2026-10-07'])
        self.assertIn('error', self.calculate("recordBounds('custom','2026-10-09','2026-10-08')"))

    def test_hundreds_of_days_sorted_and_page_preserved(self):
        result = self.calculate("selectRecords(Array.from({length:400},(_,i)=>({date:dayKey(new Date(2025,0,i+1))})),recordBounds('all'),7)")
        self.assertEqual((result['count'], result['page'], result['pages'], len(result['rows'])), (400, 7, 14, 30))
        self.assertGreater(result['rows'][0]['date'], result['rows'][-1]['date'])

    def test_empty_and_page_clamping(self):
        result = self.calculate("selectRecords([],recordBounds('all'),20)")
        self.assertEqual((result['count'], result['page'], result['pages']), (0, 1, 1))

    def test_traffic_sum_uses_recorded_body_bytes(self):
        self.assertEqual(self.calculate('trafficTotals([{upload_body_bytes:20,download_body_bytes:30},{upload_body_bytes:5,download_body_bytes:7}])'), {'upload':25,'download':37})

    def test_decimal_traffic_units_and_aligned_overview_totals(self):
        if not NODE:
            self.skipTest('Node.js is needed to validate dashboard calculations')
        function = re.search(r'^function bytes\(.*$', HTML, re.MULTILINE).group()
        result = subprocess.run([NODE, '-e', function + '\nconsole.log(JSON.stringify([999,1000,1000000,1000000000].map(bytes)));'],
                                capture_output=True, text=True, encoding='utf-8', check=True)
        self.assertEqual(json.loads(result.stdout), ['999 B', '1.00 KB', '1.00 MB', '1.00 GB'])
        self.assertLess(HTML.index('<strong>今日流量'), HTML.index('<strong>累计流量'))
        self.assertEqual(HTML.count('class="metrics today-metrics flow-metrics"'), 2)
        self.assertIn('id="trafficTotal"', HTML)
        self.assertNotIn('id="upbar"', HTML)
        self.assertNotIn('id="downbar"', HTML)
        self.assertIn('id="pendingModelRows"', HTML)

    def test_history_sum_and_missing_fields(self):
        result = self.calculate('historyTotals([{upload:{requests:3,successes:2,failures:1},download:{requests:4,successes:3,failures:1}},{upload:{requests:1}}])')
        self.assertEqual(result['upload'], {'requests':4,'successes':2,'failures':1})
        self.assertEqual(result['download']['requests'], 4)

    def test_local_day_changes_at_midnight(self):
        self.assertEqual(self.calculate("[dayKey(new Date('2026-10-08T15:59:59Z')),dayKey(new Date('2026-10-08T16:00:00Z'))]"), ['2026-10-08','2026-10-09'])

    def test_page_structure_and_no_new_remote_requests(self):
        ids = re.findall(r'\bid="([^"]+)"', HTML)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(HTML.index('<nav class="tabs"'), HTML.index('</main>'))
        traffic = HTML.split('<section id="trafficPage"')[1].split('</section>')[0]
        settings = HTML.split('<section id="settingsPage"')[1].split('</section>')[0]
        overview = HTML.split('<div id="overview"')[1].split('<section id="trafficPage"')[0]
        self.assertIn('接口流量明细', traffic)
        self.assertIn('同步与计量说明', settings)
        self.assertIn('原始诊断数据', settings)
        self.assertIn('id="lasterror"', overview)
        self.assertNotIn('原始诊断数据', overview)
        self.assertEqual(re.findall(r"fetch\('([^']+)'", HTML), ['/adapter/status', '/adapter/refresh'])
        self.assertIn('state.page=result.page', HTML)
        self.assertIn('viewport.scrollTop=pageScroll[page]', HTML)


if __name__ == '__main__':
    unittest.main()
