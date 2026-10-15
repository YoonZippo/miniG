import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

GAME_REWARD_TYPES = {"liar", "spyfall", "cheese_thief", "prisoners_night", "consonant"}
GAME_WIN_REWARD_TYPES = {"liar", "spyfall", "cheese_thief", "prisoners_night"}
GAME_COMPLETION_REWARD = 20
GAME_WIN_REWARD = 50
GAME_SPECIAL_WIN_REWARD = 100


class DatabaseManager:
    def __init__(self, db_path='database/database.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._connection() as conn:
            cursor = conn.cursor()
            # 1. 유저 전적 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id INTEGER PRIMARY KEY,
                    liar_wins INTEGER DEFAULT 0,
                    liar_plays INTEGER DEFAULT 0,
                    spyfall_wins INTEGER DEFAULT 0,
                    spyfall_plays INTEGER DEFAULT 0,
                    last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # 2. 유저 포인트 & 경제 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_economy (
                    user_id INTEGER PRIMARY KEY,
                    points INTEGER DEFAULT 500,
                    last_daily TEXT,
                    daily_streak INTEGER DEFAULT 0,
                    title TEXT DEFAULT '새싹 게이머'
                )
            ''')
            # 3. 포인트 변동 기록 로그
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS point_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS game_results (
                    game_id TEXT NOT NULL,
                    game_type TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ('win', 'loss', 'draw')),
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (game_id, user_id)
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_game_results_user_type
                ON game_results (user_id, game_type)
            ''')
            conn.commit()

    def record_game_result(
        self,
        game_id: str,
        game_type: str,
        participant_ids: List[int],
        winner_ids: Optional[List[int]] = None,
        draw_ids: Optional[List[int]] = None,
        special_winner_ids: Optional[List[int]] = None,
    ) -> bool:
        """게임 결과와 보상을 한 번의 트랜잭션으로 기록한다."""
        participants = list(dict.fromkeys(int(user_id) for user_id in participant_ids))
        winners = set(int(user_id) for user_id in (winner_ids or []))
        draws = set(int(user_id) for user_id in (draw_ids or []))
        special_winners = set(int(user_id) for user_id in (special_winner_ids or []))

        if not game_id or not game_type:
            raise ValueError("game_id와 game_type은 비어 있을 수 없습니다.")
        if not participants:
            raise ValueError("게임 결과를 기록하려면 참가자가 필요합니다.")
        if not winners.issubset(participants) or not draws.issubset(participants):
            raise ValueError("승자와 무승부 참가자는 게임 참가자여야 합니다.")
        if not special_winners.issubset(winners):
            raise ValueError("특수 승리자는 승자에 포함되어야 합니다.")
        if winners.intersection(draws):
            raise ValueError("한 참가자를 승리와 무승부로 동시에 기록할 수 없습니다.")

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("SELECT 1 FROM game_results WHERE game_id = ? LIMIT 1", (game_id,))
            if cursor.fetchone():
                return False

            results = [
                (game_id, game_type, user_id,
                 "win" if user_id in winners else "draw" if user_id in draws else "loss")
                for user_id in participants
            ]
            cursor.executemany(
                "INSERT INTO game_results (game_id, game_type, user_id, outcome) VALUES (?, ?, ?, ?)",
                results,
            )

            if game_type in GAME_REWARD_TYPES:
                for _, _, user_id, outcome in results:
                    reward = GAME_COMPLETION_REWARD
                    reason = f"GAME_COMPLETE_{game_type}"
                    if outcome == "win" and game_type in GAME_WIN_REWARD_TYPES:
                        win_reward = (
                            GAME_SPECIAL_WIN_REWARD
                            if user_id in special_winners
                            else GAME_WIN_REWARD
                        )
                        reward += win_reward
                        reason = (
                            f"GAME_SPECIAL_WIN_{game_type}"
                            if user_id in special_winners
                            else f"GAME_WIN_{game_type}"
                        )

                    cursor.execute(
                        "INSERT OR IGNORE INTO user_economy "
                        "(user_id, points, daily_streak, title) VALUES (?, 500, 0, ?)",
                        (user_id, "새싹 게이머"),
                    )
                    cursor.execute(
                        "UPDATE user_economy SET points = points + ? WHERE user_id = ?",
                        (reward, user_id),
                    )
                    cursor.execute(
                        "SELECT points FROM user_economy WHERE user_id = ?",
                        (user_id,),
                    )
                    balance = cursor.fetchone()[0]
                    cursor.execute(
                        "INSERT INTO point_logs (user_id, amount, balance_after, reason) "
                        "VALUES (?, ?, ?, ?)",
                        (user_id, reward, balance, reason),
                    )

            legacy_columns = {
                "liar": ("liar_wins", "liar_plays"),
                "spyfall": ("spyfall_wins", "spyfall_plays"),
            }
            if game_type in legacy_columns:
                win_column, play_column = legacy_columns[game_type]
                for _, _, user_id, outcome in results:
                    cursor.execute("INSERT OR IGNORE INTO user_stats (user_id) VALUES (?)", (user_id,))
                    cursor.execute(
                        f"UPDATE user_stats SET {win_column} = {win_column} + ?, "
                        f"{play_column} = {play_column} + 1, last_played = CURRENT_TIMESTAMP "
                        "WHERE user_id = ?",
                        (int(outcome == "win"), user_id),
                    )

            conn.commit()
            return True

    def get_game_stats(self, user_id: int) -> Dict[str, Dict[str, int]]:
        with self._connection() as conn:
            rows = conn.execute(
                '''
                SELECT game_type, COUNT(*),
                       SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'draw' THEN 1 ELSE 0 END)
                FROM game_results
                WHERE user_id = ?
                GROUP BY game_type
                ''',
                (user_id,),
            ).fetchall()
        return {
            game_type: {"plays": plays, "wins": wins, "draws": draws}
            for game_type, plays, wins, draws in rows
        }

    # ──────────────────────────────────────────────
    # 전적 관련
    # ──────────────────────────────────────────────
    def update_stats(self, user_id: int, game_type: str, won: bool = False):
        """승리/패배 시 전적 업데이트"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO user_stats (user_id) VALUES (?)', (user_id,))
            
            if game_type == 'liar':
                win_col, play_col = 'liar_wins', 'liar_plays'
            elif game_type == 'spyfall':
                win_col, play_col = 'spyfall_wins', 'spyfall_plays'
            else:
                return

            if won:
                cursor.execute(f'UPDATE user_stats SET {win_col} = {win_col} + 1, {play_col} = {play_col} + 1, last_played = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
            else:
                cursor.execute(f'UPDATE user_stats SET {play_col} = {play_col} + 1, last_played = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
            conn.commit()

    def get_user_stats(self, user_id: int):
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT liar_wins, liar_plays, spyfall_wins, spyfall_plays FROM user_stats WHERE user_id = ?', (user_id,))
            return cursor.fetchone()

    def get_top_rankings(self, game_type: str, limit: int = 3):
        with self._connection() as conn:
            cursor = conn.cursor()
            if game_type == 'liar':
                sort_col = 'liar_wins'
            elif game_type == 'spyfall':
                sort_col = 'spyfall_wins'
            else:
                return []

            cursor.execute(f'SELECT user_id, {sort_col} FROM user_stats WHERE {sort_col} > 0 ORDER BY {sort_col} DESC LIMIT ?', (limit,))
            return cursor.fetchall()

    # ──────────────────────────────────────────────
    # 포인트 및 경제 시스템
    # ──────────────────────────────────────────────
    def _ensure_economy_user(self, cursor: sqlite3.Cursor, user_id: int):
        cursor.execute('INSERT OR IGNORE INTO user_economy (user_id, points, daily_streak, title) VALUES (?, 500, 0, ?)', (user_id, '새싹 게이머'))

    def get_user_economy(self, user_id: int) -> dict:
        with self._connection() as conn:
            cursor = conn.cursor()
            self._ensure_economy_user(cursor, user_id)
            conn.commit()
            cursor.execute('SELECT points, last_daily, daily_streak, title FROM user_economy WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "points": row[0],
                    "last_daily": row[1],
                    "daily_streak": row[2],
                    "title": row[3]
                }
            return {"points": 500, "last_daily": None, "daily_streak": 0, "title": "새싹 게이머"}

    def add_points(self, user_id: int, amount: int, reason: str = "") -> int:
        """포인트 추가/차감 (amount가 음수면 차감)"""
        with self._connection() as conn:
            cursor = conn.cursor()
            self._ensure_economy_user(cursor, user_id)
            cursor.execute('UPDATE user_economy SET points = points + ? WHERE user_id = ?', (amount, user_id))
            cursor.execute('SELECT points FROM user_economy WHERE user_id = ?', (user_id,))
            new_balance = cursor.fetchone()[0]

            # 로그 기록
            cursor.execute('INSERT INTO point_logs (user_id, amount, balance_after, reason) VALUES (?, ?, ?, ?)',
                           (user_id, amount, new_balance, reason))
            conn.commit()
            return new_balance

    def adjust_points_safe(self, user_id: int, amount: int, reason: str = "") -> int:
        """잔액을 음수로 만들지 않고 포인트를 조정한다.

        차감액이 잔액을 넘으면 잔액 전액만 차감한다. (게임 정산용)
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            self._ensure_economy_user(cursor, user_id)
            if amount < 0:
                cursor.execute('SELECT points FROM user_economy WHERE user_id = ?', (user_id,))
                balance = cursor.fetchone()[0]
                amount = max(amount, -balance)
                if amount == 0:
                    return balance
            cursor.execute('UPDATE user_economy SET points = points + ? WHERE user_id = ?', (amount, user_id))
            cursor.execute('SELECT points FROM user_economy WHERE user_id = ?', (user_id,))
            new_balance = cursor.fetchone()[0]
            cursor.execute('INSERT INTO point_logs (user_id, amount, balance_after, reason) VALUES (?, ?, ?, ?)',
                           (user_id, amount, new_balance, reason))
            conn.commit()
            return new_balance

    def claim_daily(self, user_id: int) -> Tuple[bool, int, int, str]:
        """(성공여부, 지급된 포인트, 연속출석일수, 안내메시지)"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        with self._connection() as conn:
            cursor = conn.cursor()
            self._ensure_economy_user(cursor, user_id)
            cursor.execute('SELECT last_daily, daily_streak FROM user_economy WHERE user_id = ?', (user_id,))
            last_daily, streak = cursor.fetchone()

            if last_daily == today_str:
                return (False, 0, streak, "오늘 이미 출석체크를 완료했습니다! 내일 다시 시도해주세요.")

            if last_daily == yesterday_str:
                new_streak = streak + 1
            else:
                new_streak = 1

            # 기본 100P + 연속 출석 1일당 10P (최대 100P 추가)
            bonus = min((new_streak - 1) * 10, 100)
            reward = 100 + bonus

            cursor.execute('''
                UPDATE user_economy 
                SET points = points + ?, last_daily = ?, daily_streak = ?
                WHERE user_id = ?
            ''', (reward, today_str, new_streak, user_id))

            cursor.execute('SELECT points FROM user_economy WHERE user_id = ?', (user_id,))
            new_balance = cursor.fetchone()[0]

            cursor.execute('INSERT INTO point_logs (user_id, amount, balance_after, reason) VALUES (?, ?, ?, ?)',
                           (user_id, reward, new_balance, f"DAILY_STREAK_{new_streak}"))
            conn.commit()

            msg = f"🎉 **{reward}P** 획득! (기본 100P + 연속 출석 보너스 {bonus}P)\n현재 연속 출석: **{new_streak}일째**"
            return (True, reward, new_streak, msg)

    def transfer_points(self, sender_id: int, receiver_id: int, amount: int) -> Tuple[bool, str]:
        if sender_id == receiver_id:
            return (False, "자기 자신에게는 송금할 수 없습니다.")
        if amount <= 0:
            return (False, "1P 이상의 금액만 송금할 수 있습니다.")

        with self._connection() as conn:
            cursor = conn.cursor()
            self._ensure_economy_user(cursor, sender_id)
            self._ensure_economy_user(cursor, receiver_id)

            cursor.execute('SELECT points FROM user_economy WHERE user_id = ?', (sender_id,))
            sender_balance = cursor.fetchone()[0]

            if sender_balance < amount:
                return (False, f"잔액이 부족합니다! (현재 보유: **{sender_balance}P**)")

            # 발신자 차감
            cursor.execute('UPDATE user_economy SET points = points - ? WHERE user_id = ?', (amount, sender_id))
            cursor.execute('SELECT points FROM user_economy WHERE user_id = ?', (sender_id,))
            new_sender_bal = cursor.fetchone()[0]
            cursor.execute('INSERT INTO point_logs (user_id, amount, balance_after, reason) VALUES (?, ?, ?, ?)',
                           (sender_id, -amount, new_sender_bal, f"TRANSFER_TO_{receiver_id}"))

            # 수신자 증가
            cursor.execute('UPDATE user_economy SET points = points + ? WHERE user_id = ?', (amount, receiver_id))
            cursor.execute('SELECT points FROM user_economy WHERE user_id = ?', (receiver_id,))
            new_recv_bal = cursor.fetchone()[0]
            cursor.execute('INSERT INTO point_logs (user_id, amount, balance_after, reason) VALUES (?, ?, ?, ?)',
                           (receiver_id, amount, new_recv_bal, f"TRANSFER_FROM_{sender_id}"))

            conn.commit()
            return (True, f"성공적으로 **{amount}P**를 송금했습니다! (송금 후 잔액: **{new_sender_bal}P**)")

    def set_title(self, user_id: int, title: str, cost: int = 0) -> Tuple[bool, str]:
        with self._connection() as conn:
            cursor = conn.cursor()
            self._ensure_economy_user(cursor, user_id)
            if cost > 0:
                cursor.execute('SELECT points FROM user_economy WHERE user_id = ?', (user_id,))
                balance = cursor.fetchone()[0]
                if balance < cost:
                    return (False, f"포인트가 부족합니다! (필요: {cost}P / 보유: {balance}P)")
                cursor.execute('UPDATE user_economy SET points = points - ? WHERE user_id = ?', (cost, user_id))

            cursor.execute('UPDATE user_economy SET title = ? WHERE user_id = ?', (title, user_id))
            conn.commit()
            return (True, f"칭호가 **[{title}]**(으)로 변경되었습니다!")

    def get_top_rich(self, limit: int = 10) -> List[Tuple[int, int, str]]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, points, title 
                FROM user_economy 
                ORDER BY points DESC 
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
