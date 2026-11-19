"""Two-player keyboard duel with confirmed UNO Q LED cues or PC practice."""
import random
import time
import queue
import threading
import tkinter as tk
import json
from pathlib import Path
from string import ascii_lowercase, digits
from board_link import BoardLink
from discovery import discover, last_host, remember
from sound_effects import SoundEffects

KEY_SETTINGS = Path(__file__).resolve().parent / '.local' / 'keys.json'
PLAYER_KEYS = set(ascii_lowercase + digits)
DEFAULT_MATCH_ROUNDS = 5
MAX_MATCH_ROUNDS = 99


def load_keys():
    try:
        keys = json.loads(KEY_SETTINGS.read_text(encoding='utf-8'))
        if (isinstance(keys, list) and len(keys) == 2 and
                all(isinstance(key, str) and key in PLAYER_KEYS for key in keys) and keys[0] != keys[1]):
            return keys
    except (OSError, ValueError):
        pass
    return ['a', 'l']


class Duel:
    def __init__(self, clock=time.perf_counter, rng=None):
        self.clock = clock
        self.rng = rng or random.Random()
        self.reset()

    def reset(self):
        self.scores = [0, 0]
        self.state = 'ready'
        self.round = 0
        self.match_rounds = DEFAULT_MATCH_ROUNDS
        self.match_winner = None
        self.winner = None
        self.reason = ''
        self.reactions = [None, None]
        self.rule = 'classic'
        self.allow_press = True
        self.uncertainty_ms = 0
        self.practice = False
        self.practice_deadline = None
        self.stats = [{'times': [], 'false_starts': 0, 'wrong_colors': 0} for _ in range(2)]
        if not hasattr(self, 'match_wins'):
            self.match_wins = [0, 0]
            self.matches = 0

    def begin_practice(self):
        self.reset()
        self.practice = True
        self.practice_deadline = self.clock() + 30

    def end_practice(self):
        if self.practice and self.state != 'practice_done':
            self.state = 'practice_done'
            self.reason = 'time_up'

    def start(self, rule='classic'):
        if self.state not in ('ready', 'result'):
            return False
        if self.practice and self.clock() >= self.practice_deadline:
            self.end_practice()
            return False
        if rule not in ('classic', 'green', 'red'):
            raise ValueError('Unknown rule')
        self.rule = rule
        self.allow_press = True if rule == 'classic' else self.rng.choice([True, False])
        self.uncertainty_ms = 0
        self.round += 1
        self.state = 'waiting'
        self.due = self.clock() + self.rng.uniform(2, 5)
        self.winner = None
        self.reason = ''
        self.reactions = [None, None]
        return True

    @property
    def cue_code(self):
        if self.rule == 'red':
            return 4 if self.allow_press else 6
        return 2 if self.allow_press else 3

    def show_go(self, timestamp=None, uncertainty_ms=0):
        if self.state in ('waiting', 'cue'):
            self.go_time = self.clock() if timestamp is None else timestamp
            self.uncertainty_ms = uncertainty_ms
            self.state = 'go' if self.allow_press else 'hold'

    def press(self, player):
        if self.state == 'cue':
            self.cancel()
            self.reason = 'ambiguous'
        elif self.state == 'waiting':
            self.stats[player]['false_starts'] += 1
            self.finish(1 - player, 'false_start')
        elif self.state == 'hold':
            elapsed = self.clock() - self.go_time
            if elapsed >= 2:
                self.timeout()
                return
            self.reactions[player] = max(0, elapsed * 1000)
            self.stats[player]['wrong_colors'] += 1
            self.finish(1 - player, 'wrong_color')
        elif self.state == 'go':
            elapsed = self.clock() - self.go_time
            if elapsed >= 5:
                self.timeout()
                return
            self.reactions[player] = elapsed * 1000
            self.stats[player]['times'].append(self.reactions[player])
            self.finish(player, 'reaction')
        elif self.state in ('result', 'match') and self.reason == 'reaction':
            elapsed = self.clock() - self.go_time
            if self.reactions[player] is None and elapsed < 5:
                self.reactions[player] = elapsed * 1000
                self.stats[player]['times'].append(self.reactions[player])

    def finish(self, winner, reason):
        self.winner, self.reason = winner, reason
        self.state = 'result'
        if self.practice:
            return
        self.scores[winner] += 1
        if sum(self.scores) == self.match_rounds:
            self.state = 'match'
            self.matches += 1
            left, right = self.scores
            if left != right:
                self.match_winner = 0 if left > right else 1
                self.match_wins[self.match_winner] += 1

    def timeout(self):
        if self.state in ('go', 'hold'):
            self.reason = 'timeout' if self.state == 'go' else 'held'
            self.state = 'result'
            if not self.practice:
                self.round -= 1

    def cancel(self):
        if self.state in ('arming', 'waiting', 'cue', 'go', 'hold'):
            self.round -= 1
            self.state, self.reason = 'result', 'cancelled'


