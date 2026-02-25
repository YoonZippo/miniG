import sqlite3
import os

class DatabaseManager:
    def __init__(self, db_path='database/database.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 유저 전적 테이블 생성
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
            conn.commit()

    def update_stats(self, user_id, game_type, won=False):
        """승리/패배 시 전적 업데이트"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 유저가 없으면 새로 생성
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

    def get_user_stats(self, user_id):
        """특정 유저의 전적 조회"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT liar_wins, liar_plays, spyfall_wins, spyfall_plays FROM user_stats WHERE user_id = ?', (user_id,))
            return cursor.fetchone()

    def get_top_rankings(self, game_type, limit=3):
        """Top 3 랭킹 조회"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if game_type == 'liar':
                sort_col = 'liar_wins'
            elif game_type == 'spyfall':
                sort_col = 'spyfall_wins'
            else:
                return []

            cursor.execute(f'SELECT user_id, {sort_col} FROM user_stats WHERE {sort_col} > 0 ORDER BY {sort_col} DESC LIMIT ?', (limit,))
            return cursor.fetchall()
