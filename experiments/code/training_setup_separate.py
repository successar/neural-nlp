from train import time_str
from train import ex

import sys
fields = ['intervention', 'population', 'outcome']

f = open('../store/message/separate_message_' + time_str + '.txt', 'w')
g = open('SeparateCNNModel.py', 'r').read()
f.write(sys.argv[1] if len(sys.argv) > 1 else time_str + ' No Message')
f.write('\n\n' + g)
f.close()



for f in fields :
    ex.run(config_updates={'exp_group' : 'separate/'+f+'_setup', 
                           'exp_id' : time_str, 
                           'aspect' : f,
                           'trainer' : 'SeparateCNNModel'})