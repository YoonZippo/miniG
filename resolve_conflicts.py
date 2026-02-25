import os
import re

conflicted_files = [
    r"requirements.txt",
    r"Dockerfile",
    r"docker-compose.yml",
    r"DEPLOYMENT.md",
    r"cogs/spyfall/spyfall.py",
    r"cogs/spyfall/locations.py",
    r"cogs/liar/liar_game.py",
    r"cogs/HELLO.py"
]

def resolve_conflict(file_path):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # regex for conflict markers keeping HEAD
    # <<<<<<< HEAD
    # (HEAD content)
    # =======
    # (Remote content)
    # >>>>>>> (commit)
    
    pattern = re.compile(r'<<<<<<< HEAD\n(.*?)\n=======.*?>>>>>>> [a-z0-9]+', re.DOTALL)
    new_content = pattern.sub(r'\1', content)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Resolved: {file_path}")

if __name__ == "__main__":
    os.chdir(r"x:\Desktop\projects\discordBot")
    for f in conflicted_files:
        resolve_conflict(f)
