import sys
sys.path.insert(0, '/Users/leizihao/workspace/code/toolclub/ChatFlow/llm-chat/backend')
from quant.worker import start_screen_process
import time

if __name__ == '__main__':
    p = start_screen_process('test1', 'client1', {'market': 'cn_a', 'top_n': 30, 'universe': 'all', 'weights': {}}, 'user1')
    p.join()
