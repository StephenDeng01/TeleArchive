"""Command-line interface for TeleArchive."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from telearchive import __version__
from telearchive.coverage import export_coverage, find_id_gaps
from telearchive.db import Database
from telearchive.db_tools import create_db_backup, rollback_db_from_backup, split_db_by_chat
from telearchive.export_chat import export_chat_range
from telearchive.merge import ingest_paths
from telearchive.updater import check_for_update, dismiss_update_reminder
from telearchive.paths import default_db_path

app = typer.Typer(
    name="telearchive",
    help="合并 Telegram Desktop 导出的 JSON 聊天记录并写入 SQLite。",
    no_args_is_help=True,
)
console = Console()

DEFAULT_DB = default_db_path()


def _resolve_db(db: Optional[Path]) -> Path:
    return db or DEFAULT_DB


@app.command()
def version() -> None:
    """显示版本号。"""
    console.print(f"telearchive {__version__}")


@app.command()
def export(
    output_dir: Path = typer.Argument(
        ...,
        help="导出目录（将生成 result.json 及 photos/ 等媒体子目录）",
    ),
    from_date: str = typer.Option(
        ...,
        "--from",
        "from_date",
        help="开始时间（YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS 或 Unix 时间戳）",
    ),
    to_date: str = typer.Option(
        ...,
        "--to",
        "to_date",
        help="结束时间（日期含当天全天）",
    ),
    chat_id: Optional[int] = typer.Option(
        None, "--chat-id", help="群聊 ID；省略则使用库中唯一群聊"
    ),
    no_media: bool = typer.Option(
        False, "--no-media", help="仅导出 JSON，不复制媒体文件"
    ),
    db: Optional[Path] = typer.Option(
        None, "--db", help="数据库路径，默认 data/telearchive.db"
    ),
) -> None:
    """按时间范围导出为 Telegram Desktop 兼容的 JSON 目录结构。"""
    db_path = _resolve_db(db)
    if not db_path.is_file():
        console.print(f"[red]数据库不存在[/red]: {db_path}")
        raise typer.Exit(1)

    with Database(db_path) as database:
        chats = database.list_chat_stats()
        if not chats:
            console.print("[yellow]尚无聊天记录[/yellow]")
            raise typer.Exit(1)
        target = chat_id
        if target is None:
            if len(chats) != 1:
                console.print(
                    "[red]数据库中有多个群聊，请使用 --chat-id 指定[/red]"
                )
                for c in chats:
                    console.print(f"  {c.chat_id}: {c.name}")
                raise typer.Exit(1)
            target = chats[0].chat_id

        try:
            result = export_chat_range(
                database,
                output_dir,
                target,
                from_bound=from_date,
                to_bound=to_date,
                include_media=not no_media,
            )
        except ValueError as exc:
            console.print(f"[red]导出失败[/red]: {exc}")
            raise typer.Exit(1) from exc

    console.print(f"[green]导出完成[/green] → {result.output_dir}")
    console.print(f"群聊: {result.chat_name} (id={result.chat_id})")
    console.print(f"消息: {result.message_count} 条")
    if not no_media:
        console.print(
            f"媒体: 复制 {result.media_copied} 个，缺失 {result.media_missing} 个"
        )
    console.print(f"主文件: {result.output_dir / 'result.json'}")


@app.command("check-update")
def check_update_cmd(
    dismiss: Optional[str] = typer.Option(
        None,
        "--dismiss",
        help="不再提示该版本更新（例如 --dismiss 0.3.0）",
    ),
) -> None:
    """检查 GitHub 是否有新版本（仅提醒，不强制更新）。"""
    if dismiss:
        dismiss_update_reminder(dismiss.lstrip("vV"))
        console.print(f"[green]已设置：不再提示 v{dismiss.lstrip('vV')} 更新[/green]")
        return

    result = check_for_update()
    if result.error:
        console.print(f"[yellow]检查失败[/yellow]: {result.error}")
        raise typer.Exit(1)
    if not result.has_update:
        console.print(f"[green]当前已是最新版本[/green]（v{result.current_version}）")
        return
    latest = result.latest
    assert latest is not None
    if result.is_dismissed:
        console.print(
            f"有新版本 v{latest.version}，但您已选择不再提示此版本。"
        )
        console.print(f"下载: {latest.url}")
        return
    console.print(
        f"[cyan]发现新版本[/cyan]: v{result.current_version} → v{latest.version}"
    )
    console.print(f"下载: {latest.url}")
    if latest.notes:
        console.print("\n更新说明:\n" + latest.notes[:500])


@app.command()
def init(
    db: Optional[Path] = typer.Option(
        None, "--db", help="数据库路径，默认 data/telearchive.db"
    ),
) -> None:
    """初始化数据库（创建表结构）。"""
    path = _resolve_db(db)
    with Database(path) as database:
        database.init_schema()
    console.print(f"[green]已初始化[/green] {path.resolve()}")


@app.command()
def ingest(
    paths: list[Path] = typer.Argument(
        ...,
        help="导出目录、父文件夹或 result.json；父文件夹下多个 ChatExport_* 会自动全部导入",
    ),
    db: Optional[Path] = typer.Option(
        None, "--db", help="数据库路径，默认 data/telearchive.db"
    ),
    allow_mixed_chats: bool = typer.Option(
        False,
        "--allow-mixed-chats",
        help="允许导入与当前数据库不同的群聊（不推荐）",
    ),
    backup_before_ingest: bool = typer.Option(
        True,
        "--backup/--no-backup",
        help="导入前自动创建数据库备份（推荐开启）",
    ),
) -> None:
    """导入并合并聊天记录（按 chat_id + message_id 去重，保留旧导出中已删消息）。"""
    db_path = _resolve_db(db)
    if backup_before_ingest and db_path.is_file():
        backup = create_db_backup(db_path)
        console.print(f"[dim]已创建导入前备份[/dim] → {backup}")
    with Database(db_path) as database:
        try:
            results = ingest_paths(
                database, paths, allow_mixed_chats=allow_mixed_chats
            )
        except FileNotFoundError as e:
            console.print(f"[red]错误[/red]: {e}")
            raise typer.Exit(1) from e
        except ValueError as e:
            console.print(f"[red]解析失败[/red]: {e}")
            raise typer.Exit(1) from e

        if not results:
            console.print("[yellow]未找到任何 result.json[/yellow]")
            raise typer.Exit(1)

        chats = database.list_chat_stats()

    table = Table(title="导入结果（按时间从旧到新合并）")
    table.add_column("文件")
    table.add_column("消息", justify="right")
    table.add_column("新增", justify="right")
    table.add_column("更新", justify="right")
    table.add_column("媒体引用", justify="right")
    table.add_column("媒体在盘", justify="right")
    table.add_column("媒体缺失", justify="right")

    total_seen = total_new = total_updated = 0
    for source, stats in results:
        total_seen += stats.messages_seen
        total_new += stats.messages_new
        total_updated += stats.messages_updated
        table.add_row(
            _export_label(source),
            str(stats.messages_seen),
            str(stats.messages_new),
            str(stats.messages_updated),
            str(stats.media_refs),
            str(stats.media_found),
            str(stats.media_missing),
        )

    console.print(table)
    if chats:
        console.print(
            f"\n合并后共 [cyan]{chats[0].message_count}[/cyan] 条唯一消息 "
            f"（本批处理 {total_seen}，新增 {total_new}，更新 {total_updated}）"
        )
        if len(results) > 1:
            latest_seen = results[-1][1].messages_seen
            preserved = max(chats[0].message_count - latest_seen, 0)
            if preserved:
                console.print(
                    f"[dim]较新导出中已消失、仅由较早导出保留的消息约 "
                    f"{preserved} 条（群自动删除导致）[/dim]"
                )
    console.print(f"数据库: [cyan]{db_path.resolve()}[/cyan]")


@app.command("split-db")
def split_db(
    out_dir: Path = typer.Argument(..., help="拆分输出目录（将生成多个 .db）"),
    db: Optional[Path] = typer.Option(
        None, "--db", help="数据库路径，默认 data/telearchive.db"
    ),
) -> None:
    """将混合群聊的数据库按 chat_id 拆分为多个单群数据库。"""
    db_path = _resolve_db(db)
    results = split_db_by_chat(db_path, out_dir)
    table = Table(title="拆分结果")
    table.add_column("群聊 ID", justify="right")
    table.add_column("名称")
    table.add_column("消息数", justify="right")
    table.add_column("输出 DB")
    for r in results:
        table.add_row(str(r.chat_id), r.chat_name, str(r.message_count), str(r.output_db))
    console.print(table)


@app.command("rollback-db")
def rollback_db(
    backup_db: Path = typer.Argument(..., help="备份数据库路径（*.db）"),
    db: Optional[Path] = typer.Option(
        None, "--db", help="数据库路径，默认 data/telearchive.db"
    ),
) -> None:
    """使用指定备份覆盖当前数据库，实现回滚。"""
    db_path = _resolve_db(db)
    rollback_db_from_backup(db_path, backup_db)
    console.print(f"[green]已回滚[/green] {db_path.resolve()} ← {backup_db.resolve()}")


@app.command("status")
def status_cmd(
    db: Optional[Path] = typer.Option(
        None, "--db", help="数据库路径，默认 data/telearchive.db"
    ),
) -> None:
    """查看各群聊消息统计与最近导入记录。"""
    db_path = _resolve_db(db)
    if not db_path.is_file():
        console.print(f"[red]数据库不存在[/red]: {db_path}，请先运行 ingest")
        raise typer.Exit(1)

    with Database(db_path) as database:
        chats = database.list_chat_stats()
        imports = database.import_history()
        logical, locations, media_found, media_missing = database.media_stats()

    if chats:
        table = Table(title="群聊概览")
        table.add_column("ID", justify="right")
        table.add_column("名称")
        table.add_column("消息数", justify="right")
        table.add_column("最早")
        table.add_column("最晚")

        for c in chats:
            earliest = _fmt_ts(c.earliest)
            latest = _fmt_ts(c.latest)
            table.add_row(str(c.chat_id), c.name, str(c.message_count), earliest, latest)
        console.print(table)
    else:
        console.print("[yellow]尚无聊天记录[/yellow]")

    if logical:
        console.print(
            f"\n媒体：逻辑附件 [cyan]{logical}[/cyan]，"
            f"路径记录 {locations}（含不同导出批次下的重复命名），"
            f"磁盘存在 [green]{media_found}[/green]，缺失 [red]{media_missing}[/red]"
        )
        console.print(
            "[dim]查询首选路径：message_media.preferred_absolute_path；"
            "全部路径：media_locations 表。[/dim]"
        )

    if imports:
        console.print()
        hist = Table(title="最近导入")
        hist.add_column("时间")
        hist.add_column("来源")
        hist.add_column("处理", justify="right")
        hist.add_column("新增", justify="right")
        hist.add_column("更新", justify="right")
        for row in imports:
            hist.add_row(
                row["imported_at"],
                _export_label(row["source_path"]),
                str(row["messages_seen"]),
                str(row["messages_new"]),
                str(row["messages_updated"]),
            )
        console.print(hist)


@app.command()
def gaps(
    chat_id: Optional[int] = typer.Option(
        None, "--chat-id", help="群聊 ID；省略则使用库中第一个群"
    ),
    min_gap: int = typer.Option(
        5, "--min-gap", help="仅显示连续缺失 message id 数 ≥ 此值的区段"
    ),
    db: Optional[Path] = typer.Option(
        None, "--db", help="数据库路径，默认 data/telearchive.db"
    ),
) -> None:
    """分析 message id 序列中的空洞（通常由群自动删消息导致）。"""
    db_path = _resolve_db(db)
    if not db_path.is_file():
        console.print(f"[red]数据库不存在[/red]: {db_path}")
        raise typer.Exit(1)

    with Database(db_path) as database:
        chats = database.list_chat_stats()
        if not chats:
            console.print("[yellow]尚无聊天记录[/yellow]")
            raise typer.Exit(0)
        target = chat_id if chat_id is not None else chats[0].chat_id
        chat_name = next((c.name for c in chats if c.chat_id == target), str(target))
        id_gaps = find_id_gaps(database._conn, target, min_gap=min_gap)
        coverage = export_coverage(database._conn, target)

    console.print(f"群聊：[cyan]{chat_name}[/cyan] (id={target})")

    if coverage:
        cov = Table(title="各导出批次贡献")
        cov.add_column("导出")
        cov.add_column("本批消息", justify="right")
        cov.add_column("首次入库", justify="right")
        for row in coverage:
            cov.add_row(
                _export_label(row.source_path),
                str(row.messages_seen),
                str(row.messages_new),
            )
        console.print(cov)

    if not id_gaps:
        console.print(f"\n未发现 ≥{min_gap} 的 message id 空洞。")
        return

    gap_table = Table(title=f"Message ID 空洞（≥{min_gap}）")
    gap_table.add_column("前一条 id", justify="right")
    gap_table.add_column("后一条 id", justify="right")
    gap_table.add_column("缺失条数", justify="right")
    for gap in id_gaps[:30]:
        gap_table.add_row(str(gap.after_id), str(gap.before_id), str(gap.missing_count))
    console.print(gap_table)
    if len(id_gaps) > 30:
        console.print(f"[dim]… 另有 {len(id_gaps) - 30} 段未显示[/dim]")


def _fmt_ts(ts: int | None) -> str:
    if ts is None or ts == 0:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _export_label(source: str) -> str:
    path = Path(source)
    if path.name == "result.json" and path.parent.name:
        return path.parent.name
    return path.name


if __name__ == "__main__":
    app()
