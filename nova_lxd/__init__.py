__import__('pkg_resources').declare_namespace(__name__)

import os

os.environ['EVENTLET_NO_GREENDNS'] = 'yes'
