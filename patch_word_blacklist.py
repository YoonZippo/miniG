import os

def patch_word_blacklist():
    file_path = r"x:\Desktop\projects\discordBot\miniG\cogs\liar\liar_game.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Add `from collections import deque` to imports if not exists
    if "from collections import deque" not in content:
        import_block = "from collections import Counter\n"
        new_import_block = "from collections import Counter, deque\n"
        content = content.replace(import_block, new_import_block)

    # 2. Add global deque
    if "recent_words =" not in content:
        global_block = "active_games: Dict[int, 'LiarGame'] = {}\n"
        new_global_block = "active_games: Dict[int, 'LiarGame'] = {}\n# 최근 사용된 제시어 50개 추적\nrecent_words = deque(maxlen=50)\n"
        content = content.replace(global_block, new_global_block)
        
    # 3. Modify callback inside CategorySelect to use recent_words
    old_callback = """    async def callback(self, interaction: discord.Interaction):
        # 1. 카테고리 및 제시어 선정
        self.game.category = self.values[0]
        
        category_words = NORMAL_WORDS[self.game.category]
        if self.game.game_mode == "IDIOT":
            # 같은 카테고리 안에서 무작위로 서로 다른 2개의 단어를 추출 (시민용, 라이어용)
            sampled = random.sample(category_words, 2)
            self.game.word = sampled[0]
            self.game.liar_word = sampled[1]
        else:
            self.game.word = random.choice(category_words)"""
            
    new_callback = """    async def callback(self, interaction: discord.Interaction):
        # 1. 카테고리 및 제시어 선정
        self.game.category = self.values[0]
        
        category_words = NORMAL_WORDS[self.game.category]
        
        # 최근 50번 이내에 나오지 않았던 단어만 필터링 (가용 단어 부족 시 롤백 방지)
        available_words = [w for w in category_words if w not in recent_words]
        
        if self.game.game_mode == "IDIOT":
            if len(available_words) >= 2:
                sampled = random.sample(available_words, 2)
            else:
                sampled = random.sample(category_words, 2) # 필터링 된 단어가 부족하면 전체에서 무작위 추출
            self.game.word = sampled[0]
            self.game.liar_word = sampled[1]
            recent_words.append(self.game.word)
            recent_words.append(self.game.liar_word)
        else:
            if len(available_words) >= 1:
                self.game.word = random.choice(available_words)
            else:
                self.game.word = random.choice(category_words) # 필터링 된 단어가 부족하면 전체에서 무작위 추출
            recent_words.append(self.game.word)"""

    if old_callback in content:
        content = content.replace(old_callback, new_callback)
        print("Successfully applied word blacklist to liar_game.py!")
    else:
        print("Warning: Failed to find the target callback in liar_game.py")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

patch_word_blacklist()
