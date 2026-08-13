"""音频库模块（音乐爬取 + 账号管理）。

从 LX_SmartMixroll 迁移网易云/酷我音乐爬取能力，作为 BGM 库的第二个入库入口。
账号体系仿 publisher 模块（多账号、Cookie 持久化、扫码登录），爬取子进程隔离。

子模块：
- providers/      音乐源 provider（netease/kuwo）
- _cookie.py      账号 cookie 持久化
- login.py        网易云扫码登录（patchright）
- worker.py       爬取/搜索子进程入口
- runner.py       主进程侧子进程编排
- bgm_import.py   爬取结果纳入 BGM 库的公共逻辑
- types.py        数据契约（AudioTaskPayload / AudioTaskResult）
"""
