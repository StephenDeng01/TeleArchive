# TeleArchive

将 **Telegram Desktop** 手动导出的 JSON 聊天记录，按时间顺序合并、去重后写入 **SQLite**，便于后续用 SQL 或 Python 分析群聊内容。

适用于：无法申请 Bot/API、群消息自动删除、需要定期导出导致**分段且重叠**的场景。

## 前置条件

1. 使用 [Telegram Desktop](https://desktop.telegram.org/) **≥ 4.15.2**（支持 JSON 导出）。
2. 在目标群聊：**右键标题 → Export chat history**，格式选 **JSON**（可不导出媒体以加快速度）。
3. 每次导出会得到一个文件夹，内含 `result.json` 及媒体子目录（`photos/`、`video_files/` 等）。**JSON 里只有相对路径，图片/视频本体在同级目录中。**

## 安装

```bash
cd TeleArchive
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## 使用

```bash
# 初始化数据库（也可在首次 ingest 时自动创建）
telearchive init

# 导入一次或多次导出（目录或 result.json 均可，支持多个路径）
telearchive ingest ~/Downloads/ChatExport_2026-05-20
telearchive ingest ~/Downloads/ChatExport_2026-05-26

# 导入父文件夹（自动发现其下所有 ChatExport_*）
telearchive ingest "Telegram Desktop(1)"

# 查看合并统计与 id 空洞（自动删消息造成的缺口）
telearchive status
telearchive gaps --min-gap 10
```

默认数据库路径：`data/telearchive.db`。

自定义路径：

```bash
telearchive --db /path/to/my.db ingest ./exports/batch1
```

## 合并原理

| 问题 | 处理方式 |
|------|----------|
| 多段导出重叠 | 以 `(chat_id, message_id)` 为主键去重；Telegram 在单聊内 message id 唯一 |
| 消息被编辑 | 若新导出带更新的 `edited_unixtime` 或内容变化，则更新记录 |
| 顺序 | 库内按 `date_unixtime`, `message_id` 索引，查询时 `ORDER BY` 即可 |
| 原始字段 | `raw_json` 保留完整消息 JSON，便于扩展分析 |
| 图片/视频 | JSON 仅存相对路径；入库时写入 `media_locations`，并按内容 hash 合并不同导出里重命名的同一文件；查询用 `message_media.preferred_absolute_path` |
| 自动删消息 | **并集合并**：较新导出更短时，较早导出里独有的消息仍会保留 |
| 导出批次 | 传入父文件夹可一次导入多个 `ChatExport_*`；按消息时间从旧到新合并 |

### JSON 与媒体文件的关系

Telegram 导出结构示例：

```
ChatExport_2026-05-26/
├── result.json          # 消息元数据 + 媒体相对路径
├── photos/
├── video_files/
├── voice_messages/
└── stickers/
```

`result.json` 中一条带图消息可能类似：

```json
{
  "id": 42,
  "type": "message",
  "photo": "photos/photo_3@26-05-2026_12-00-00.jpg",
  "width": "1280",
  "height": "720"
}
```

导入时以 **`result.json` 所在目录** 为 `export_root`，将 `export_root + photo` 解析为磁盘上的绝对路径。`ingest` 必须传入**整个导出文件夹**（或其中的 `result.json`），不能只拷贝 JSON 而丢掉旁边的 `photos/` 等目录。

多次导出时，同一条消息的相对路径字符串通常相同，但文件在不同日期的导出目录里；工具会记录 `export_root`，并在磁盘上找不到文件时，尽量保留上一次仍能访问的路径。

**注意**：导出时若把「媒体大小限制」设为 0 MB，JSON 里可能只有占位说明、没有真实文件，此时 `file_exists=0` 属正常情况。

## 分析示例（SQL）

```bash
sqlite3 data/telearchive.db
```

```sql
-- 某群最近 50 条文本消息
SELECT datetime(date_unixtime, 'unixepoch') AS t,
       from_name, text
FROM messages
WHERE chat_id = -1001234567890 AND text IS NOT NULL
ORDER BY date_unixtime DESC
LIMIT 50;

-- 按发送者统计条数
SELECT from_name, COUNT(*) AS n
FROM messages
WHERE chat_id = -1001234567890 AND msg_type = 'message'
GROUP BY from_id
ORDER BY n DESC;

-- 带图片且文件仍在磁盘上的消息（首选路径）
SELECT m.date_iso, m.from_name, mm.preferred_absolute_path
FROM messages m
JOIN message_media mm ON mm.chat_id = m.chat_id AND mm.message_id = m.message_id
WHERE m.chat_id = -1001234567890
  AND mm.media_kind = 'photo'
ORDER BY m.date_unixtime DESC
LIMIT 20;

-- 同一附件在不同导出批次下的全部路径
SELECT relative_path, absolute_path, file_exists
FROM media_locations
WHERE chat_id = -1001234567890 AND message_id = 218281;
```

也可用 pandas：`pd.read_sql("SELECT ...", sqlite3.connect("data/telearchive.db"))`。

## 推荐工作流

1. 固定导出目录，例如 `~/TeleArchive/exports/`，每次导出用日期命名子文件夹。
2. 每周或每天导出后执行：`telearchive ingest ~/TeleArchive/exports/*`
3. 用 `status` 确认消息总数与时间范围是否连续变长。

## Windows 可执行文件

无需安装 Python，使用单个 `telearchive.exe` 即可。

### 方式一：GitHub Release 下载（推荐，无需 Windows）

1. 打开仓库 [Releases](https://github.com/StephenDeng01/TeleArchive/releases) 页面。
2. 下载最新版 **`telearchive.exe`** 即可使用。

维护者发布新版本：

```bash
git tag v0.1.0
git push origin v0.1.0
```

或在 GitHub **Actions → Build Windows exe → Run workflow**，勾选发布 Release，填写标签（如 `v0.1.0`），构建完成后 exe 会自动出现在 Releases 页面。

### 方式二：GitHub Actions 手动构建（仅下载 Artifact）

1. 打开 **Actions → Build Windows exe → Run workflow**。
2. 若不需要 Release，将「发布到 GitHub Release」设为 false。
3. 在 **Artifacts** 下载 `telearchive-windows-x64`。

### 方式三：在 Windows 本机构建

需要 [Python 3.9+](https://www.python.org/downloads/)（仅构建时用）。

```powershell
git clone https://github.com/StephenDeng01/TeleArchive.git
cd TeleArchive
.\scripts\build_windows.ps1
```

产物：`dist\telearchive.exe`（约 15–25 MB，单文件、免安装）。

### Windows 使用示例

在 PowerShell 或 CMD 中，于 exe 所在目录或将其加入 PATH：

```powershell
.\telearchive.exe init
.\telearchive.exe ingest "D:\Downloads\ChatExport_2026-05-26"
.\telearchive.exe ingest "D:\Downloads\Telegram Desktop(1)"
.\telearchive.exe status
.\telearchive.exe gaps --min-gap 10
```

数据库默认写在当前工作目录的 `data\telearchive.db`。可指定路径：

```powershell
.\telearchive.exe ingest --db D:\TeleArchive\archive.db "D:\exports\batch1"
```

## 开发

```bash
pytest
```

## 参考

- [Telegram Data Export Schema](https://core.telegram.org/import-export)
