import os

# 必须在导入任何 app 模块前生效：app.database 在 import 时按 settings 建引擎，
# 默认 postgres URL 需要 psycopg2，测试环境没有也不该依赖真实数据库。
os.environ.setdefault("DATABASE_URL", "sqlite://")