class Window:
    BG = '#0b1120'

    def __init__(self, root):
        self.root, self.game, self.link = root, Duel(), BoardLink()
        self.sounds = SoundEffects()
        self.sound_enabled = tk.BooleanVar(value=True)
        self.sound_signature = None
        self.discovery_results = queue.Queue()
        self.searching = False
        self.mode = tk.StringVar(value='board')
        self.round_mode = 'board'
        self.rule = tk.StringVar(value='classic')
        self.session = tk.StringVar(value='match')
        self.cue_token = None
        self.held = set()
        self.keys = load_keys()
        self.edit_player = None
        self.last_signal = None
        root.title('閃電對決 · UNO Q')
        root.geometry('1060x900')
        root.minsize(900, 860)
        root.configure(bg=self.BG)
        top = tk.Frame(root, bg=self.BG)
        top.pack(fill='x', padx=30, pady=(12, 0))
        tk.Checkbutton(top, text='音效', variable=self.sound_enabled, command=self.toggle_sound,
                       bg=self.BG, fg='white', activebackground=self.BG, activeforeground='white',
                       selectcolor='#244569', font=('Microsoft JhengHei', 11)).pack(side='left')
        self.label(root, '閃電對決', 30, '#eef4ff').pack()
        self.label(root, '看燈號搶按', 12, '#a7b6ce').pack(pady=(0, 8))
        sessions = tk.Frame(root, bg=self.BG)
        sessions.pack(pady=3)
        self.session_buttons = []
        for value, label in [('match', '正式比賽'), ('practice', '30 秒練習 · 不計分')]:
            button = tk.Radiobutton(sessions, text=label, value=value, variable=self.session,
                                    bg=self.BG, fg='white', selectcolor='#244569', font=('Microsoft JhengHei', 12))
            button.pack(side='left', padx=8)
            self.session_buttons.append(button)
        self.label(sessions, '比賽局數（1–99）', 11).pack(side='left', padx=(12, 5))
        self.rounds_entry = tk.Entry(sessions, width=5, justify='center', font=('Consolas', 12))
        self.rounds_entry.insert(0, str(DEFAULT_MATCH_ROUNDS))
        self.rounds_entry.pack(side='left')
        self.rounds_entry.bind('<Return>', lambda _: self.start())
        modes = tk.Frame(root, bg=self.BG)
        modes.pack(pady=5)
        self.mode_buttons = []
        for value, text in [('board', 'UNO Q 燈號'), ('visual', 'PC 綠燈（離線練習）')]:
            button = tk.Radiobutton(modes, text=text, value=value, variable=self.mode,
                                    bg=self.BG, fg='white', selectcolor='#244569', font=('Microsoft JhengHei', 12))
            button.pack(side='left', padx=8)
            self.mode_buttons.append(button)
        rules = tk.Frame(root, bg=self.BG)
        rules.pack(pady=5)
        self.rule_buttons = []
        for value, text in [('classic', '經典搶快'), ('green', '綠燈按・紅燈停'), ('red', '紅燈按・綠燈停')]:
            button = tk.Radiobutton(rules, text=text, value=value, variable=self.rule,
                                    bg=self.BG, fg='white', selectcolor='#244569', font=('Microsoft JhengHei', 12))
            button.pack(side='left', padx=8)
            self.rule_buttons.append(button)
        players = tk.Frame(root, bg=self.BG)
        players.pack(fill='x', padx=30)
        self.cards, self.times, self.key_buttons = [], [], []
        for i, color in enumerate(('#58c7ff', '#ffae73')):
            box = tk.Frame(players, bg='#142139', padx=25, pady=12)
            box.pack(side='left', expand=True, fill='both', padx=8)
            self.label(box, f'玩家 {i+1}', 16, color, '#142139').pack()
            binding = self.button(box, f'按鍵 {self.keys[i].upper()} · 更改', lambda player=i: self.edit_key(player))
            binding.pack(pady=(4, 0))
            self.key_buttons.append(binding)
            score = self.label(box, '0', 28, color, '#142139')
            score.pack()
            timing = self.label(box, '等待出手', 13, '#a7b6ce', '#142139')
            timing.pack()
            self.cards.append(score)
            self.times.append(timing)
        self.stage = tk.Label(root, text='準備對決', font=('Microsoft JhengHei', 42, 'bold'),
                              bg='#172641', fg='white', pady=28)
        self.stage.pack(fill='x', padx=38, pady=(20, 10))
        self.detail = self.label(root, self.key_hint(), 16)
        self.detail.pack()
        self.info = self.label(root, '放開按鍵，按空白鍵開始', 12, '#a7b6ce')
        self.info.pack(pady=8)
        controls = tk.Frame(root, bg=self.BG)
        controls.pack(pady=6)
        self.next_button = self.button(controls, '開始 / 下一回合  [Space]', self.start)
        self.next_button.pack(side='left', padx=6)
        self.button(controls, '重新比賽', self.reset).pack(side='left', padx=6)
        self.history = self.label(root, '偷跑對手得分 · 5 秒無人按鍵則重賽', 11, '#a7b6ce')
        self.history.pack(pady=8)
        self.statistics = self.label(root, '統計：完成比賽或練習後顯示', 11, '#b8d5ed')
        self.statistics.pack(pady=4)
        network = tk.Frame(root, bg=self.BG)
        network.pack(pady=6)
        self.sync_button = self.button(network, '一鍵連線 UNO Q', self.connect)
        self.sync_button.pack(side='left')
        self.manual_button = self.button(network, '手動 IP（備用）', self.show_manual)
        self.manual_button.pack(side='left', padx=8)
        self.manual_frame = tk.Frame(root, bg=self.BG)
        self.label(self.manual_frame, 'IP（不用輸入 port）', 10).pack(side='left')
        self.host = tk.Entry(self.manual_frame, width=25, font=('Consolas', 12))
        self.host.insert(0, last_host().split(':')[0])
        self.host.pack(side='left', padx=8)
        self.network = self.label(root, self.link.status, 10, '#7e94b8')
        self.network.pack()
        self.label(root, '英文輸入法 · F11 全螢幕 · Esc 離開全螢幕 · 切離視窗取消該回合', 10, '#7e94b8').pack(pady=8)
        root.bind('<KeyPress>', self.key_down)
        root.bind('<KeyRelease>', self.key_up)
        root.bind('<FocusOut>', lambda _: root.after_idle(self.focus_check))
        root.bind('<F11>', lambda _: root.attributes('-fullscreen', not root.attributes('-fullscreen')))
        root.bind('<Escape>', lambda _: root.attributes('-fullscreen', False))
        root.after(8, self.tick)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def close(self):
        self.link.send(self.host.get(), 5, self.game.scores)
        self.sounds.close()
        self.root.destroy()

    def toggle_sound(self):
        self.sounds.enabled = self.sound_enabled.get()
        if not self.sounds.enabled:
            self.sounds.stop()

    def show_manual(self):
        if self.manual_frame.winfo_manager():
            self.manual_frame.pack_forget()
        else:
            self.manual_frame.pack(before=self.network, pady=4)

    def connect(self):
        if self.searching or self.game.state in ('arming', 'waiting', 'cue', 'go', 'hold'):
            return
        self.searching = True
        self.link.status = '正在尋找 UNO Q…請確認 App Lab 已執行 Reaction Duel v7'
        self.sync_button.config(state='disabled')
        preferred = self.host.get().strip()
        def work():
            try:
                self.discovery_results.put((discover(preferred), ''))
            except Exception as exc:
                self.discovery_results.put(([], str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def select_board(self, item):
        address = item['host'].split(':')[0]
        self.host.config(state='normal')
        self.host.delete(0, 'end')
        self.host.insert(0, address)
        try:
            remember(item['host'])
        except OSError:
            pass
        self.link.status = f'已找到 UNO Q：{address}'
        self.signal(True)
        self.info.config(text=f'已找到 {address}，正在同步比分；完成後按空白鍵開始')

    def poll_discovery(self):
        try:
            boards, error = self.discovery_results.get_nowait()
        except queue.Empty:
            return
        self.searching = False
        self.sync_button.config(state='normal')
        if len(boards) == 1:
            self.select_board(boards[0])
        elif boards:
            self.searching = True
            self.sync_button.config(state='disabled')
            self.link.status = '找到多台 UNO Q，請選擇這次要使用的板子'
            picker = tk.Toplevel(self.root)
            picker.title('選擇 UNO Q')
            picker.grab_set()
            def dismiss():
                self.searching = False
                self.sync_button.config(state='normal')
                picker.destroy()
            picker.protocol('WM_DELETE_WINDOW', dismiss)
            for item in boards:
                def choose(selected=item):
                    self.searching = False
                    self.sync_button.config(state='normal')
                    self.select_board(selected)
                    picker.destroy()
                self.button(picker, item['host'], choose).pack(fill='x', padx=20, pady=8)
        else:
            self.link.status = '未找到 v7 接收器：請先在 App Lab 按 Run；也可用「手動 IP」再連線。' + error

    def label(self, parent, text, size, color='#eef4ff', bg=None):
        return tk.Label(parent, text=text, font=('Microsoft JhengHei', size), fg=color, bg=bg or self.BG)

    def button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, font=('Microsoft JhengHei', 12),
                         bg='#244569', fg='white', relief='flat', padx=16, pady=8, takefocus=False)

    def start(self):
        if self.edit_player is not None:
            return
        if self.searching:
            self.info.config(text='正在尋找板子，請稍候。')
            return
        if self.mode.get() == 'board' and not self.host.get().strip():
            self.info.config(text='請按「一鍵連線 UNO Q」，或改選 PC 離線練習。')
            return
        if self.held.intersection(self.keys):
            self.info.config(text='請先放開兩位玩家的按鍵，再開始。')
            return
        if self.game.state == 'ready':
            if self.session.get() == 'practice':
                self.game.begin_practice()
            else:
                rounds = self.rounds_entry.get().strip()
                if not (1 <= len(rounds) <= 2 and rounds.isascii() and rounds.isdecimal()
                        and 1 <= int(rounds) <= MAX_MATCH_ROUNDS):
                    self.info.config(text='請輸入 1 到 99 的整數局數。')
                    self.rounds_entry.focus_set()
                    return
                self.game.match_rounds = int(rounds)
        if self.game.start(self.rule.get()):
            self.cue_token = None
            self.round_mode = self.mode.get()
            if self.round_mode == 'board':
                self.game.state = 'arming'
                self.cue_token = object()
                self.cue_deadline = self.game.clock() + 5
                self.last_signal = (1, tuple(self.game.scores))
                self.link.send(self.host.get(), 1, self.game.scores, token=self.cue_token)
            self.root.focus_set()
            self.render()

    def reset(self):
        self.edit_player = None
        self.sounds.stop()
        self.cue_token = None
        self.game.reset()
        self.render()

    def key_hint(self):
        return f'玩家 1 按 {self.keys[0].upper()} · 玩家 2 按 {self.keys[1].upper()}'

    def edit_key(self, player):
        if self.game.state == 'ready':
            self.edit_player = player
            self.root.focus_set()
            self.info.config(text=f'設定玩家 {player + 1}：按英文字母或數字，Esc 取消')

    def capture_key(self, key):
        player = self.edit_player
        if key != 'escape':
            if key not in PLAYER_KEYS or key == self.keys[1 - player]:
                self.info.config(text='請使用未被另一位玩家使用的英文字母或數字。')
                return
            self.keys[player] = key
        self.edit_player = None
        self.render()
        if key != 'escape':
            try:
                KEY_SETTINGS.parent.mkdir(exist_ok=True)
                KEY_SETTINGS.write_text(json.dumps(self.keys), encoding='utf-8')
            except OSError:
                self.info.config(text='按鍵已更新，這次無法儲存到磁碟。')

    def key_down(self, event):
        if event.widget in (self.host, self.rounds_entry):
            return
        key = event.keysym.lower()
        if key in self.held:
            return 'break'
        self.held.add(key)
        if self.edit_player is not None:
            self.capture_key(key)
            return 'break'
        if key == 'space':
            self.reset() if self.game.state in ('match', 'practice_done') else self.start()
        elif key in self.keys:
            self.game.press(self.keys.index(key))
            self.render()
        if key == 'space' or key in self.keys:
            return 'break'

    def key_up(self, event):
        self.held.discard(event.keysym.lower())

    def focus_check(self):
        if self.root.focus_displayof() is None:
            self.held.clear()
            self.edit_player = None
            self.game.cancel()
            self.cue_token = None
            self.render()

    def render(self):
        g = self.game
        for i in range(2):
            self.cards[i].config(text='—' if g.practice else str(g.scores[i]))
            value = g.reactions[i]
            timing = '—' if value is None else f'{value:.0f} ms'
            if value is not None and self.round_mode == 'board':
                timing = f'約 {value:.0f} ms（±{g.uncertainty_ms:.0f} ms 網路區間）'
            self.times[i].config(text=timing)
        for button, key in zip(self.key_buttons, self.keys):
            button.config(text=f'按鍵 {key.upper()} · 更改', state='normal' if g.state == 'ready' else 'disabled')
        title, color, detail = '準備對決', '#172641', self.key_hint()
        if g.state == 'waiting':
            title, color, detail = '等一下…', '#603348', '不要偷跑！等待綠色訊號'
        elif g.state in ('go', 'hold'):
            green = g.cue_code in (2, 6)
            title, color, detail = ('綠燈' if green else '紅燈'), ('#087f69' if green else '#af2946'), '依本回合規則判斷是否按鍵'
        if g.state in ('waiting', 'cue', 'go', 'hold') and self.round_mode == 'board':
            title, color, detail = '看 UNO Q！', '#172641', '看板上 RGB LED3 的顏色；RGB 藍燈＝等待'
        if g.state == 'arming':
            title, color, detail = '連接裁判台…', '#172641', '確認板上等待燈號，尚未開始；請放開按鍵'
        if g.state in ('result', 'match'):
            if g.reason in ('reaction', 'false_start', 'wrong_color'):
                title = f'玩家 {g.winner+1} 得分！'
                color = '#155a80' if g.winner == 0 else '#884725'
                detail = f'玩家 {2-g.winner} 偷跑，對手得分' if g.reason == 'false_start' else '先收到的有效按鍵得分'
                if g.reason == 'wrong_color':
                    detail = f'玩家 {2-g.winner} 按了禁止顏色，對手得分'
            else:
                title = '本回合重賽'
                detail = '視窗失去焦點，本回合不計分' if g.reason == 'cancelled' else '五秒內沒有人出手，本回合不計分'
                if g.reason == 'ambiguous':
                    detail = '按鍵發生在燈號確認途中，無法判定先後；不計分重賽'
                elif g.reason == 'connection':
                    detail = 'UNO Q 未確認燈號，本回合取消；請檢查連線與板上版本'
                elif g.reason == 'held':
                    title, detail = '成功忍住！', '雙方都沒有誤按，比分不變；空白鍵繼續'
        if g.state == 'match':
            if g.match_winner is None:
                title, color, detail = '平手！', '#244569', '雙方得分相同'
            else:
                title = f'玩家 {g.match_winner+1} 奪冠！'
                color = '#155a80' if g.match_winner == 0 else '#884725'
                detail = f'Congratulations! Player {g.match_winner+1} WIN'
        if g.practice and g.state == 'result':
            title = '練習成功！' if g.reason in ('reaction', 'held') else '繼續練習！'
            detail = '下一題即將開始；練習不計入正式比分'
        if g.state == 'practice_done':
            title, color, detail = '練習完成', '#244569', '30 秒練習結束；空白鍵重置'
        self.stage.config(text=title, bg=color)
        self.detail.config(text=detail)
        if g.practice:
            remaining = max(0, int(g.practice_deadline - g.clock() + .999))
            info = f'練習 · 剩餘 {remaining} 秒 · 第 {g.round} 題 ｜ ' + ('空白鍵重置' if g.state == 'practice_done' else '自動進行中')
        elif g.state == 'ready':
            info = '放開按鍵，按開始或空白鍵'
        elif g.state in ('arming', 'waiting', 'cue', 'go', 'hold'):
            info = f'第 {g.round} / {g.match_rounds} 局 ｜ 等待訊號'
        else:
            hint = '空白鍵重置比賽' if g.state == 'match' else '空白鍵開始下一局'
            info = f'已完成 {sum(g.scores)} / {g.match_rounds} 局 · {g.scores[0]} : {g.scores[1]} ｜ {hint}'
        self.info.config(text=info)
        def summary(i):
            stat = g.stats[i]
            times = stat['times']
            speed = f'平均 {sum(times)/len(times):.0f} ms · 最快 {min(times):.0f} ms' if times else '尚無有效反應'
            rate = f' · 勝率 {100*g.match_wins[i]/g.matches:.0f}%' if g.matches else ''
            return f'玩家 {i+1}：{speed} · 偷跑 {stat["false_starts"]} · 誤按 {stat["wrong_colors"]}{rate}'
        self.statistics.config(text=summary(0) + '\n' + summary(1))
        self.next_button.config(state='disabled' if g.practice or g.state in ('arming', 'waiting', 'cue', 'go', 'hold', 'match') else 'normal')
        self.host.config(state='disabled' if g.state in ('arming', 'waiting', 'cue', 'go', 'hold') else 'normal')
        for button in [*self.mode_buttons, self.sync_button, self.manual_button]:
            button.config(state='disabled' if g.state in ('arming', 'waiting', 'cue', 'go', 'hold') else 'normal')
        if self.searching:
            self.sync_button.config(state='disabled')
        self.rounds_entry.config(state='normal' if g.state == 'ready' else 'disabled')
        for button in [*self.rule_buttons, *self.session_buttons]:
            button.config(state='normal' if g.state == 'ready' else 'disabled')
        rule_text = {'classic': '經典：綠燈搶按', 'green': '綠燈按、紅燈停', 'red': '紅燈按、綠燈停'}[g.rule]
        self.history.config(text=rule_text + (' · 練習連續出題、不計分' if g.practice else ' · 打完設定局數後比較得分'))
        signature = (g.round, g.state, g.reason, g.winner)
        if signature != self.sound_signature:
            self.sound_signature = signature
            if g.state == 'match':
                self.sounds.play('win')
            elif (not g.practice and g.state == 'result'
                  and g.reason in ('reaction', 'false_start', 'wrong_color')):
                self.sounds.play('score')
        self.signal()

    def signal(self, force=False):
        g = self.game
        if g.state in ('arming', 'cue'):
            return
        if g.state == 'waiting':
            code = 1
        elif g.state in ('go', 'hold'):
            code = g.cue_code
        elif g.state == 'practice_done':
            code = 11
        elif g.practice:
            code = 9 if g.reason in ('reaction', 'held') else 10
        elif g.state == 'match':
            if g.match_winner is None:
                code = 16 if g.reason == 'reaction' else 15
            else:
                code = (13 if g.reason == 'reaction' else 7) + g.match_winner
        else:
            code = 12 if g.reason == 'reaction' else 5
        signal = (code, tuple(g.scores))
        if force or signal != self.last_signal:
            self.link.send(self.host.get(), code, g.scores)
            self.last_signal = signal

    def tick(self):
        self.poll_discovery()
        g = self.game
        if g.practice and g.state != 'practice_done' and g.clock() >= g.practice_deadline:
            g.end_practice()
            self.cue_token = None
            self.render()
        while True:
            try:
                token, success, received, sent = self.link.results.get_nowait()
            except queue.Empty:
                break
            if token is self.cue_token and g.state in ('arming', 'cue'):
                if success:
                    if g.state == 'arming':
                        if self.held.intersection(self.keys):
                            g.cancel()
                            g.reason = 'ambiguous'
                        else:
                            g.state = 'waiting'
                            g.due = g.clock() + g.rng.uniform(2, 5)
                    else:
                        g.show_go((sent + received) / 2, max(0, received - sent) * 500)
                else:
                    g.cancel()
                    g.reason = 'connection'
                self.cue_token = None
                self.render()
        if g.state == 'waiting' and g.clock() >= g.due:
            if self.round_mode == 'board':
                g.state = 'cue'
                self.cue_token = object()
                self.cue_deadline = g.clock() + 5
                self.last_signal = (g.cue_code, tuple(g.scores))
                self.link.send(self.host.get(), g.cue_code, g.scores, token=self.cue_token)
            else:
                green = g.cue_code in (2, 6)
                self.stage.config(text='綠燈' if green else '紅燈', bg='#087f69' if green else '#af2946')
                self.stage.update_idletasks()
                g.show_go()
            self.render()
        elif g.state in ('arming', 'cue') and g.clock() >= self.cue_deadline:
            g.cancel()
            g.reason = 'connection'
            self.cue_token = None
            self.render()
        elif g.state in ('go', 'hold') and g.clock() - g.go_time >= (5 if g.state == 'go' else 2):
            g.timeout()
            self.render()
        if g.practice and g.state == 'result':
            if not hasattr(self, 'practice_next_at') or self.practice_last_round != g.round:
                self.practice_last_round = g.round
                self.practice_next_at = g.clock() + .7
            elif g.clock() >= self.practice_next_at:
                self.start()
        if g.practice and g.state != 'practice_done':
            remaining = max(0, int(g.practice_deadline - g.clock() + .999))
            self.info.config(text=f'練習 · 剩餘 {remaining} 秒 · 第 {g.round} 題 ｜ 自動進行中')
        self.network.config(text=self.sounds.error or self.link.status)
        self.root.after(8, self.tick)


if __name__ == '__main__':
    app = tk.Tk()
    Window(app)
    app.mainloop()
