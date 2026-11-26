# 澄湾自然展馆大字折页印务

展馆编辑提交有序展签定稿。印务组用正印实物号装盘，由背印工位按冻结工单续印。验收员核回实际两面，把齐件清单签给服务台。系统用 SQLite 记载模拟实吐和实印，可在本机复验纸式、方向、页位和实际出处。

## 运行

使用 Python 3.11 标准库。平台物化项目时提供 `check_project.py`，从项目根目录运行完整回归。

```sh
python3 -B check_project.py
python3 -B demo.py
```

演示在临时目录创建两端库，在本机经 HTTP 走完五页校样、两张正印、封盘、欠件检查、补齐与重开复领。输出包括手算页位对照、第一次验收的欠件和第二次验收的逐折页实际出处。断言失败会使演示退出非零。

在两个终端分别启动长驻服务时，为两端指定不同数据库。

```sh
python3 -B -m tray.desk_http --db desk.sqlite3 --port 8766 --station http://127.0.0.1:8767
python3 -B -m back.station_http --db station.sqlite3 --port 8767 --desk http://127.0.0.1:8766
```

两端各自初始化缺失的表。用原数据库重开会保留已录入和签出的记录。演示样例由显式请求录入。开发和验收环境默认监听回环地址，参与方在同一可信本机上使用公开业务接口。

## 纸式、折页和出处

正文按输入顺序编号，每一项是一页文字。用 `null` 补足至四的倍数 M，表明该页位留空。第 i 张折页从 0 起算，依次取正面 `[M−2i, 1+2i]`、背面 `[2+2i, M−1−2i]`，左右顺序即数组顺序。折页号从 A、B 顺延。纸式为 `{"width":210,"height":297}` 这样的有序整数毫米尺寸，宽高都须为正整数。方向为 `head` 或 `foot`，工位使用与装盘记录相同的方向。

五页定稿 `1` 至 `5` 的 A 正面为 `[null,"1"]`，背面为 `["2",null]`。B 正面为 `[null,"3"]`，背面为 `["4","5"]`。两个折页分别正印并登记入盘。先背印 A 时只欠 B。续印 B 后按 A、B 签出。正印实物、封盘工单和工位实际出件都记录固定册版和页片。验收以最早合格工位序号为该折页选件，提交托盘的次序不影响取舍。

## JSON HTTP

POST 发送 JSON 对象，GET 和 POST 的成功状态为 200。`draft`、`edition`、`sheet`、`order`、`slot`、`sequence` 和 `book` 为正整数。`tray`、`fold`、`request` 为非空字符串。将托盘名作为 URL 路径段时使用 URL 编码。两端的请求号各自在本端绑定。

| 台端入口 | 请求字段 | 返回记录 |
| --- | --- | --- |
| `POST /drafts` | `pages`、`paper` | `draft`、正文、纸式、各折页两面预览 |
| `GET /drafts/{draft}` | 路径中的校样号 | 校样原记录 |
| `POST /editions` | `draft` | `edition`、所用校样号、正文、纸式和固定页片 |
| `GET /editions/{edition}` | 路径中的版号 | 固定册版 |
| `POST /front` | `edition`、`fold`、`paper`、`request` | 实物 `sheet`、册版、折页、实际纸式、正面及原请求号 |
| `GET /front/{sheet}` | 路径中的实物号 | 正印原记录 |
| `POST /trays/{tray}/load` | `slot`、`sheet`、`direction` | 已辨认的实际槽位 |
| `POST /trays/{tray}/dispatch` | 空对象 | `order`、托盘、册版、纸式、按槽号排列的实物及两面页片 |
| `GET /trays/{tray}/order`、`GET /orders/{order}` | 路径中的托盘名或工单号 | 同一份冻结工单 |
| `POST /books/finish` | `edition`、`trays`，后者为托盘名数组 | `book`、册版、按固定折页序排列的完整清单 |
| `GET /books/{book}` | 路径中的成册号 | 原签出清单 |

| 工位入口 | 请求字段 | 返回记录 |
| --- | --- | --- |
| `POST /back` | `order`、`slot`、`paper`、`direction`、`request` | 首次实印的 `sequence`、工单、托盘、槽、册版、实物、折页、纸式、方向、背页和原请求号 |
| `GET /impressions/{sequence}` | 路径中的实印序号 | 原实际出件记录 |
| `GET /orders/{order}/impressions` | 路径中的工单号 | `impressions` 数组，查无实际出件时为空 |
| `GET /impressions?order=1&order=2` | 一个或多个 `order` 参数 | 同一工位读事务内按序号查询的实际出件 |

错误响应有 `error` 字段。非法输入返回 400，未知的具名事实返回 404。正背印纸式失配、背印方向失配及成功号改参返回 409。成功号按原参数重投得到原次，背印同工单同槽用正确参数换新号仍绑定首序号。盘内重复装入、占槽、串册、空盘封单及封盘后装入返回 409。封盘重领得到原工单。验收欠件或冲突时返回 409，包含 `missing` 和 `conflicts` 数组。工位证据失答时返回 503，待能取证后可再办。齐件每次签出生成正式号，后续按正式号领取按值保存的清单。

## 正常回归

`tests/test_edition.py` 检查 N1、N2 的三页与五页拼版、旧版读回及拒绝非法校样。`tests/test_press.py` 检查 N3、N5、N6 的纸式、方向、原号和换号重报、独立工单槽及原库重开。`tests/test_tray.py` 检查 N4 的盘内唯一、固定册版及封单。`tests/test_books.py` 检查 N7、N8 的欠件、串册、首件选择与原清单复领。`tests/test_recovery.py` 用真实 HTTP 扣留请求、丢弃回包，核对失答与空记录的区别，以及两端反复初始化后仍能接续办理。`tests/test_workday.py` 独立断言五页的手算结果进入原签出清单。
