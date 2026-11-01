"""PythonAnywhere 用的 WSGI 入口文件。

用法：在 PythonAnywhere 的 Web 页签里，把「WSGI configuration file」的内容
整个替换成这个文件的内容，并把下面的 USERNAME 改成你自己的用户名。
"""

import os
import sys

# ↓↓↓ 只改这一行：改成你的 PythonAnywhere 用户名（登录名，不含 .pythonanywhere.com）
USERNAME = "你的用户名"

BASE = "/home/{}/divergence".format(USERNAME)

if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 缓存目录 .cache 要建在应用目录下，所以必须切过去（否则会写到根目录，可能没权限）
os.chdir(BASE)

from server import app as application  # noqa: E402  Flask 约定变量名必须是 application
